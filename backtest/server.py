"""
回测引擎 HTTP 接口服务（v4.1 规范）
================================================================================
面向 Agent / HR 系统的独立 HTTP 服务，与网页版 (web_app.py) 解耦。

特性：
- 统一入口 `/api/v1/run`：支持「嵌套 v4 JSON」和「扁平 JSON」两种请求格式
- 完整透传 v4.1 结论层（overview_desc / role_ranking / highlights / recommendation / target_role）
- 标准错误响应：HTTP 状态码 + error_code + error_message
- `/api/v1/health` 健康检查、`/api/v1/docs` 接口说明、`/api/v1/meta` 元信息
- 结果下载：`/api/v1/results/<request_id>/response.json` 与打包 zip

启动：
    cd backtest
    python3 server.py                          # 监听 0.0.0.0:5051
    python3 server.py --port 8080 --host 0.0.0.0

作者: 徐远 | 日期: 2026-08-22
================================================================================
"""
from __future__ import annotations
import argparse
import io
import json
import os
import sys
import zipfile
from datetime import datetime
from typing import Any, Dict

from flask import Flask, jsonify, request, send_file

# 路径自适应（Sprint 0: 本地/服务器），支持 FINBACK_BASE_DIR 覆盖
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKTEST_DIR not in sys.path:
    sys.path.insert(0, _BACKTEST_DIR)

from query_engine import run_query, QueryParser

if os.getenv("FINBACK_BASE_DIR"):
    RESULTS_DIR = os.path.join(os.environ["FINBACK_BASE_DIR"], "backtest", "results")
else:
    RESULTS_DIR = os.path.join(_BACKTEST_DIR, "results")

API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

app = Flask(__name__)

# 元信息（供 Agent 动态获取合法取值）
_META = {
    "api_version": API_VERSION,
    "name": "金融产品业绩贡献计量与绩效考评系统 - 回测归因引擎",
    "roles": QueryParser.VALID_ROLES,
    "benchmarks": list(QueryParser.VALID_BENCHMARKS.keys()),
    "rebalance_freq": QueryParser.VALID_FREQS,
    "granularity": QueryParser.VALID_FREQS,
    "error_codes": ["INDUSTRY_NOT_FOUND", "ROLE_NOT_FOUND", "INVALID_PARAM", "NO_DATA", "EXECUTION_ERROR"],
    "default_benchmark": "hs300",
    "default_rebalance_freq": "monthly",
    "default_granularity": "monthly",
}


def _make_error(status_code: int, error_code: str, message: str, request_id: str | None = None) -> tuple:
    """统一错误响应格式"""
    body: Dict[str, Any] = {
        "status": "error",
        "error_code": error_code,
        "error_message": message,
    }
    if request_id:
        body["request_id"] = request_id
    return jsonify(body), status_code


@app.route("/")
def root():
    """服务根路径：返回接口入口说明"""
    return jsonify({
        "service": _META["name"],
        "api_version": API_VERSION,
        "endpoints": {
            "run": f"POST {API_PREFIX}/run",
            "health": f"GET {API_PREFIX}/health",
            "meta": f"GET {API_PREFIX}/meta",
            "docs": f"GET {API_PREFIX}/docs",
            "download_response": f"GET {API_PREFIX}/results/<request_id>/response.json",
            "download_all": f"GET {API_PREFIX}/results/<request_id>/all.zip",
        },
        "docs_file": "docs/回测引擎HTTP接口文档_v5.md",
    })


@app.route(f"{API_PREFIX}/health", methods=["GET"])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "service": _META["name"],
        "api_version": API_VERSION,
        "time": datetime.now().isoformat(),
    })


@app.route(f"{API_PREFIX}/meta", methods=["GET"])
def meta():
    """元信息：合法取值枚举，供 Agent 动态校验参数"""
    return jsonify(_META)


@app.route(f"{API_PREFIX}/docs", methods=["GET"])
def docs():
    """接口文档概要（完整文档见 docs/回测引擎HTTP接口文档_v5.md）"""
    return jsonify({
        "status": "ok",
        "summary": "完整接口文档见 docs/回测引擎HTTP接口文档_v5.md",
        "request_fields": {
            "request_id": "string (可选，缺省自动生成)",
            "timestamp": "string (可选)",
            "query": {
                "time_range": {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
                "target_role": "string|null",
                "industry": "string|null",
                "role_weights": "object|null",
                "benchmark": "hs300|csi500|shanghai",
                "rebalance_freq": "monthly|quarterly|yearly",
                "granularity": "monthly|quarterly|yearly",
            },
        },
        "response_structure": {
            "status": "success|error",
            "request_id": "string",
            "query_summary": "string",
            "results": {
                "overview": "整体绩效 + *_desc 人话描述",
                "role_breakdown": "各角色贡献明细",
                "role_ranking": "贡献排名",
                "highlights": "主要发现",
                "recommendation": "分配+复盘建议",
                "filter_detail": "实际筛选条件",
                "time_series": "时间序列",
                "target_role": "聚焦角色",
            },
        },
    })


@app.route(f"{API_PREFIX}/run", methods=["POST"])
def run():
    """
    执行回测。

    支持两种请求格式：
      1. 嵌套格式（v4 规范，Agent 解析自然语言后生成）：
         {"request_id":"q_001","timestamp":"...","query":{...}}
      2. 扁平格式（直接把 query 字段平铺在顶层）：
         {"start_date":"...","end_date":"...","industry":"...", ...}
    """
    # 读取原始请求
    raw = request.get_json(silent=True)
    if raw is None:
        return _make_error(400, "INVALID_PARAM", "请求体必须为 JSON，且 Content-Type: application/json")

    # 从嵌套格式或扁平格式提取 query
    if isinstance(raw, dict) and "query" in raw and isinstance(raw["query"], dict):
        # 嵌套格式：透传 run_query（含 request_id / timestamp）
        query_json = dict(raw)
        query_json.setdefault("request_id", f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        query_json.setdefault("timestamp", datetime.now().isoformat())
    elif isinstance(raw, dict):
        # 扁平格式：组装成嵌套格式
        query_json = {
            "request_id": raw.get("request_id") or f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": raw.get("timestamp") or datetime.now().isoformat(),
            "query": {
                "time_range": {"start_date": raw.get("start_date"), "end_date": raw.get("end_date")},
                "target_role": raw.get("target_role") or None,
                "industry": raw.get("industry") or None,
                "role_weights": raw.get("role_weights") or None,
                "benchmark": raw.get("benchmark") or "hs300",
                "rebalance_freq": raw.get("rebalance_freq") or "monthly",
                "granularity": raw.get("granularity") or "monthly",
            },
        }
    else:
        return _make_error(400, "INVALID_PARAM", "请求体必须为 JSON 对象")

    # 执行回测（核心引擎，完整透传 v4.1 结果）
    result = run_query(query_json)
    request_id = result.get("request_id", query_json.get("request_id", "unknown"))

    # 错误映射到 HTTP 状态码
    if result.get("status") == "error":
        error_code = result.get("error_code", "EXECUTION_ERROR")
        status_map = {
            "INDUSTRY_NOT_FOUND": 400,
            "ROLE_NOT_FOUND": 400,
            "INVALID_PARAM": 400,
            "NO_DATA": 404,
            "EXECUTION_ERROR": 500,
        }
        status_code = status_map.get(error_code, 400)
        return _make_error(status_code, error_code, result.get("error_message", "未知错误"), request_id)

    return jsonify(result), 200


@app.route(f"{API_PREFIX}/results/<request_id>/response.json", methods=["GET"])
def download_response(request_id: str):
    """下载某次回测的完整结果 JSON"""
    filepath = os.path.join(RESULTS_DIR, request_id, "response.json")
    if not os.path.exists(filepath):
        return _make_error(404, "NO_DATA", f"结果不存在: request_id={request_id}")
    return send_file(filepath, as_attachment=True, download_name=f"backtest_{request_id}.json")


@app.route(f"{API_PREFIX}/results/<request_id>/all.zip", methods=["GET"])
def download_all(request_id: str):
    """下载某次回测的全部中间数据（打包 zip）"""
    result_dir = os.path.join(RESULTS_DIR, request_id)
    if not os.path.isdir(result_dir):
        return _make_error(404, "NO_DATA", f"结果目录不存在: request_id={request_id}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in os.listdir(result_dir):
            filepath = os.path.join(result_dir, filename)
            if os.path.isfile(filepath):
                zf.write(filepath, filename)
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"backtest_{request_id}_all.zip",
    )


def main():
    parser = argparse.ArgumentParser(description="回测引擎 HTTP 接口服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=5051, help="监听端口（默认 5051）")
    parser.add_argument("--debug", action="store_true", help="开启 Flask 调试模式")
    args = parser.parse_args()

    print("=" * 60)
    print(f"🚀 回测引擎 HTTP 接口服务")
    print(f"   接口版本: {API_VERSION}")
    print(f"   监听地址: {args.host}:{args.port}")
    print(f"   主入口:   POST http://{args.host}:{args.port}{API_PREFIX}/run")
    print(f"   健康检查: GET  http://{args.host}:{args.port}{API_PREFIX}/health")
    print("=" * 60)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
