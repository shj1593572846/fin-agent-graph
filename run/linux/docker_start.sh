#!/usr/bin/env bash
set -e

# 定位项目根目录
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "================================================================"
echo "   [Linux/Docker] 正在一键构建并启动生产容器集群..."
echo "================================================================"

docker compose up -d --build
echo ""
echo "✅ 容器启动完成！当前运行状态："
docker compose ps
