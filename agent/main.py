import argparse
import os
import sys
import time

# 确保 agent 目录和项目根目录都在 sys.path 中
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(1, _PROJECT_ROOT)

# 适配 Windows 控制台编码，防止 Emoji 及中文字符输出异常
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from langchain_core.messages import HumanMessage
from graph import build_multi_agent_graph


def run_research_pipeline(topic: str, keep_alive_minutes: int = 10) -> str:
    """
    运行基于六节点拓扑的 LangGraph 多 Agent 协同研判工作流：
    node1 (下载日线数据) -> node2 (过滤个股) -> node3 (分时16宫格)
         -> node4 (分析16宫格 [agent]) \
                                        == 通信 == -> node6 (决策者 [agent]) -> END
         -> node5 (分析消息面 [agent]) /
    """
    app = build_multi_agent_graph()

    initial_state = {
        "topic": topic,
        "messages": [HumanMessage(content=f"请启动六节点协同流程，对「{topic or '全市场重点龙头'}」进行日K线初筛、实时分时16宫格构建、量化形态回踩承接分析、消息面排查与终审决策")],
        "collected_data": "",
        "filtered_data": "",
        "filtered_stocks": [],
        "grid_stocks": [],
        "dashboard_url": "",
        "grid_quant_analysis": "",
        "news_analysis": "",
        "final_decision": "",
        "analysis_result": "",
    }

    print("=" * 80)
    print(f"🚀 启动 LangGraph 六节点多 Agent 协同体系 | 目标主题：{topic or '全市场重点标的'}")
    print("=" * 80)

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 80)
    print("📌 【阶段汇总 1 & 2：强势股筛选过滤成果】")
    print("=" * 80)
    print(final_state.get("filtered_data", "无过滤记录"))

    print("\n" + "=" * 80)
    print(f"🖥️ 【阶段汇总 3：分时图16宫格终端就绪】")
    dash_urls = final_state.get('dashboard_urls', [final_state.get('dashboard_url', 'http://127.0.0.1:8888')])
    print(f"👉 实时监控大屏网页窗口 ({len(dash_urls)} 个): {dash_urls}")
    print(f"📊 监控标的 ({len(final_state.get('grid_stocks', []))} 只，每页16只): {final_state.get('grid_stocks', [])}")
    print("=" * 80)

    print("\n" + "=" * 80)
    print("📈 【阶段汇总 4：Node4 技术分时均线承接研报全文】")
    print("=" * 80)
    tech_str = final_state.get("grid_quant_analysis", "")
    print(tech_str)
    print("=" * 80 + "\n")
    sys.stdout.flush()

    print("\n" + "=" * 80)
    print("📰 【阶段汇总 5：Node5 消息面与行业催化研报全文】")
    print("=" * 80)
    news_str = final_state.get("news_analysis", "")
    print(news_str)
    print("=" * 80 + "\n")
    sys.stdout.flush()

    print("\n" + "=" * 80)
    print("👑 【阶段汇总 6：Node6 决策者 Agent 终审投资操盘研报（最终决策）】")
    print("=" * 80)
    decision = final_state.get("final_decision", final_state.get("analysis_result", ""))
    if not decision or not str(decision).strip():
        decision = "⚠️ [系统提示] 未获取到有效终审研报内容，请检查大模型网络连通性或查看 stock_data/qualified_stocks_morning.csv。"
    print(decision)
    print("=" * 80 + "\n")
    sys.stdout.flush()

    # 💾 【策略执行完毕】提取排名第一股票并持久化至 MySQL stock_recommendation 表（排重校验：股票代码 + 买入日期）
    try:
        from db import save_top_stock_from_state
        save_top_stock_from_state(final_state)
    except Exception as e:
        print(f"⚠️ [数据库提示] 写入 stock_recommendation 表异常: {str(e)}\n")
        sys.stdout.flush()

    # 延迟保持 16 宫格网页看板服务运行 (默认 10 分钟，支持 Ctrl+C 随时安全退出)
    if keep_alive_minutes > 0:
        dash_urls = final_state.get('dashboard_urls', [final_state.get('dashboard_url', 'http://127.0.0.1:8888')])
        total_seconds = keep_alive_minutes * 60
        print("=" * 80)
        print(f"🌐 【16宫格网页看板保持运行中】实时分时大屏窗口: {dash_urls}")
        print(f"⏱️ 进程将保持服务 {keep_alive_minutes} 分钟供实时看盘与监控 (按 Ctrl+C 可随时退出)...")
        print("=" * 80)
        try:
            for remaining in range(total_seconds, 0, -1):
                mins, secs = divmod(remaining, 60)
                sys.stdout.write(f"\r⏳ 16宫格看盘服务保持运行中... 倒计时: {mins:02d}分{secs:02d}秒 (按 Ctrl+C 可提前退出)")
                sys.stdout.flush()
                time.sleep(1)
            print("\n\n⏰ 10分钟保持时间结束，16宫格服务已正常关闭。")
        except KeyboardInterrupt:
            print("\n\n🛑 检测到中断信号，16宫格后台服务已安全退出。")

    

    
    return decision


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangGraph 六节点多 Agent 股票量化与协同决策系统")
    parser.add_argument(
        "--topic",
        type=str,
        default="",
        help="需要收集日线数据并分析的股票板块或主题（留空则收集全市场非科创板、非ST股票）",
    )
    parser.add_argument(
        "--keep-alive",
        type=int,
        default=10,
        help="研报生成后保持16宫格看板运行的分钟数 (默认10分钟，0表示直接退出)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        default=True,
        help="开启极速分析模式（优先复用缓存、直接量化直驱大模型、提升5-10倍执行速度）",
    )
    parser.add_argument(
        "--full",
        dest="fast",
        action="store_false",
        help="开启深度全量模式（全网全量重抓全部标的数据）",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="静默模式，不在桌面强行弹出外部浏览器网页窗口",
    )
    args = parser.parse_args()

    if args.fast:
        os.environ["FAST_MODE"] = "1"
    else:
        os.environ["FAST_MODE"] = "0"

    if args.no_browser:
        os.environ["NO_BROWSER"] = "1"

    run_research_pipeline(args.topic, keep_alive_minutes=args.keep_alive)
