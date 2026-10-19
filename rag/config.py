import os

# RAG 根目录及数据存储路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOCUMENTS_DIR = os.path.join(DATA_DIR, "documents")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")

# 确保必要的数据持久化目录存在
for _dir in [DATA_DIR, DOCUMENTS_DIR, CHROMA_DIR, SAMPLES_DIR]:
    os.makedirs(_dir, exist_ok=True)

# 向量数据库与切片配置
COLLECTION_NAME = "financial_reports_rag"
CHUNK_SIZE = 750
CHUNK_OVERLAP = 120

# 分类定义
CATEGORY_RESEARCH = "研报分析"
CATEGORY_FINANCIAL = "财报解读"
VALID_CATEGORIES = [CATEGORY_RESEARCH, CATEGORY_FINANCIAL]
