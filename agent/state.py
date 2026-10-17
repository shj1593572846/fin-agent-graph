from typing import Annotated, List, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ResearchState(TypedDict, total=False):
    """
    多 Agent 协同工作流全生命周期共享状态：
    node1 (下载日线数据) -> node2 (过滤个股) -> node3 (分时16宫格)
         -> node4 (16宫格分时分析) \
                                   == 通信 == -> node6 (决策者) -> END
         -> node5 (消息面分析)     /
    """

    # 用户指定的研究/分析主题或板块
    topic: str
    # 消息历史（使用 add_messages 自动追加）
    messages: Annotated[List[BaseMessage], add_messages]

    # === node1 产出 ===
    # 历史日K线数据或全市场股票下载汇总
    collected_data: str

    # === node2 产出 ===
    # 筛选过滤后的高动能/涨停/多头股票数据及列表
    filtered_data: str
    filtered_stocks: List[dict]  # 结构化股票列表 [{"股票代码": "...", "股票简称": "..."}, ...]

    # === node3 产出 (参考 stock_chart.py) ===
    grid_stocks: List[str]            # 选中的股票代码列表 (支持 >16 只，16只/页多窗口)
    dashboard_url: str                # 默认首页终端地址 (如 http://127.0.0.1:8888)
    dashboard_urls: List[str]         # 所有16宫格网页窗口地址列表 [http://127.0.0.1:8888/?page=1, ...]
    grid_pages_meta: dict             # 多窗口元数据 {"total_stocks": N, "total_pages": M, "pages": [...]}
    grid_realtime_data: List[dict]    # 实时分时行情快照 (含各股票分时K线、VWAP、分时量)

    # === node4 产出 (参考 stock_quant.py) ===
    grid_quant_analysis: str          # 16宫格早盘量化回踩与承接筛选技术研报
    qualified_stocks: List[dict]      # 技术面强力符合战法的股票清单

    # === node5 产出 ===
    news_analysis: str                # 消息面、催化剂与行业舆情分析研报
    news_sentiment: dict              # 消息面多空情绪打分

    # === node4 与 node5 协同通信 ===
    tech_news_comm: str               # 技术面与消息面 Agent 间的对齐与交叉验证纪要

    # === node6 产出 ===
    final_decision: str               # 决策者 Agent 综合研判与终审操盘报告
    analysis_result: str              # 兼容原有字段 (指向最终分析报告)
