import os
import sys

# 确保 agent 目录和项目根目录都在 sys.path 中
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(1, _PROJECT_ROOT)

from langgraph.graph import END, START, StateGraph

from agents import (
    download_stock_day_node,
    filter_stock_node,
    generate_grid_dashboard_node,
    analyze_grid_agent_node,
    analyze_news_agent_node,
    decision_maker_agent_node,
    # 向后兼容别名导入
    collector_stock_day_agent_node,
    filter_stock_agent_node,
    analyst_agent_node,
)
from state import ResearchState


def build_multi_agent_graph():
    """
    根据六节点架构图构建并编译 LangGraph 智能体协同工作流：
    
           node1 (下载日线数据)
                │
                ▼
           node2 (过滤个股)
                │
                ▼
           node3 (过滤后的个股生成实时的分时图16宫格 [参考 stock_chart.py])
                │
         ┌──────┴──────┐
         ▼             ▼
   node4 (分析16宫格)  node5 (分析消息面)
         │  ──通信──   │
         └──────┬──────┘
                ▼
           node6 (决策者 [agent])
                │
                ▼
               END
    """
    workflow = StateGraph(ResearchState)

    # 1. 注册工作流中的 6 个核心节点
    workflow.add_node("node1", download_stock_day_node)
    workflow.add_node("node2", filter_stock_node)
    workflow.add_node("node3", generate_grid_dashboard_node)
    workflow.add_node("node4", analyze_grid_agent_node)
    workflow.add_node("node5", analyze_news_agent_node)
    workflow.add_node("node6", decision_maker_agent_node)

    # 2. 编排工作流拓扑流转边
    # 阶段一：日线数据下载与过滤
    workflow.add_edge(START, "node1")
    workflow.add_edge("node1", "node2")

    # 阶段二：生成实时分时16宫格
    workflow.add_edge("node2", "node3")

    # 阶段三：16宫格分发给技术分时量化 Agent (node4) 与消息面分析 Agent (node5)
    workflow.add_edge("node3", "node4")
    workflow.add_edge("node3", "node5")

    # 阶段四：技术面与消息面协同交互后，汇聚输入至决策者 Agent (node6)
    workflow.add_edge("node4", "node6")
    workflow.add_edge("node5", "node6")

    # 阶段五：决策者输出终审投资研报后结束
    workflow.add_edge("node6", END)

    # 3. 编译并返回可执行工作流应用
    return workflow.compile()
