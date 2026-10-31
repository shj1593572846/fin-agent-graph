#!/usr/bin/env bash
# 热重启应用容器
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "正在重启应用容器 fin-agent-app..."
docker compose restart app
echo "✅ 重启完成！"
