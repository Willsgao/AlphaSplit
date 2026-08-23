# ============================================================
# 回测引擎 HTTP 接口服务 - Docker 镜像
#
# 构建 & 运行:
#   docker build -t backtest-server .
#   docker run -d --name backtest -p 5051:5051 \
#     -v /path/to/FinTech/data:/app/data \
#     -v /path/to/FinTech/backtest/results:/app/backtest/results \
#     backtest-server
# 或用 docker-compose: docker compose up -d
# ============================================================
FROM python:3.11-slim

# 设置时区 & 依赖
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用缓存层）
COPY backtest/requirements.txt /app/backtest/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/backtest/requirements.txt \
    && pip install "gunicorn>=21.2.0"

# 拷贝代码
COPY backtest /app/backtest
COPY data /app/data

# 接口端口
EXPOSE 5051

WORKDIR /app/backtest

# 生产启动：gunicorn（workers=1 + preload，见 gunicorn.conf.py）
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
