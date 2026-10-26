"""
RAG 核心服务层：文档生命周期管理、向量检索、大模型深度研报/财报解读问答
"""

import os
import sys
import json
import time
import uuid
import threading
from typing import List, Dict, Any, Optional

from rag.config import (
    DOCUMENTS_DIR,
    METADATA_FILE,
    SAMPLES_DIR,
    CATEGORY_RESEARCH,
    CATEGORY_FINANCIAL,
    VALID_CATEGORIES,
)
from rag.document_loader import load_document_content
from rag.text_splitter import split_document_pages
from rag.vector_store import vector_store
from rag.skill import financial_rag_skill, FinancialRAGSkill

# 导入项目中已有的大模型接口
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
_AGENT_DIR = os.path.join(_PROJECT_ROOT, "agent")
for _p in [_PROJECT_ROOT, _AGENT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

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


class FinancialRAGService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(FinancialRAGService, cls).__new__(cls)
                cls._instance._init_service()
        return cls._instance

    def _init_service(self):
        """初始化服务并加载元数据与专属问答 Skill"""
        self.metadata_lock = threading.Lock()
        self.skill = financial_rag_skill
        self._ensure_metadata_file()
        # 若知识库为空，自动预热加载样本数据
        self.init_samples_if_empty()

    def _ensure_metadata_file(self):
        """确保 metadata.json 文件存在且格式规范"""
        with self.metadata_lock:
            if not os.path.exists(METADATA_FILE):
                with open(METADATA_FILE, "w", encoding="utf-8") as f:
                    json.dump({"documents": []}, f, ensure_ascii=False, indent=2)

    def _load_metadata(self) -> Dict[str, Any]:
        """读取元数据文件"""
        with self.metadata_lock:
            try:
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [RAG] 读取 metadata.json 异常: {e}")
                return {"documents": []}

    def _save_metadata(self, data: Dict[str, Any]):
        """持久化元数据文件"""
        with self.metadata_lock:
            with open(METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def init_samples_if_empty(self):
        """如果知识库当前为空，自动导入预置的优质研报与财报分析样本"""
        meta = self._load_metadata()
        if meta.get("documents"):
            return  # 已经有文档，不重复初始化

        print("📚 [RAG Service] 检测到知识库为空，正在自动导入示例研报与财报解读样本...")
        samples = [
            {
                "file_name": "sample_maotai_financial_2024q1.md",
                "title": "贵州茅台2024年一季度财务报告全景透视与健康度分析",
                "category": CATEGORY_FINANCIAL,
                "stock_code": "600519",
                "stock_name": "贵州茅台",
            },
            {
                "file_name": "sample_catl_research_2024.md",
                "title": "宁德时代深度研报：全球动力电池龙头，技术代际压制与出海溢价",
                "category": CATEGORY_RESEARCH,
                "stock_code": "300750",
                "stock_name": "宁德时代",
            },
            {
                "file_name": "sample_byd_financial_research.md",
                "title": "比亚迪财务解读与投研策略：第五代DM混动颠覆与高端出海",
                "category": CATEGORY_RESEARCH,
                "stock_code": "002594",
                "stock_name": "比亚迪",
            },
        ]

        for s in samples:
            src_path = os.path.join(SAMPLES_DIR, s["file_name"])
            if os.path.exists(src_path):
                try:
                    with open(src_path, "rb") as f:
                        file_bytes = f.read()
                    self.save_and_index_document(
                        file_bytes=file_bytes,
                        filename=s["file_name"],
                        category=s["category"],
                        stock_code=s["stock_code"],
                        stock_name=s["stock_name"],
                        title=s["title"],
                    )
                    print(f"  ✅ 已成功导入样本: {s['title']}")
                except Exception as e:
                    print(f"  ❌ 导入样本 {s['file_name']} 失败: {e}")

    def save_and_index_document(
        self,
        file_bytes: bytes,
        filename: str,
        category: str = CATEGORY_RESEARCH,
        stock_code: str = "",
        stock_name: str = "",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        保存上传的文档、解析内容、分块切片并写入向量库持久化
        """
        if not file_bytes:
            raise ValueError("上传的文件内容为空")

        category_clean = category if category in VALID_CATEGORIES else CATEGORY_RESEARCH
        doc_id = f"doc_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
        # 确定标题与存储文件名
        base_name, ext = os.path.splitext(filename)
        clean_title = (title or "").strip() or base_name
        saved_filename = f"{doc_id}_{filename}"
        saved_path = os.path.join(DOCUMENTS_DIR, saved_filename)

        # 1. 写入本地原始文档存储
        with open(saved_path, "wb") as f:
            f.write(file_bytes)

        file_size = len(file_bytes)

        # 2. 调用多格式加载器解析文档
        pages_data = load_document_content(saved_path)
        if not pages_data:
            # 清理物理文件
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise ValueError(f"未能从文档中提取到有效文本内容，请确认文档未损坏或未被加密")

        # 3. 准备元数据结构
        upload_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        doc_meta = {
            "id": doc_id,
            "filename": saved_filename,
            "original_name": filename,
            "title": clean_title,
            "category": category_clean,
            "stock_code": stock_code.strip(),
            "stock_name": stock_name.strip(),
            "file_size": file_size,
            "file_size_human": f"{file_size / 1024:.1f} KB" if file_size < 1048576 else f"{file_size / (1024 * 1024):.2f} MB",
            "upload_time": upload_time_str,
            "chunk_count": 0,
            "summary": "",
            "file_path": saved_path,
        }

        # 4. 金融语义敏捷分块
        chunks = split_document_pages(pages_data, doc_meta)
        if not chunks:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise ValueError("文档内容过少或分块后无有效文本片段")

        doc_meta["chunk_count"] = len(chunks)
        # 提取前 200 字作为预览摘要
        first_text = chunks[0]["text"]
        doc_meta["summary"] = first_text[:220].strip() + ("..." if len(first_text) > 220 else "")

        # 5. 写入持久化向量库 Chroma
        vector_store.add_chunks(chunks)

        # 6. 保存文档元数据到 metadata.json
        meta_data = self._load_metadata()
        docs = meta_data.get("documents", [])
        # 头插法，保证最新上传置顶
        docs.insert(0, doc_meta)
        meta_data["documents"] = docs
        self._save_metadata(meta_data)

        return doc_meta

    def list_documents(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取文档列表，支持按分类及关键词搜索过滤"""
        meta_data = self._load_metadata()
        docs = meta_data.get("documents", [])

        filtered = []
        for d in docs:
            if category and category != "全部" and d.get("category") != category:
                continue
            if search and search.strip():
                kw = search.strip().lower()
                title = str(d.get("title", "")).lower()
                stock_code = str(d.get("stock_code", "")).lower()
                stock_name = str(d.get("stock_name", "")).lower()
                summary = str(d.get("summary", "")).lower()
                if not (kw in title or kw in stock_code or kw in stock_name or kw in summary):
                    continue
            filtered.append(d)

        return filtered

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取指定文档详细信息"""
        docs = self.list_documents()
        for d in docs:
            if d.get("id") == doc_id:
                return d
        return None

    def get_document_chunks(self, doc_id: str) -> List[Dict[str, Any]]:
        """获取指定文档在 Chroma 中的所有分块片段"""
        try:
            res = vector_store.collection.get(
                where={"doc_id": doc_id},
                include=["documents", "metadatas"]
            )
            chunks = []
            if res and "documents" in res and res["documents"]:
                for i in range(len(res["documents"])):
                    text = res["documents"][i]
                    meta = res["metadatas"][i] if "metadatas" in res and res["metadatas"] else {}
                    chunks.append({
                        "chunk_id": res["ids"][i],
                        "text": text,
                        "chunk_index": meta.get("chunk_index", i),
                        "page": meta.get("page", 1),
                        "title": meta.get("title", ""),
                        "category": meta.get("category", ""),
                        "stock_code": meta.get("stock_code", ""),
                        "stock_name": meta.get("stock_name", ""),
                    })
                # 按分块序号排序
                chunks.sort(key=lambda x: x.get("chunk_index", 0))
            return chunks
        except Exception as e:
            print(f"⚠️ [RAG] 获取 doc_id={doc_id} 分块异常: {e}")
            return []

    def delete_document(self, doc_id: str) -> bool:
        """删除文档：删除向量索引、原始文件及元数据记录"""
        # 1. 删除向量索引
        vector_store.delete_by_doc_id(doc_id)

        # 2. 删除物理文件
        doc = self.get_document(doc_id)
        if doc and "file_path" in doc:
            fpath = doc["file_path"]
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    print(f"⚠️ [RAG] 删除文档物理文件失败: {e}")

        # 3. 从 metadata.json 中剔除
        meta_data = self._load_metadata()
        docs = meta_data.get("documents", [])
        new_docs = [d for d in docs if d.get("id") != doc_id]
        meta_data["documents"] = new_docs
        self._save_metadata(meta_data)
        return True

    def query_rag(
        self,
        query: str,
        category: Optional[str] = None,
        stock_code: Optional[str] = None,
        top_k: int = 4,
        generate_answer: bool = True,
        session_id: str = "default",
        use_memory: Optional[bool] = None,
        search_mode: Optional[str] = "hybrid",
    ) -> Dict[str, Any]:
        """
        基于金融知识库智能问答 Skill 执行混合检索 (Vector + BM25 + RRF)、滑动窗口对话记忆关联与深度研报/财报分析
        """
        return self.skill.execute(
            query=query,
            category=category,
            stock_code=stock_code,
            top_k=top_k,
            generate_answer=generate_answer,
            session_id=session_id,
            use_memory=use_memory,
            search_mode=search_mode,
        )

    def get_memory_turns(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """获取指定会话在滑动窗口中的全部对话历史"""
        return self.skill.get_memory_turns(session_id)

    def clear_memory(self, session_id: Optional[str] = None) -> bool:
        """清空指定会话或全部滑动窗口记忆"""
        return self.skill.clear_memory(session_id)

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库总体统计数据"""
        docs = self.list_documents()
        total_docs = len(docs)
        research_docs = sum(1 for d in docs if d.get("category") == CATEGORY_RESEARCH)
        financial_docs = sum(1 for d in docs if d.get("category") == CATEGORY_FINANCIAL)
        total_chunks = vector_store.count()

        stocks_covered = set()
        for d in docs:
            code = d.get("stock_code")
            name = d.get("stock_name")
            if code or name:
                stocks_covered.add(f"{code} {name}".strip())

        return {
            "total_docs": total_docs,
            "research_docs": research_docs,
            "financial_docs": financial_docs,
            "total_chunks": total_chunks,
            "stocks_count": len(stocks_covered),
            "stocks_covered": list(stocks_covered),
        }


# 全局单例
rag_service = FinancialRAGService()
