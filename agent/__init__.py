"""
LangGraph 多 Agent 股票量化与协同决策系统
"""

import os
import sys

# 保证当前包目录及项目根目录在模块导入路径中
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(1, _PROJECT_ROOT)

from .state import ResearchState
from .graph import build_multi_agent_graph
from .main import run_research_pipeline
from .user_memory import load_user_memory, save_user_memory, get_user_role

__all__ = [
    "ResearchState",
    "build_multi_agent_graph",
    "run_research_pipeline",
    "load_user_memory",
    "save_user_memory",
    "get_user_role",
]
