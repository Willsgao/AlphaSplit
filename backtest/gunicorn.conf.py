"""
gunicorn 生产配置
=================
用法：
    gunicorn -c gunicorn.conf.py wsgi:app

设计要点：
- 引擎内部为串行计算，且每次回测需加载全量数据（数百 MB），
  故固定为 1 个 worker + 开启 preload，避免多 worker 重复加载数据、浪费内存。
- 若确实需要并发（多个 Agent 同时请求），可调大 workers，
  但需注意内存占用会随 worker 数线性增长。
"""
import multiprocessing
import os

# 绑定地址与端口（可用环境变量覆盖）
bind = os.getenv("BACKTEST_BIND", "0.0.0.0:5051")

# worker 数：默认 1（引擎串行 + 数据量大，见上方设计要点）
workers = int(os.getenv("BACKTEST_WORKERS", "1"))

# worker 类型：默认同步（串行计算无需异步）
worker_class = "sync"

# preload：先加载一次应用（含引擎/数据加载），再 fork worker
# 配合 workers=1 可避免重复加载数据
preload_app = True

# 超时：单次回测约 30~60s，Shapley 多子集可能更久，设 600s
timeout = int(os.getenv("BACKTEST_TIMEOUT", "600"))
graceful_timeout = 30
keepalive = 5

# 日志
accesslog = "-"                 # 访问日志输出到 stdout
errorlog = "-"                  # 错误日志输出到 stderr
loglevel = os.getenv("BACKTEST_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# 单进程请求并发上限
worker_connections = 1000

# 进程命名
proc_name = "backtest-server"
