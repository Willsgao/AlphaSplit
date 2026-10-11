#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash deploy/tencent/update.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_DIR}"

git pull --ff-only
docker compose --env-file .env up -d --build

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8766/api/health >/dev/null; then
    echo "AlphaSplit 已更新并通过健康检查。"
    exit 0
  fi
  sleep 2
done

docker compose logs --tail=200
exit 1
