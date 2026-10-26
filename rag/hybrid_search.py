"""
rag/hybrid_search.py
金融知识库混合检索引擎 (Hybrid Search Engine)

融合两路检索：
1. 稠密向量语义检索 (Dense Vector Search)：捕捉深层金融语义、意图与同义表达；
2. 稀疏字面关键词检索 (Sparse BM25 Search)：精准命中股票代码、公司简称、专有财务比率与精确数值；
3. 倒数排名融合 (Reciprocal Rank Fusion, RRF)：工业级两路召回排序融合算法，消弭异构分数分布差异。
"""

import math
import re
from typing import List, Dict, Any, Optional, Set
from collections import Counter


# 金融核心专有词汇表（用于提高关键财务指标与投研术语的切词权重）
FINANCIAL_KEYWORDS: Set[str] = {
    "营业收入", "营收", "净利润", "归母净利润", "扣非净利润", "毛利率", "净利率",
    "净资产收益率", "roe", "roa", "自由现金流", "经营性现金流", "资本开支", "资产负债率",
    "研发费用", "研发投入", "投资评级", "买入", "增持", "中性", "减持", "目标价", "估值",
    "市盈率", "pe", "市净率", "pb", "ev/ebitda", "护城河", "催化剂", "市场份额", "市占率",
    "产能利用率", "渗透率", "碳酸锂", "动力电池", "储能", "白酒", "半导体", "新能源", "算力"
}


def tokenize_financial_text(text: str) -> List[str]:
    """
    轻量级无依赖金融文本分词器：
    1. 提取英文代码、指标缩写与数字 (如 600519, 2024Q1, 15.8%, ROE, PE)；
    2. 优先匹配金融专有词表；
    3. 中文部分生成 1-gram (单字) 与 2-gram (双字相邻组合)，保证字面匹配的高召回率。
    """
    if not text:
        return []

    tokens: List[str] = []
    text_lower = text.lower()

    # 1. 提取数字、百分比与英文字符串 (如 600519, 15.8%, roe, 2024)
    alphanumeric_tokens = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?%?", text_lower)
    tokens.extend(alphanumeric_tokens)

    # 2. 金融关键专有词先行匹配
    for kw in FINANCIAL_KEYWORDS:
        if kw in text_lower:
            tokens.append(kw)

    # 3. 提取所有中文文本段并构建 1-gram 与 2-gram
    chinese_blocks = re.findall(r"[\u4e00-\u9fa5]+", text_lower)
    for block in chinese_blocks:
        b_len = len(block)
        # 单字 unigram
        for char in block:
            tokens.append(char)
        # 双字 bigram
        if b_len >= 2:
            for j in range(b_len - 1):
                tokens.append(block[j:j + 2])
        # 三字 trigram（仅针对 3~4 字小短语）
        if 3 <= b_len <= 6:
            for j in range(b_len - 2):
                tokens.append(block[j:j + 3])

    return tokens


class BM25Index:
    """
    针对金融知识切片的高性能内存 BM25 稀疏检索索引
    遵循 Okapi BM25 标准算法：k1=1.5, b=0.75
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = 0
        self.avg_doc_len = 0.0
        # doc_id -> token counts
        self.doc_lengths: Dict[str, int] = {}
        # token -> set of chunk_ids
        self.inverted_index: Dict[str, Set[str]] = {}
        # chunk_id -> Counter(token -> freq)
        self.doc_term_freqs: Dict[str, Counter] = {}
        # token -> idf
        self.idf_cache: Dict[str, float] = {}
        # chunk_id -> chunk dict
        self.chunks_map: Dict[str, Dict[str, Any]] = {}

    def fit(self, chunks: List[Dict[str, Any]]):
        """为全量切片构建或重建 BM25 倒排索引"""
        self.doc_count = len(chunks)
        if self.doc_count == 0:
            self.avg_doc_len = 0.0
            return

        total_length = 0
        self.doc_lengths.clear()
        self.inverted_index.clear()
        self.doc_term_freqs.clear()
        self.chunks_map.clear()

        for c in chunks:
            cid = c.get("chunk_id") or str(c.get("id", ""))
            self.chunks_map[cid] = c

            # 将标题、股票名与正文合并形成检索文本（标题权重强化）
            combined_text = (
                f"{c.get('title', '')} {c.get('stock_name', '')} {c.get('stock_code', '')} "
                f"{c.get('title', '')} {c.get('text', '')}"
            )
            tokens = tokenize_financial_text(combined_text)
            doc_len = len(tokens)
            self.doc_lengths[cid] = doc_len
            total_length += doc_len

            tf = Counter(tokens)
            self.doc_term_freqs[cid] = tf

            for t in tf.keys():
                if t not in self.inverted_index:
                    self.inverted_index[t] = set()
                self.inverted_index[t].add(cid)

        self.avg_doc_len = total_length / self.doc_count

        # 预计算所有词项的 IDF
        self.idf_cache.clear()
        for t, doc_set in self.inverted_index.items():
            n = len(doc_set)
            # Okapi BM25 IDF 平滑公式
            self.idf_cache[t] = math.log((self.doc_count - n + 0.5) / (n + 0.5) + 1.0)

    def search(
        self,
        query: str,
        n_results: int = 5,
        stock_code_filter: Optional[str] = None,
        category_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        基于 BM25 算法计算每个切片与查询词项的字面匹配度
        """
        query_tokens = tokenize_financial_text(query)
        if not query_tokens or self.doc_count == 0:
            return []

        # 找到包含任意查询词的候选文档
        candidate_ids: Set[str] = set()
        for t in query_tokens:
            if t in self.inverted_index:
                candidate_ids.update(self.inverted_index[t])

        if not candidate_ids:
            return []

        scores: Dict[str, float] = {}
        target_code = (stock_code_filter or "").strip()
        target_cat = (category_filter or "").strip()

        for cid in candidate_ids:
            chunk = self.chunks_map.get(cid)
            if not chunk:
                continue

            # 过滤条件筛选
            if target_code and str(chunk.get("stock_code", "")).strip() != target_code:
                continue
            if target_cat and target_cat != "全部" and str(chunk.get("category", "")).strip() != target_cat:
                continue

            doc_len = self.doc_lengths.get(cid, 0)
            tf = self.doc_term_freqs.get(cid, Counter())
            bm25_score = 0.0

            for t in query_tokens:
                f = tf.get(t, 0)
                if f > 0:
                    idf = self.idf_cache.get(t, 0.0)
                    numerator = f * (self.k1 + 1.0)
                    denominator = f + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_len + 1e-6)))
                    bm25_score += idf * (numerator / (denominator + 1e-6))

            # 精确匹配增益：如果股票代码或股票简称直接完整匹配，给予大幅加权
            c_code = str(chunk.get("stock_code", "")).strip()
            c_name = str(chunk.get("stock_name", "")).strip()
            c_title = str(chunk.get("title", "")).strip()

            if c_code and c_code in query:
                bm25_score += 4.0
            if c_name and c_name in query:
                bm25_score += 3.0
            if c_title and any(w in c_title for w in ["深度", "研报", "财报", "一季", "年报"]):
                bm25_score += 0.5

            if bm25_score > 0:
                scores[cid] = bm25_score

        if not scores:
            return []

        # 排序并取 Top-N
        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n_results]
        max_score = sorted_items[0][1] if sorted_items else 1.0

        results = []
        for rank, (cid, raw_score) in enumerate(sorted_items, 1):
            c = dict(self.chunks_map[cid])
            # 归一化稀疏分数为 0.0 ~ 1.0
            norm_score = round(min(1.0, raw_score / (max_score + 1e-6)), 4)
            c["score"] = norm_score
            c["bm25_raw_score"] = round(raw_score, 3)
            c["sparse_rank"] = rank
            c["retrieval_method"] = "bm25"
            results.append(c)

        return results


def reciprocal_rank_fusion(
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]],
    top_k: int = 5,
    rrf_k: int = 60,
    w_dense: float = 0.5,
    w_sparse: float = 0.5
) -> List[Dict[str, Any]]:
    """
    标准倒数排名融合算法 (Reciprocal Rank Fusion, RRF)
    公式：RRF_Score(d) = w_dense * (1 / (k + rank_dense(d))) + w_sparse * (1 / (k + rank_sparse(d)))
    
    优势：
    1. 不依赖向量相似度与 BM25 分数的数值尺度是否一致，彻底避免某一方分值偏大支配全场的问题；
    2. 能让在两路检索中排名均居前的切片强势凸显；
    3. 能让命中精确代码/专有名词但语义向量略有偏差的高价值切片被精准捕获。
    """
    fused_scores: Dict[str, float] = {}
    fused_chunks: Dict[str, Dict[str, Any]] = {}
    dense_ranks: Dict[str, int] = {}
    sparse_ranks: Dict[str, int] = {}

    # 1. 统计稠密向量排名
    for rank, c in enumerate(dense_results, 1):
        cid = c.get("chunk_id")
        if not cid:
            continue
        fused_chunks[cid] = c
        dense_ranks[cid] = rank
        rrf_contrib = w_dense * (1.0 / (rrf_k + rank))
        fused_scores[cid] = fused_scores.get(cid, 0.0) + rrf_contrib

    # 2. 统计稀疏 BM25 排名
    for rank, c in enumerate(sparse_results, 1):
        cid = c.get("chunk_id")
        if not cid:
            continue
        if cid not in fused_chunks:
            fused_chunks[cid] = c
        sparse_ranks[cid] = rank
        rrf_contrib = w_sparse * (1.0 / (rrf_k + rank))
        fused_scores[cid] = fused_scores.get(cid, 0.0) + rrf_contrib

    if not fused_scores:
        return []

    # 3. 按融合得分降序排序
    sorted_candidates = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    max_rrf = sorted_candidates[0][1] if sorted_candidates else 1.0

    final_results = []
    for rank, (cid, rrf_score) in enumerate(sorted_candidates, 1):
        c = dict(fused_chunks[cid])
        # 归一化综合分为 0.0 ~ 1.0 的百分制展现
        norm_score = round(min(1.0, rrf_score / (max_rrf + 1e-6)), 4)
        c["score"] = norm_score
        c["rrf_score"] = round(rrf_score, 5)
        c["dense_rank"] = dense_ranks.get(cid, None)
        c["sparse_rank"] = sparse_ranks.get(cid, None)
        c["retrieval_method"] = "hybrid_rrf"
        final_results.append(c)

    return final_results
