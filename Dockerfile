FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements-lock.txt /app/requirements-lock.txt
RUN python -m pip install --disable-pip-version-check -r /app/requirements-lock.txt

COPY agent_layer /app/agent_layer
COPY backtest /app/backtest
COPY data /app/data
COPY engine /app/engine

RUN mkdir -p /app/backtest/results /app/backtest/reports \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin alphasplit \
    && chown -R alphasplit:alphasplit /app/backtest/results /app/backtest/reports

USER alphasplit

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "engine.api.main", "--mode", "mock", "--host", "0.0.0.0", "--port", "8000"]
