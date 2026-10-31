#!/usr/bin/env bash
set -e

# 定位项目根目录
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "================================================================"
echo "   [Linux] LangGraph AI 量化选股系统 (FastAPI + React 前端)"
echo "================================================================"

# 检查虚拟环境
PYTHON_CMD="python3"
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/venv/bin/python"
fi

# 启动后端服务
echo "[1/2] 正在启动 FastAPI 后端服务 (server.py, 端口: 8000)..."
$PYTHON_CMD server.py &
BACKEND_PID=$!

sleep 2

# 启动前端服务
echo "[2/2] 正在启动 Vite 前端服务 (端口: 5173)..."
cd "$ROOT_DIR/frontend"
npm run dev

kill $BACKEND_PID 2>/dev/null || true
