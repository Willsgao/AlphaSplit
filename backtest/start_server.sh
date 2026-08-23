#!/usr/bin/env bash
# 回测引擎 HTTP 接口服务启动脚本
# 用法:
#   ./start_server.sh                    # 默认 0.0.0.0:5051
#   ./start_server.sh --port 8080        # 自定义端口
#   FINBACK_BASE_DIR=/path ./start_server.sh   # 指定项目根目录
set -e
cd "$(dirname "$0")"

PORT="${1:-5051}"
if [[ -n "$2" ]]; then
  PORT="$2"
fi

echo "启动回测引擎 HTTP 接口服务 (端口: $PORT) ..."
exec python3 server.py --host 0.0.0.0 --port "$PORT"
