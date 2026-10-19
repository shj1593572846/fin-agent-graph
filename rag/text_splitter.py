"""
文本切片与分块处理：针对研报和财报特点进行语义与段落敏感的分块
"""

from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rag.config import CHUNK_SIZE, CHUNK_OVERLAP


def get_financial_text_splitter() -> RecursiveCharacterTextSplitter:
    """初始化适配中文金融研报与财报段落特性的文本切分器"""
    separators = [
        "\n\n\n",
        "\n\n",
        "\n### ",
        "\n## ",
        "\n# ",
        "\n【",
        "\n一、",
        "\n二、",
        "\n三、",
        "\n四、",
        "\n五、",
        "\n六、",
        "\n七、",
        "\n（一）",
        "\n（二）",
        "\n（三）",
        "\n（四）",
        "\n",
        "。\n",
        "；\n",
        "。",
        "；",
        " ",
        "",
    ]
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=separators,
        keep_separator=True,
    )


def split_document_pages(
    pages_data: List[Dict[str, Any]],
    doc_meta: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    将文档按页提取的文本列表切分成带丰富元数据的 chunks 集合
    """
    splitter = get_financial_text_splitter()
    chunks = []
    chunk_index = 0

    doc_id = doc_meta.get("id", "")
    title = doc_meta.get("title", "")
    category = doc_meta.get("category", "")
    stock_code = doc_meta.get("stock_code", "")
    stock_name = doc_meta.get("stock_name", "")

    for p in pages_data:
        page_num = p.get("page", 1)
        raw_text = p.get("text", "")
        if not raw_text.strip():
            continue

        raw_chunks = splitter.split_text(raw_text)
        for c in raw_chunks:
            c_clean = c.strip()
            # 过滤过短无意义碎片
            if len(c_clean) < 15:
                continue

            chunk_id = f"{doc_id}_c{chunk_index}"
            chunk_item = {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "chunk_index": chunk_index,
                "text": c_clean,
                "page": page_num,
                "title": title,
                "category": category,
                "stock_code": stock_code,
                "stock_name": stock_name,
            }
            chunks.append(chunk_item)
            chunk_index += 1

    return chunks
