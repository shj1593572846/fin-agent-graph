"""
向量数据库持久化与检索模块：基于 ChromaDB 提供金融知识库切片的持久化存储与语义检索
"""

import os
import threading
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from rag.config import CHROMA_DIR, COLLECTION_NAME


class FinancialVectorStore:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(FinancialVectorStore, cls).__new__(cls)
                cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        """初始化 ChromaDB 持久化客户端与 Collection"""
        os.makedirs(CHROMA_DIR, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
        )
        # 获取或创建金融研报/财报专属集合
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Financial research reports & financial statements RAG store"}
        )

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """
        向 Chroma 批量写入分块及其元数据
        """
        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []

        for c in chunks:
            ids.append(c["chunk_id"])
            documents.append(c["text"])
            # Chroma metadata 要求值不能为 None
            metadatas.append({
                "doc_id": str(c.get("doc_id", "")),
                "chunk_index": int(c.get("chunk_index", 0)),
                "page": int(c.get("page", 1)),
                "title": str(c.get("title", "")),
                "category": str(c.get("category", "")),
                "stock_code": str(c.get("stock_code", "")),
                "stock_name": str(c.get("stock_name", "")),
            })

        # 分批写入，防止单次写入超出限制
        batch_size = 100
        total_added = 0
        for i in range(0, len(ids), batch_size):
            b_ids = ids[i:i + batch_size]
            b_docs = documents[i:i + batch_size]
            b_metas = metadatas[i:i + batch_size]
            self.collection.upsert(
                ids=b_ids,
                documents=b_docs,
                metadatas=b_metas
            )
            total_added += len(b_ids)

        return total_added

    def delete_by_doc_id(self, doc_id: str) -> bool:
        """根据文档 ID 删除其在 Chroma 中的所有分块"""
        try:
            self.collection.delete(where={"doc_id": doc_id})
            return True
        except Exception as e:
            print(f"⚠️ [VectorStore] 删除 doc_id={doc_id} 向量失败: {e}")
            return False

    def query_similarity(
        self,
        query_text: str,
        n_results: int = 5,
        category: Optional[str] = None,
        stock_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        按查询语义向量相似度匹配检索 top_k 个相关分块
        支持按分类 (研报分析 / 财报解读) 和股票代码精确过滤
        """
        if not query_text.strip():
            return []

        where_clause = None
        conditions = []

        if category and category != "全部":
            conditions.append({"category": category})
        if stock_code and stock_code.strip():
            conditions.append({"stock_code": stock_code.strip()})

        if len(conditions) == 1:
            where_clause = conditions[0]
        elif len(conditions) > 1:
            where_clause = {"$and": conditions}

        # 检查当前集合总数，防止请求 n_results 大于集合文档数
        total_count = self.collection.count()
        if total_count == 0:
            return []
        effective_n = min(n_results, total_count)

        kwargs = {
            "query_texts": [query_text],
            "n_results": effective_n,
        }
        if where_clause:
            kwargs["where"] = where_clause

        try:
            res = self.collection.query(**kwargs)
        except Exception as e:
            # 如果过滤条件未匹配到任何结果导致报错，安全降级为空
            print(f"⚠️ [VectorStore] 查询异常: {e}")
            return []

        results = []
        if res and "documents" in res and res["documents"]:
            docs = res["documents"][0]
            metas = res["metadatas"][0] if "metadatas" in res and res["metadatas"] else []
            dists = res["distances"][0] if "distances" in res and res["distances"] else []
            ids = res["ids"][0] if "ids" in res and res["ids"] else []

            for i in range(len(docs)):
                doc_text = docs[i]
                meta = metas[i] if i < len(metas) else {}
                dist = dists[i] if i < len(dists) else 1.0
                chunk_id = ids[i] if i < len(ids) else ""
                
                # 计算余弦相似度分数 (Chroma 默认使用 L2 或 Cosine distance)
                # 距离越小相似度越高，标准化为 0.0 ~ 1.0 的 score
                score = round(max(0.0, 1.0 - (dist / 2.0)), 4) if dist <= 2.0 else 0.5

                results.append({
                    "chunk_id": chunk_id,
                    "text": doc_text,
                    "score": score,
                    "distance": dist,
                    "doc_id": meta.get("doc_id", ""),
                    "title": meta.get("title", ""),
                    "category": meta.get("category", ""),
                    "stock_code": meta.get("stock_code", ""),
                    "stock_name": meta.get("stock_name", ""),
                    "page": meta.get("page", 1),
                    "chunk_index": meta.get("chunk_index", 0),
                })

        return results

    def count(self) -> int:
        """获取当前集合中分块总数"""
        try:
            return self.collection.count()
        except Exception:
            return 0


# 全局单例
vector_store = FinancialVectorStore()
