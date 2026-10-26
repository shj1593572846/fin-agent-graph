"""
RAG 知识库 RESTful API 路由模块
提供研报分析与财报解读文档的上传、解析切片、向量检索、大模型深度问答与知识库状态管理
"""

import os
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from rag.rag_service import rag_service
from rag.skill import financial_rag_skill
from rag.config import CATEGORY_RESEARCH, CATEGORY_FINANCIAL

router = APIRouter(prefix="/api/rag", tags=["RAG 研报财报知识库"])


class RAGQueryRequest(BaseModel):
    query: str
    category: Optional[str] = None
    stock_code: Optional[str] = None
    top_k: int = 4
    generate_answer: bool = True
    session_id: Optional[str] = "default"
    use_memory: Optional[bool] = True
    search_mode: Optional[str] = "hybrid"


@router.get("/stats")
async def get_rag_stats():
    """获取知识库总体统计指标（文档数、分类分布、切片量、覆盖个股）"""
    try:
        stats = rag_service.get_stats()
        return {"success": True, "data": stats}
    except Exception as e:
        return {"success": False, "error": str(e), "data": {}}


@router.get("/skill")
async def get_rag_skill_info():
    """获取金融研报与财报问答 Skill 的自描述元数据及出入参契约"""
    try:
        return {"success": True, "data": financial_rag_skill.get_metadata()}
    except Exception as e:
        return {"success": False, "error": str(e), "data": {}}


@router.post("/skill/reload")
async def reload_rag_skill():
    """从 SKILL.md 文件热重载 Agent 人设与提示词配置"""
    try:
        ok = financial_rag_skill.reload()
        return {
            "success": ok,
            "message": "已成功从 SKILL.md 重新装载 Agent 设定与提示词！",
            "data": financial_rag_skill.get_metadata(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/memory")
async def get_rag_memory(session_id: str = "default"):
    """获取指定会话在滑动窗口中的全部对话历史与记忆统计"""
    try:
        turns = financial_rag_skill.get_memory_turns(session_id)
        stats = financial_rag_skill.get_memory_stats()
        return {
            "success": True,
            "session_id": session_id,
            "data": turns,
            "count": len(turns),
            "stats": stats,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "data": [], "count": 0}


@router.delete("/memory")
async def clear_rag_memory(session_id: Optional[str] = None):
    """清空指定会话或全部滑动窗口记忆"""
    try:
        financial_rag_skill.clear_memory(session_id)
        msg = f"会话 '{session_id}' 滑动窗口记忆已成功清空！" if session_id else "全部会话滑动窗口记忆已成功清空！"
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/documents")
async def get_documents(category: Optional[str] = None, search: Optional[str] = None):
    """查询已入库文档列表，支持分类筛选与标题/个股关键词搜索"""
    try:
        docs = rag_service.list_documents(category=category, search=search)
        return {"success": True, "data": docs, "count": len(docs)}
    except Exception as e:
        return {"success": False, "error": str(e), "data": [], "count": 0}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(CATEGORY_RESEARCH),
    title: Optional[str] = Form(None),
    stock_code: Optional[str] = Form(""),
    stock_name: Optional[str] = Form(""),
):
    """
    上传研报或财报文件（支持 PDF / DOCX / TXT / Markdown），
    服务端自动完成文本提取、金融语义分块切片并持久化至向量库
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未检测到有效的文件名")

    # 验证文件扩展名
    allowed_exts = [".pdf", ".docx", ".doc", ".txt", ".md", ".markdown"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        return {
            "success": False,
            "error": f"不支持的文件格式: {ext}，目前支持 {', '.join(allowed_exts)}",
        }

    try:
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            return {"success": False, "error": "上传的文件内容为空，请重新选择"}

        # 默认限制上传大小 50MB
        if len(file_bytes) > 50 * 1024 * 1024:
            return {"success": False, "error": "文件大小超出 50MB 限制"}

        doc_meta = rag_service.save_and_index_document(
            file_bytes=file_bytes,
            filename=file.filename,
            category=category,
            stock_code=stock_code or "",
            stock_name=stock_name or "",
            title=title,
        )

        return {
            "success": True,
            "data": doc_meta,
            "message": f"🎉 文档《{doc_meta['title']}》解析入库成功！共生成 {doc_meta['chunk_count']} 个知识向量切片。",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"文档解析入库失败: {str(e)}"}


@router.get("/documents/{doc_id}")
async def get_document_detail(doc_id: str):
    """获取指定文档基本信息与分块切片预览"""
    try:
        doc = rag_service.get_document(doc_id)
        if not doc:
            return {"success": False, "message": f"未找到 ID 为 {doc_id} 的文档"}
        chunks = rag_service.get_document_chunks(doc_id)
        return {
            "success": True,
            "data": {
                **doc,
                "chunks": chunks,
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(doc_id: str):
    """获取指定文档切分出的所有知识片段列表"""
    try:
        chunks = rag_service.get_document_chunks(doc_id)
        return {"success": True, "data": chunks, "count": len(chunks)}
    except Exception as e:
        return {"success": False, "error": str(e), "data": []}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """从知识库彻底删除文档、物理文件及其对应的向量索引"""
    try:
        doc = rag_service.get_document(doc_id)
        title = doc["title"] if doc else doc_id
        ok = rag_service.delete_document(doc_id)
        return {
            "success": ok,
            "message": f"文档《{title}》已从知识库成功移除并清理向量数据！",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/query")
async def query_knowledge_base(req: RAGQueryRequest):
    """
    研报财报智能问答：语义检索知识切片并调用大模型进行深度分析输出
    """
    try:
        res = rag_service.query_rag(
            query=req.query,
            category=req.category,
            stock_code=req.stock_code,
            top_k=req.top_k,
            generate_answer=req.generate_answer,
            session_id=req.session_id or "default",
            use_memory=req.use_memory if req.use_memory is not None else True,
            search_mode=req.search_mode or "hybrid",
        )
        return {"success": True, "data": res}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "data": {
                "query": req.query,
                "answer": f"抱歉，问答检索服务发生异常: {str(e)}",
                "sources": [],
            }
        }


@router.post("/init-samples")
async def init_samples():
    """手动重新导入内置的示范研报与财报解读样本"""
    try:
        rag_service.init_samples_if_empty()
        return {"success": True, "message": "示范样本已成功加载就绪！"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class FetchReportsRequest(BaseModel):
    symbol: Optional[str] = ""
    count: int = 5
    category: Optional[str] = "自动"
    rating: Optional[str] = "*"
    keyword: Optional[str] = ""
    selected_info_codes: Optional[list[str]] = None


@router.get("/preview-reports")
async def preview_institutional_reports(
    symbol: Optional[str] = "",
    count: int = 15,
    rating: Optional[str] = "*",
    keyword: Optional[str] = "",
):
    """
    在线预览财经机构与投行近期发布的最新研报列表（支持勾选按需入库）
    """
    try:
        from rag.report_fetcher import get_recent_reports_list
        items = get_recent_reports_list(
            symbol=symbol or "",
            count=count,
            rating=rating or "*",
            keyword=keyword or "",
        )
        return {"success": True, "data": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e), "data": [], "count": 0}


@router.post("/fetch-reports")
async def fetch_and_import_reports(req: FetchReportsRequest):
    """
    从权威机构/投行财经接口自动下载近期研报与财报解读，解析分块并写入 RAG 向量知识库
    """
    try:
        from rag.report_fetcher import download_and_import_reports
        res = download_and_import_reports(
            symbol=req.symbol or "",
            count=req.count,
            category=req.category or "自动",
            rating=req.rating or "*",
            keyword=req.keyword or "",
            selected_info_codes=req.selected_info_codes,
        )
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"抓取机构研报入库异常: {str(e)}", "imported_count": 0}

