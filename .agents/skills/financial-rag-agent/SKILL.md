---
name: financial-rag-agent
description: >-
  基于本地研报分析与财报解读向量知识库进行投研问答与财务指标深度分析的专业智能体技能。当需要查询个股券商研报评级、目标价、核心投资逻辑或解读财报营收、净利润、毛利率等财务数据时使用。
---

# 金融研报分析与财报解读智能体 (Financial RAG Agent)

该技能通过本地向量知识库（ChromaDB）与大模型为用户提供资深证券分析师与注册会计师（CPA）级别的深度研报分析与财报洞察。

## 何时使用本技能
- 用户询问个股的机构投资评级、研报核心催化剂、业务护城河或目标估值；
- 用户需要解读个股季报/年报的营业收入、归母净利润、毛利率、现金流等财务指标；
- 用户希望查询本地已入库研报或检索财报文献切片。

## 执行与调用方式
可在 Python 脚本、智能体工具流或命令行中直接调用 RAG 模块：

### 1. 命令行或 Python 代码直接调用
```python
from rag import financial_rag_skill

# 执行研报财报深度智能问答
result = financial_rag_skill.execute(
    query="贵州茅台一季度净利润增速与毛利率",
    category="财报解读",  # 可选：'研报分析' 或 '财报解读'
    stock_code="600519",
    top_k=4,
    generate_answer=True,
)
print(result["answer"])
```

### 2. 通过 RESTful API 检索问答
```bash
curl -X POST http://127.0.0.1:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "宁德时代核心投资逻辑", "category": "研报分析", "top_k": 4}'
```

### 3. 配置与指令定义
该 Agent 的提示词、角色人设与输出规范集中由 `rag/SKILL.md` 统一管理与热更新。
