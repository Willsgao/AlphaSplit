#!/usr/bin/env bash
# ============================================================
# 回测引擎 HTTP 接口服务 - 一键部署脚本
# 适用：本地 / 云服务器（代码与数据同机）
#
# 用法:
#   ./deploy.sh install        安装依赖（创建 venv）
#   ./deploy.sh start          启动服务（优先 supervisor，其次 gunicorn 后台）
#   ./deploy.sh stop           停止服务
#   ./deploy.sh restart        重启服务
#   ./deploy.sh status         查看状态
#   ./deploy.sh health         健康检查
#   ./deploy.sh logs           查看日志
#
# 环境变量（可覆盖）:
#   BACKTEST_PORT    监听端口，默认 5051
#   BACKTEST_BIND    完整绑定，默认 0.0.0.0:5051（优先于 BACKTEST_PORT）
#   BACKTEST_WORKERS gunicorn worker 数，默认 1（引擎串行，勿随意调大）
#   FINBACK_BASE_DIR 项目根目录（默认自动探测到脚本上两级）
# ============================================================
set -euo pipefail

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKTEST_DIR="$SCRIPT_DIR"
BASE_DIR="${FINBACK_BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="$BACKTEST_DIR/venv"
PYTHON="$VENV_DIR/bin/python"

# 端口
BIND="${BACKTEST_BIND:-0.0.0.0:${BACKTEST_PORT:-5051}}"
PORT="${BIND##*:}"

PIDFILE="$BACKTEST_DIR/backtest.pid"
OUTLOG="$BACKTEST_DIR/logs/backtest.out.log"
ERRLOG="$BACKTEST_DIR/logs/backtest.err.log"

mkdir -p "$BACKTEST_DIR/logs"

SUPERVISOR_CONF="$BACKTEST_DIR/deploy/supervisor_backtest.conf"

print_header() {
  echo "============================================================"
  echo " 回测引擎 HTTP 接口服务"
  echo " 项目根目录 : $BASE_DIR"
  echo " 接口绑定   : $BIND"
  echo "============================================================"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---------------- install ----------------
do_install() {
  print_header
  echo "[1/3] 创建虚拟环境 ($VENV_DIR) ..."
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
  fi
  echo "[2/3] 安装依赖 ..."
  "$PYTHON" -m pip install --upgrade pip -q
  "$PYTHON" -m pip install -r "$BACKTEST_DIR/requirements.txt" -q
  echo "[3/3] 安装 gunicorn（生产服务器） ..."
  "$PYTHON" -m pip install "gunicorn>=21.2.0" -q
  echo "✅ 依赖安装完成。数据目录应位于: $BASE_DIR/data/processed"
  echo "   启动: $0 start   健康检查: $0 health"
}

# ---------------- start (supervisor) ----------------
start_via_supervisor() {
  if ! have_cmd supervisorctl; then
    echo "  (未安装 supervisor，改用 gunicorn 后台运行)"
    return 1
  fi
  echo "[部署] 使用 supervisor 管理进程 ..."
  # 生成带实际路径的临时配置（替换占位路径）
  SED_TMP="$BACKTEST_DIR/deploy/.supervisor_generated.conf"
  sed \
    -e "s|/opt/FinTech|$BASE_DIR|g" \
    -e "s|/opt/FinTech/backtest/venv/bin/gunicorn|$VENV_DIR/bin/gunicorn|g" \
    "$SUPERVISOR_CONF" > "$SED_TMP"
  echo "  生成配置: $SED_TMP"
  echo "  请手动执行（需要 sudo，supervisor 需已安装）:"
  echo "    sudo cp $SED_TMP /etc/supervisor/conf.d/backtest.conf"
  echo "    sudo supervisorctl reread && sudo supervisorctl update"
  echo "    sudo supervisorctl start backtest"
  echo "  或直接使用 gunicorn 后台运行: $0 start"
  return 0
}

# ---------------- start (gunicorn) ----------------
start_via_gunicorn() {
  echo "[部署] 使用 gunicorn 后台运行 ..."
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "  服务已在运行 (PID=$(cat "$PIDFILE"))"
    return 0
  fi
  cd "$BACKTEST_DIR"
  FINBACK_BASE_DIR="$BASE_DIR" nohup "$VENV_DIR/bin/gunicorn" \
    -c gunicorn.conf.py wsgi:app \
    --bind "$BIND" \
    --daemon \
    --pid "$PIDFILE" \
    --access-logfile "$OUTLOG" \
    --error-logfile "$ERRLOG" \
    >/dev/null 2>&1
  # 等待启动
  for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then
      echo "✅ 服务已启动 (PID=$(cat "$PIDFILE"), 端口 $PORT)"
      return 0
    fi
    sleep 1
  done
  echo "❌ 启动超时，请查看日志: tail -f $ERRLOG"
  return 1
}

do_start() {
  print_header
  # 校验数据目录
  if [ ! -d "$BASE_DIR/data/processed" ]; then
    echo "⚠️  未找到数据目录: $BASE_DIR/data/processed"
    echo "   请设置 FINBACK_BASE_DIR 指向项目根目录（含 data/processed 与 backtest）"
  fi
  if start_via_supervisor; then
    :
  else
    start_via_gunicorn
  fi
}

do_stop() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")" && echo "✅ 服务已停止" || echo "❌ 停止失败"
    rm -f "$PIDFILE"
  else
    echo "服务未在运行"
  fi
}

do_restart() { do_stop; sleep 1; do_start; }

do_status() {
  print_header
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "状态: ✅ 运行中 (PID=$(cat "$PIDFILE"), 端口 $PORT)"
  else
    echo "状态: ⏸  未运行"
  fi
  echo "日志: $OUTLOG / $ERRLOG"
  if curl -s "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then
    echo "健康: ✅ 通过 (curl $BIND/api/v1/health)"
  else
    echo "健康: ❌ 不可达"
  fi
}

do_health() {
  curl -s "http://127.0.0.1:$PORT/api/v1/health"
  echo ""
}

do_logs() { tail -f "$ERRLOG"; }

# ---------------- main ----------------
case "${1:-}" in
  install)  do_install ;;
  start)    do_start ;;
  stop)     do_stop ;;
  restart)  do_restart ;;
  status)   do_status ;;
  health)   do_health ;;
  logs)     do_logs ;;
  *)
    echo "用法: $0 {install|start|stop|restart|status|health|logs}"
    echo ""
    echo "  示例:"
    echo "    $0 install     # 首次部署：创建 venv + 安装依赖"
    echo "    $0 start       # 启动服务"
    echo "    $0 status      # 查看状态"
    echo "    $0 health      # 健康检查"
    ;;
esac
