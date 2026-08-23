"""
生产 WSGI 入口（供 gunicorn / uwsgi 使用）
=========================================
启动：
    gunicorn -c gunicorn.conf.py wsgi:app

作者: 徐远 | 日期: 2026-08-22
"""
import os
import sys

# 保证能从任意工作目录导入 backtest 包
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKTEST_DIR not in sys.path:
    sys.path.insert(0, _BACKTEST_DIR)

from server import app

# 便于 uwsgi 兼容
application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5051)
