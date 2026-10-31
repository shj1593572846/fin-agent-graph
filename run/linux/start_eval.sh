#!/usr/bin/env bash
set -e

# 定位项目根目录
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "================================================================"
echo "   [Linux] LangGraph 选股多 Agent 全生命周期评测控制台 (Eval)"
echo "================================================================"
echo ""
echo "请选择评测执行模式："
echo "  [1] 🧪 标杆场景回归评测 (高动能牛市复现，含LLM专家裁判)"
echo "  [2] 🛡️ 弱势防守场景评测 (单边下挫行情，考核空仓风控纪律)"
echo "  [3] 💾 本地真实产物评测 (基于 stock_data/ 现场数据出具诊断)"
echo "  [4] ⚡ 端到端全链路执行 (实时调度 Node 1-6 选股并插桩审计)"
echo "  [0] 退出"
echo ""

read -p "请输入编号 (0-4) [默认 1]: " user_choice
user_choice=${user_choice:-1}

if [ "$user_choice" = "0" ]; then
    exit 0
fi

# 检查虚拟环境
PYTHON_CMD="python3"
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/venv/bin/python"
fi

if [ "$user_choice" = "1" ]; then
    echo "正在运行标杆场景评测 (local_cache)..."
    $PYTHON_CMD eval/run_eval.py --mode benchmark --case local_cache
    exit 0
fi

if [ "$user_choice" = "2" ]; then
    echo "正在运行弱势防守评测 (bear_defensive)..."
    $PYTHON_CMD eval/run_eval.py --mode benchmark --case bear_defensive
    exit 0
fi

if [ "$user_choice" = "3" ]; then
    echo "正在基于本地最新产物执行诊断评测 (offline)..."
    $PYTHON_CMD eval/run_eval.py --mode offline
    exit 0
fi

if [ "$user_choice" = "4" ]; then
    read -p "请输入选股主题 (留空为全市场): " topic_name
    echo "正在执行端到端选股工作流并全链路追踪诊断..."
    $PYTHON_CMD eval/run_eval.py --mode live --topic "$topic_name"
    exit 0
fi
