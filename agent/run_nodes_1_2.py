"""
定时任务执行脚本：每天执行 node1 (下载日线数据与K线图) 和 node2 (视觉多模态过滤个股)
支持作为独立脚本被操作系统计划任务 (Windows Task Scheduler / Linux Cron) 或调度引擎调用。
"""

import os
import sys
import time
import datetime
import traceback

# 确保 agent 目录和项目根目录都在 sys.path 中
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(1, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from state import ResearchState
from agents import download_stock_day_node, filter_stock_node


def run_node1_node2_job(topic: str = "") -> dict:
    """运行 node1 和 node2 节点流程并记录日志"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 80)
    print(f"⏰ [定时任务启动] 当前时间: {now_str}")
    print(f"📌 执行内容: Node 1 (下载日线数据与K线图) + Node 2 (视觉多模态过滤个股)")
    print(f"🎯 分析主题: {'全市场' if not topic else topic}")
    print("=" * 80)

    state: ResearchState = {
        "topic": topic,
        "collected_data": "",
        "kline_charts": [],
        "kline_chart_path": "",
        "filtered_data": "",
        "filtered_stocks": [],
        "messages": [],
    }

    t_start = time.time()
    try:
        # 1. 运行 Node 1
        print("\n>>> 开始执行 [Node 1: download_stock_day_node] ...")
        t1 = time.time()
        node1_res = download_stock_day_node(state)
        state.update(node1_res)
        print(f">>> [Node 1] 完成，耗时: {time.time() - t1:.2f}秒，共准备 K线走势图: {len(state.get('kline_charts', []))} 张\n")

        # 2. 运行 Node 2
        print(">>> 开始执行 [Node 2: filter_stock_node] ...")
        t2 = time.time()
        node2_res = filter_stock_node(state)
        state.update(node2_res)
        qualified_stocks = state.get("filtered_stocks", [])
        print(f">>> [Node 2] 完成，耗时: {time.time() - t2:.2f}秒，共筛选出达标个股: {len(qualified_stocks)} 只\n")

        total_elapsed = time.time() - t_start
        print("=" * 80)
        print(f"🎉 [定时任务顺利执行完毕] 总耗时: {total_elapsed:.2f}秒")
        print(f"📊 达标标的: {[s.get('股票简称', s.get('name', '')) for s in qualified_stocks[:10]]}")
        print("=" * 80)
        return state

    except Exception as e:
        print(f"❌ [定时任务异常中断]: {e}")
        traceback.print_exc()
        raise e


if __name__ == "__main__":
    target_topic = sys.argv[1] if len(sys.argv) > 1 else ""
    run_node1_node2_job(topic=target_topic)
