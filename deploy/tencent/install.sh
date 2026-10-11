#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash deploy/tencent/install.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env"
NGINX_SOURCE="${PROJECT_DIR}/deploy/tencent/alphasplit.nginx.conf"
NGINX_TARGET="/etc/nginx/conf.d/alphasplit.conf"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker。请先在腾讯云安装 Docker Engine 与 Compose 插件。" >&2
  echo "安装完成后确认以下命令可用: docker compose version" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "未检测到 Docker Compose 插件。" >&2
  exit 1
fi

if ! command -v nginx >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y nginx curl
  elif command -v yum >/dev/null 2>&1; then
    yum install -y nginx curl
  else
    echo "无法自动安装 Nginx，请先安装后重新运行。" >&2
    exit 1
  fi
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${PROJECT_DIR}/deploy/tencent/alphasplit.env.example" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "已创建 ${ENV_FILE}，当前采用无 API Key 的公开演示模式。"
fi

mkdir -p "${PROJECT_DIR}/backtest/results" "${PROJECT_DIR}/backtest/reports"
chown -R 10001:10001 "${PROJECT_DIR}/backtest/results" "${PROJECT_DIR}/backtest/reports"

install -m 0644 "${NGINX_SOURCE}" "${NGINX_TARGET}"
nginx -t

cd "${PROJECT_DIR}"
docker compose --env-file "${ENV_FILE}" up -d --build

if command -v setsebool >/dev/null 2>&1; then
  setsebool -P httpd_can_network_connect 1 || true
fi

systemctl enable --now nginx
systemctl reload nginx

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http
  firewall-cmd --reload
fi

echo "等待 AlphaSplit 健康检查..."
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8766/api/health >/dev/null; then
    echo "部署完成。请访问: http://服务器公网IP/"
    exit 0
  fi
  sleep 2
done

echo "服务未在预期时间内就绪，请检查: docker compose logs --tail=200" >&2
exit 1
