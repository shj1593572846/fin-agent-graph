"""
rag/skill.py
RAG 研报分析与财报解读智能问答 Skill 模块

将原先耦合在知识库服务中的大模型问答能力抽象为符合标准规范的 Skill（智能体技能）。
具备如下特性：
1. 标准化接口：提供清晰的 Input / Output Pydantic Schema 与元数据定义；
2. 解耦与可复用：独立封装检索 (retrieve)、上下文构建 (build_context)、深度研报分析 (generate_analysis) 与主执行流程 (execute)；
3. 工具化集成：通过 as_tool() 与 as_retrieval_tool() 支持无缝导出为 LangChain / LangGraph 智能体可直接调用的 Tool；
4. 优雅降级与可观测：包含完整的异常容错与执行耗时度量。
"""

import os
import sys
import time
import yaml
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

# 确保模块搜索路径包含当前目录与项目根目录
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
_AGENT_DIR = os.path.join(_PROJECT_ROOT, "agent")
for _p in [_PROJECT_ROOT, _AGENT_DIR, _CURRENT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rag.config import (
    CATEGORY_RESEARCH,
    CATEGORY_FINANCIAL,
    VALID_CATEGORIES,
)
from rag.vector_store import vector_store
from rag.memory import sliding_window_memory, SlidingWindowMemory

try:
    from agent.agents import get_llm, is_api_key_configured
except ImportError:
    def is_api_key_configured():
        return bool(os.getenv("OPENAI_API_KEY"))

    def get_llm(temperature=0.2, max_tokens=2200):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("MODEL_NAME", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            temperature=temperature,
            max_tokens=max_tokens,
        )


# ==============================================================================
# Skill 标准出入参 Schema 定义
# ==============================================================================
class RAGQueryInput(BaseModel):
    """金融知识库问答 Skill 输入参数契约"""
    query: str = Field(..., description="投研咨询问题、行业研究关注点或财务指标分析需求")
    category: Optional[str] = Field(None, description="分类过滤：'研报分析' 或 '财报解读'，留空或'全部'则不限分类")
    stock_code: Optional[str] = Field(None, description="可选股票代码（如 '600519'），留空则全局匹配或自动继承上下文标的")
    top_k: int = Field(4, ge=1, le=10, description="向量相似度检索匹配的最优知识切片条数")
    generate_answer: bool = Field(True, description="是否调用大模型基于切片生成专业研报分析，为 False 时仅返回原始切片")
    session_id: Optional[str] = Field("default", description="多轮对话会话 ID，用于隔离维护滑动窗口记忆")
    use_memory: Optional[bool] = Field(True, description="是否启用滑动窗口多轮对话历史记忆")
    search_mode: Optional[str] = Field("hybrid", description="检索模式：'hybrid' (混合检索：向量+BM25+RRF), 'vector' (仅语义向量), 'bm25' (仅字面关键词)")


class RAGChunkItem(BaseModel):
    """知识库分块信息"""
    chunk_id: str
    text: str
    chunk_index: int = 0
    page: int = 1
    title: str = ""
    category: str = ""
    stock_code: str = ""
    stock_name: str = ""
    score: float = 0.0


class RAGQueryResult(BaseModel):
    """金融知识库问答 Skill 执行输出结果契约"""
    query: str
    category: str = "全部"
    stock_code: Optional[str] = None
    answer: str = ""
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    session_id: str = "default"
    memory_turns: int = 0
    memory_window_size: int = 5
    search_mode: str = "hybrid"
    success: bool = True
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


# ==============================================================================
# Skill 基类抽象
# ==============================================================================
class BaseSkill:
    """标准智能体技能基类"""
    name: str = "base_skill"
    display_name: str = "Base Skill"
    description: str = "Base skill description"
    version: str = "1.0.0"
    input_schema = None
    output_schema = None

    def execute(self, *args, **kwargs) -> Any:
        raise NotImplementedError("Skill 子类必须实现 execute 方法")

    def __call__(self, *args, **kwargs) -> Any:
        return self.execute(*args, **kwargs)

    def get_metadata(self) -> Dict[str, Any]:
        """获取技能自描述元数据"""
        meta = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
        }
        if self.input_schema and hasattr(self.input_schema, "schema"):
            meta["input_schema"] = self.input_schema.schema()
        if self.output_schema and hasattr(self.output_schema, "schema"):
            meta["output_schema"] = self.output_schema.schema()
        return meta

    def as_tool(self):
        """导出为 LangChain 标准 Tool"""
        raise NotImplementedError("Skill 子类可按需实现 as_tool 方法")


# ==============================================================================
# SKILL.md 文件定位与解析加载器
# ==============================================================================
def find_skill_file(explicit_path: Optional[str] = None) -> Optional[str]:
    """定位 SKILL.md / Skill.md 规范配置文件"""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path

    candidates = [
        os.path.join(_CURRENT_DIR, "SKILL.md"),
        os.path.join(_CURRENT_DIR, "Skill.md"),
        os.path.join(_CURRENT_DIR, "skill.md"),
        os.path.join(_PROJECT_ROOT, ".agents", "skills", "financial-rag-agent", "SKILL.md"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def parse_skill_markdown(file_path: str) -> Dict[str, Any]:
    """
    解析 SKILL.md 文件中的 YAML Frontmatter 元数据与 Markdown 正文指令 Prompt
    """
    if not file_path or not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"⚠️ [SKILL.md] 读取技能文件失败 ({file_path}): {e}")
        return {}

    meta = {}
    body = content.strip()

    # 提取 YAML Frontmatter 元数据
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw_frontmatter = parts[1].strip()
            body = parts[2].strip()
            try:
                parsed = yaml.safe_load(raw_frontmatter)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception as ye:
                print(f"⚠️ [SKILL.md] 解析 YAML Frontmatter 异常: {ye}")

    meta["instructions"] = body
    meta["file_path"] = file_path
    return meta


# ==============================================================================
# 核心金融知识库问答 Skill 实现 (支持 SKILL.md 外部化指定 Agent)
# ==============================================================================
class FinancialRAGSkill(BaseSkill):
    """
    金融研报分析与财报解读智能问答 Skill (Financial RAG Q&A Skill)
    
    职责：
    1. 接收用户的投研/财务问题与筛选条件；
    2. 基于 Chroma 向量库执行金融专业语义相似度检索；
    3. 规范拼接结构化投研上下文资料；
    4. 装载顶尖证券研究所行业首席分析师兼 CPA 人设 Prompt 调用大模型；
    5. 输出结构严谨的投研分析报告与来源依据切片。
    """
    name: str = "financial_rag_qa"
    display_name: str = "研报分析与财报解读智能问答 Skill"
    description: str = (
        "检索本地研报分析与财报解读向量知识库，基于高相关知识切片由顶尖金融行业分析师大模型"
        "生成深度投研研报与财务指标洞察（涵盖成长性、盈利质量、杜邦分析、投资评级与催化剂）。"
    )
    version: str = "1.0.0"
    role: str = "顶尖证券研究所行业首席分析师兼注册会计师（CPA）"
    temperature: float = 0.2
    max_tokens: int = 2500
    top_k: int = 4
    enable_memory: bool = True
    memory_window_size: int = 5
    search_mode: str = "hybrid"
    skill_file: Optional[str] = None
    input_schema = RAGQueryInput
    output_schema = RAGQueryResult

    # 兜底默认金融行业首席分析师与注册会计师 System Prompt
    DEFAULT_SYSTEM_PROMPT = (
        "你是一位具备十余年资深经验的顶尖证券研究所行业首席分析师兼注册会计师（CPA）。\n"
        "你的任务是基于提供的【研报分析】与【财报解读】知识库参考资料，精准、深入、客观地回答用户的投研或财务问题。\n\n"
        "【输出专业规范】\n"
        "1. 严谨引用数据：优先引用资料中的关键财务指标（如营收、归母净利润、毛利率、扣非净利、现金流、PE/PB 估值、目标价等）；\n"
        "2. 结构清晰：使用 Markdown 格式，通过分级标题、要点列表或数据对比表格清晰展现核心观点；\n"
        "3. 核心维度涵盖：\n"
        "   - 财报解读需注重：成长性、盈利质量、杜邦分析、现金流安全边际与潜在财务瑕疵；\n"
        "   - 研报分析需注重：投资评级、核心催化剂、竞争护城河、技术代际壁垒与估值空间；\n"
        "4. 真实客观：若资料中未提及某项数据，应如实客观说明，严禁凭空捏造财务数字。"
    )

    def __init__(self, skill_file: Optional[str] = None, system_prompt: Optional[str] = None):
        self.memory = sliding_window_memory
        self.load_from_skill_md(skill_file=skill_file)
        if system_prompt:
            self.system_prompt = system_prompt

    def load_from_skill_md(self, skill_file: Optional[str] = None) -> bool:
        """通过 SKILL.md / Skill.md 外部化定义指定 Agent 人设、运行参数与提示词指令"""
        target_path = find_skill_file(skill_file)
        if target_path:
            spec = parse_skill_markdown(target_path)
            self.skill_file = target_path
            if spec.get("name"):
                self.name = spec["name"]
            if spec.get("display_name"):
                self.display_name = spec["display_name"]
            if spec.get("description"):
                self.description = spec["description"]
            if spec.get("version"):
                self.version = str(spec["version"])
            if spec.get("role"):
                self.role = spec["role"]
            if spec.get("temperature") is not None:
                self.temperature = float(spec["temperature"])
            if spec.get("max_tokens") is not None:
                self.max_tokens = int(spec["max_tokens"])
            if spec.get("top_k") is not None:
                self.top_k = int(spec["top_k"])
            if spec.get("enable_memory") is not None:
                self.enable_memory = bool(spec["enable_memory"])
            if spec.get("memory_window_size") is not None:
                self.memory_window_size = max(1, int(spec["memory_window_size"]))
                self.memory.set_window_size(self.memory_window_size)
            if spec.get("search_mode"):
                self.search_mode = str(spec["search_mode"]).strip().lower()
            if spec.get("instructions"):
                self.system_prompt = spec["instructions"]
            rel_path = os.path.relpath(target_path, _PROJECT_ROOT) if _PROJECT_ROOT in target_path else target_path
            print(f"📘 [Skill] 成功从 {rel_path} 装载 Agent 设定 (Role={self.role}, SearchMode={self.search_mode}, MemoryWindow={self.memory_window_size})")
            return True
        else:
            self.skill_file = None
            self.system_prompt = self.DEFAULT_SYSTEM_PROMPT
            return False

    def reload(self) -> bool:
        """从关联的 SKILL.md 文件热重载 Agent 定义与提示词"""
        return self.load_from_skill_md(self.skill_file)

    def get_metadata(self) -> Dict[str, Any]:
        """获取技能自描述元数据，包含由 SKILL.md 指定的 Agent 人设、记忆配置与出入参契约"""
        meta = super().get_metadata()
        meta.update({
            "role": self.role,
            "skill_file": self.skill_file,
            "skill_file_relative": os.path.relpath(self.skill_file, _PROJECT_ROOT) if self.skill_file else None,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_k": self.top_k,
            "enable_memory": self.enable_memory,
            "memory_window_size": self.memory_window_size,
            "memory_stats": self.memory.get_stats(),
            "search_mode": self.search_mode,
            "retrieval_strategy": "Hybrid (Dense Vector + BM25 Sparse + RRF)",
            "instructions_preview": (self.system_prompt[:260] + "...") if len(self.system_prompt) > 260 else self.system_prompt,
        })
        return meta

    def get_memory_turns(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """获取指定会话在滑动窗口中的全部对话历史"""
        return self.memory.get_turns(session_id)

    def clear_memory(self, session_id: Optional[str] = None) -> bool:
        """清空指定会话或全部滑动窗口记忆"""
        return self.memory.clear(session_id)

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取当前滑动窗口状态统计"""
        return self.memory.get_stats()

    def retrieve(
        self,
        query: str,
        category: Optional[str] = None,
        stock_code: Optional[str] = None,
        top_k: int = 4,
        search_mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        步骤 1：检索知识库切片（默认采用混合检索 Hybrid Search: 稠密向量 + BM25稀疏 + RRF倒数排名融合）
        """
        mode = (search_mode or self.search_mode or "hybrid").lower().strip()
        category_clean = category if category in VALID_CATEGORIES else None

        if mode == "bm25":
            matched_chunks = vector_store.query_bm25(
                query_text=query,
                n_results=top_k,
                category=category_clean,
                stock_code=stock_code,
            )
        elif mode == "vector":
            matched_chunks = vector_store.query_similarity(
                query_text=query,
                n_results=top_k,
                category=category_clean,
                stock_code=stock_code,
            )
        else:
            # 默认混合检索模式 (Hybrid: Dense Vector + BM25 Sparse + RRF Fusion)
            matched_chunks = vector_store.query_hybrid(
                query_text=query,
                n_results=top_k,
                category=category_clean,
                stock_code=stock_code,
            )

        # 若按特定分类未匹配到结果，尝试跨分类重试以防漏检
        if not matched_chunks and category_clean:
            if mode == "bm25":
                matched_chunks = vector_store.query_bm25(query_text=query, n_results=top_k, category=None, stock_code=stock_code)
            elif mode == "vector":
                matched_chunks = vector_store.query_similarity(query_text=query, n_results=top_k, category=None, stock_code=stock_code)
            else:
                matched_chunks = vector_store.query_hybrid(query_text=query, n_results=top_k, category=None, stock_code=stock_code)

        return matched_chunks

    def build_context(self, chunks: List[Dict[str, Any]]) -> str:
        """
        步骤 2：将检索到的切片格式化为标准上下文引述文本块
        """
        if not chunks:
            return ""
        context_blocks = []
        for idx, c in enumerate(chunks):
            doc_tag = (
                f"【资料 {idx+1}】《{c.get('title', '未知文献')}》 "
                f"({c.get('category', '研报/财报')} | 标的: {c.get('stock_code', '')} {c.get('stock_name', '')} | 页码: {c.get('page', 1)})"
            )
            context_blocks.append(f"{doc_tag}\n{c.get('text', '')}")
        return "\n\n----------------------------------------\n\n".join(context_blocks)

    def generate_analysis(
        self,
        query: str,
        context_str: str,
        session_id: str = "default",
        use_memory: bool = True,
        system_prompt_override: Optional[str] = None
    ) -> str:
        """
        步骤 3：结合滑动窗口历史消息与检索切片，构造 Prompt 调用大模型进行深度研报问答分析
        """
        sys_prompt = system_prompt_override or self.system_prompt
        user_prompt = (
            f"【用户咨询问题】\n{query}\n\n"
            f"【检索到的研报与财报资料库】\n{context_str}\n\n"
            "请基于以上研报财报资料及前序对话上下文，给出专业、详实的投研分析与深度解答："
        )

        try:
            llm = get_llm(temperature=self.temperature, max_tokens=self.max_tokens)
            from langchain_core.messages import SystemMessage, HumanMessage

            messages = [SystemMessage(content=sys_prompt)]

            # 注入滑动窗口历史对话消息
            if use_memory:
                history_msgs = self.memory.get_history_messages(session_id)
                if history_msgs:
                    messages.extend(history_msgs)

            messages.append(HumanMessage(content=user_prompt))

            response = llm.invoke(messages)
            answer_text = response.content if hasattr(response, "content") else str(response)
            if isinstance(answer_text, list):
                answer_text = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in answer_text)
            return str(answer_text or "").strip()
        except Exception as e:
            print(f"❌ [FinancialRAGSkill LLM Error]: {e}")
            raise e

    def execute(
        self,
        query: str = "",
        category: Optional[str] = None,
        stock_code: Optional[str] = None,
        top_k: int = 4,
        generate_answer: bool = True,
        session_id: str = "default",
        use_memory: Optional[bool] = None,
        search_mode: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        主执行入口：协同滑动窗口记忆、混合检索 (Vector+BM25+RRF)、切片组装、大模型分析并输出统一规范结果
        """
        t_start = time.time()
        query_clean = str(query or "").strip()
        effective_cat = category if category in VALID_CATEGORIES else "全部"
        s_id = (session_id or "default").strip()
        effective_use_memory = self.enable_memory if use_memory is None else bool(use_memory)
        effective_search_mode = (search_mode or self.search_mode or "hybrid").lower().strip()

        # 空查询校验
        if not query_clean:
            return {
                "query": query,
                "category": effective_cat,
                "stock_code": stock_code,
                "answer": "请输入您想咨询的研报核心逻辑或财报财务指标问题。",
                "sources": [],
                "session_id": s_id,
                "memory_turns": len(self.memory.get_turns(s_id)),
                "memory_window_size": self.memory.window_size,
                "search_mode": effective_search_mode,
                "success": True,
                "elapsed_seconds": round(time.time() - t_start, 3),
            }

        # 上下文标的指代消歧：若当前未传入股票代码且启用了记忆，尝试从滑动窗口前序对话回溯获取标的代码
        resolved_stock_code = (stock_code or "").strip() or None
        if not resolved_stock_code and effective_use_memory:
            inherited_code = self.memory.get_last_stock_code(s_id)
            if inherited_code:
                resolved_stock_code = inherited_code

        try:
            # 1. 混合检索（语义向量 + BM25 + RRF 融合重排）
            matched_chunks = self.retrieve(
                query=query_clean,
                category=category,
                stock_code=resolved_stock_code,
                top_k=top_k or self.top_k,
                search_mode=effective_search_mode,
            )

            # 2. 无匹配处理
            if not matched_chunks:
                empty_msg = (
                    "🔍 知识库中暂未检索到与您提问高度相关的研报或财报内容。\n\n"
                    "建议您：\n"
                    "1. 上传相关的个股研报 PDF 或财报文件；\n"
                    "2. 尝试换用更明确的标的名称（如「贵州茅台」、「宁德时代」、「比亚迪」）或核心财务指标（如「营收增长率」、「毛利率」、「投资评级」）。"
                )
                return {
                    "query": query_clean,
                    "category": effective_cat,
                    "stock_code": resolved_stock_code,
                    "answer": empty_msg,
                    "sources": [],
                    "session_id": s_id,
                    "memory_turns": len(self.memory.get_turns(s_id)),
                    "memory_window_size": self.memory.window_size,
                    "search_mode": effective_search_mode,
                    "success": True,
                    "elapsed_seconds": round(time.time() - t_start, 3),
                }

            # 3. 仅需要切片模式（无需 LLM 生成）
            if not generate_answer:
                return {
                    "query": query_clean,
                    "category": effective_cat,
                    "stock_code": resolved_stock_code,
                    "answer": "",
                    "sources": matched_chunks,
                    "session_id": s_id,
                    "memory_turns": len(self.memory.get_turns(s_id)),
                    "memory_window_size": self.memory.window_size,
                    "search_mode": effective_search_mode,
                    "success": True,
                    "elapsed_seconds": round(time.time() - t_start, 3),
                }

            # 4. 上下文合成与深度问答（带滑动窗口历史）
            context_str = self.build_context(matched_chunks)
            try:
                answer_text = self.generate_analysis(
                    query=query_clean,
                    context_str=context_str,
                    session_id=s_id,
                    use_memory=effective_use_memory,
                )
            except Exception as llm_err:
                # 优雅降级：LLM 异常时直接呈现知识库原文切片
                fallback_sample = matched_chunks[0].get("text", "")
                answer_text = (
                    f"⚠️ 大模型分析生成暂时异常 ({type(llm_err).__name__}: {str(llm_err)})。\n\n"
                    f"为您直接提取知识库中最匹配的原文段落如下：\n\n"
                    f"{fallback_sample}"
                )

            # 5. 将本轮对话记录存入滑动窗口记忆中
            if effective_use_memory and answer_text and generate_answer:
                stock_name = ""
                if matched_chunks:
                    stock_name = matched_chunks[0].get("stock_name", "")
                self.memory.add_turn(
                    session_id=s_id,
                    query=query_clean,
                    answer=answer_text,
                    stock_code=resolved_stock_code,
                    stock_name=stock_name,
                    category=effective_cat,
                )

            return {
                "query": query_clean,
                "category": effective_cat,
                "stock_code": resolved_stock_code,
                "answer": answer_text,
                "sources": matched_chunks,
                "session_id": s_id,
                "memory_turns": len(self.memory.get_turns(s_id)),
                "memory_window_size": self.memory.window_size,
                "search_mode": effective_search_mode,
                "success": True,
                "elapsed_seconds": round(time.time() - t_start, 3),
            }

        except Exception as e:
            return {
                "query": query_clean,
                "category": effective_cat,
                "stock_code": resolved_stock_code,
                "answer": f"抱歉，问答检索服务发生异常: {str(e)}",
                "sources": [],
                "session_id": s_id,
                "memory_turns": len(self.memory.get_turns(s_id)),
                "memory_window_size": self.memory.window_size,
                "search_mode": effective_search_mode,
                "success": False,
                "error": str(e),
                "elapsed_seconds": round(time.time() - t_start, 3),
            }

    def as_tool(self):
        """
        导出为 LangChain StructuredTool，供 LangGraph 或 ReAct Agent 作为智能体工具使用
        """
        try:
            from langchain_core.tools import StructuredTool

            def _tool_entrypoint(query: str, category: Optional[str] = None, stock_code: Optional[str] = None, top_k: int = 4) -> str:
                res = self.execute(query=query, category=category, stock_code=stock_code, top_k=top_k, generate_answer=True)
                ans = res.get("answer", "")
                sources = res.get("sources", [])
                src_summary = f"\n\n（参考知识库切片数：{len(sources)}）" if sources else ""
                return ans + src_summary

            return StructuredTool.from_function(
                func=_tool_entrypoint,
                name=self.name,
                description=self.description,
                args_schema=self.input_schema,
            )
        except Exception as e:
            print(f"⚠️ [FinancialRAGSkill] 导出为 LangChain Tool 异常: {e}")
            return None

    def as_retrieval_tool(self):
        """
        导出为轻量级检索 Tool（仅返回高相关知识片段原文，不重复调用大模型，供下游智能体自己分析推理）
        """
        try:
            from langchain_core.tools import tool

            @tool
            def query_financial_rag_knowledge(query: str, category: str = "", stock_code: str = "") -> str:
                """
                检索本地研报分析与财报解读 RAG 知识库。
                当需要查询个股深度券商研报、机构投资评级、目标价、业绩催化剂，或解读企业季报/年报财务指标（营收、净利润、毛利率、现金流等）时调用此工具。
                参数:
                - query: 查询问题或关键词（如'贵州茅台一季度净利润增速与毛利率'、'宁德时代核心投资逻辑'）
                - category: 可选分类过滤，'研报分析' 或 '财报解读'，留空则不限分类
                - stock_code: 可选股票代码（如 '600519'），留空则全局语义匹配
                """
                cat = category if category in VALID_CATEGORIES else None
                res = self.execute(query=query, category=cat, stock_code=stock_code, top_k=3, generate_answer=False)
                sources = res.get("sources", [])
                if not sources:
                    return f"在 RAG 知识库中未检索到与「{query}」相关的研报或财报切片。"

                output = [f"=== 本地研报与财报 RAG 知识库检索结果（共匹配到 {len(sources)} 条高相关知识切片）==="]
                for idx, s in enumerate(sources):
                    score_pct = int(s.get("score", 0) * 100)
                    output.append(
                        f"\n【切片 {idx+1}】《{s.get('title')}》 ({s.get('category')} | 标的: {s.get('stock_code')} {s.get('stock_name')}) [相似度: {score_pct}%]"
                    )
                    output.append(s.get("text", ""))
                return "\n".join(output)

            return query_financial_rag_knowledge
        except Exception as e:
            print(f"⚠️ [FinancialRAGSkill] 导出为检索 Tool 异常: {e}")
            return None


# 全局单例
financial_rag_skill = FinancialRAGSkill()
# 别名
rag_skill = financial_rag_skill
