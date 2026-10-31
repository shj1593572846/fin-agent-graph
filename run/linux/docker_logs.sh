#!/usr/bin/env bash
# 查看实时智能体流式日志
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

docker compose logs -f app
