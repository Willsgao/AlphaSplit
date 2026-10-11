"""
QuantSkills 回测归因引擎桥接层。

代码来源：agent_delivery_20260822（徐远交付包），已复制至仓库根目录 `backtest/` 与 `data/processed/`。
本模块负责路径引导、结果缓存与统一调用入口，供 FastAPI 与 Agent 层使用。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = ROOT / "backtest"
DATA_DIR = ROOT / "data" / "processed"
RESULTS_DIR = BACKTEST_DIR / "results"
CACHE_DIR = RESULTS_DIR / "_cache"
DEMO_STATIC = ROOT / "engine" / "web" / "demo" / "backtest_demo.json"
DEMO_STATIC_URL = "/static/demo/backtest_demo.json"
CACHE_SCHEMA_VERSION = 1

_ENGINE: Any | None = None


def _bootstrap() -> None:
    """确保回测引擎能定位到 AlphaSplit 根目录与数据。"""
    if not os.getenv("FINBACK_BASE_DIR"):
        os.environ["FINBACK_BASE_DIR"] = str(ROOT)
    if str(BACKTEST_DIR) not in sys.path:
        sys.path.insert(0, str(BACKTEST_DIR))


def data_available() -> bool:
    """检查随包回测数据是否就绪。"""
    required_groups = [
        [DATA_DIR / "hs300_daily_qfq.csv.gz", DATA_DIR / "hs300_daily_qfq.csv"],
        [DATA_DIR / "financial_monthly_clean.csv.gz", DATA_DIR / "financial_monthly_clean.csv"],
        [DATA_DIR / "stock_industry_mapping.csv"],
        [DATA_DIR / "hs300_index_daily.csv"],
        [DATA_DIR / "industry_returns_daily.csv"],
    ]
    return all(any(path.exists() for path in alternatives) for alternatives in required_groups)


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _bootstrap()
        from query_engine import QueryParser, run_query  # type: ignore

        _ENGINE = {"run_query": run_query, "QueryParser": QueryParser}
    return _ENGINE


def get_meta() -> dict[str, Any]:
    engine = get_engine()
    parser = engine["QueryParser"]
    demo = get_demo_info()
    return {
        "api_version": "v1",
        "name": "AlphaSplit QuantSkills 回测归因引擎",
        "data_ready": data_available(),
        "data_dir": str(DATA_DIR),
        "roles": parser.VALID_ROLES,
        "benchmarks": list(parser.VALID_BENCHMARKS.keys()),
        "rebalance_freq": parser.VALID_FREQS,
        "granularity": parser.VALID_FREQS,
        "error_codes": [
            "INDUSTRY_NOT_FOUND",
            "ROLE_NOT_FOUND",
            "INVALID_PARAM",
            "NO_DATA",
            "BENCHMARK_DATA_MISSING",
            "COALITION_BACKTEST_FAILED",
            "EXECUTION_ERROR",
        ],
        "default_benchmark": "hs300",
        "default_rebalance_freq": "monthly",
        "default_granularity": "monthly",
        "demo": demo,
        "cache": {
            "enabled": True,
            "dir": str(CACHE_DIR),
            "demo_endpoint": "/api/backtest/demo",
            "results_endpoint": "/api/backtest/results",
        },
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_key_from_query(query: dict[str, Any]) -> str:
    """相同回测参数生成稳定缓存键（用于路演重复演示与在线秒开）。"""
    tr = query.get("time_range") or {}
    factor_config = query.get("factor_config") or {}
    cache_factor_config = {
        key: factor_config[key]
        for key in ("config_id", "version", "roles")
        if key in factor_config
    }
    payload = {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "start": tr.get("start_date") or "",
        "end": tr.get("end_date") or "",
        "industry": (query.get("industry") or "").strip(),
        "benchmark": query.get("benchmark") or "hs300",
        "freq": query.get("rebalance_freq") or query.get("granularity") or "monthly",
        "target_role": (query.get("target_role") or "").strip(),
        # provenance含确认时间等审计字段，不应导致相同投资参数重复建缓存。
        "factor_config": cache_factor_config,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _cache_response_path(cache_key: str) -> Path:
    return CACHE_DIR / cache_key / "response.json"


def find_cached_result(query: dict[str, Any]) -> Path | None:
    path = _cache_response_path(cache_key_from_query(query))
    return path if path.exists() else None


def save_result_cache(query: dict[str, Any], result: dict[str, Any]) -> str:
    """将成功回测写入参数缓存目录。"""
    if result.get("status") == "error" or "results" not in result:
        return ""
    key = cache_key_from_query(query)
    out_dir = CACHE_DIR / key
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "cache_key": key,
        "request_id": result.get("request_id"),
        "query_summary": result.get("query_summary"),
        "query": query,
        "saved_at": datetime.now().isoformat(),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "response.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return key


def load_cached_result(query: dict[str, Any]) -> dict[str, Any] | None:
    path = find_cached_result(query)
    if not path:
        return None
    data = _read_json(path)
    if not data:
        return None
    data["_source"] = "cache"
    data["_cache_key"] = cache_key_from_query(query)
    return data


def load_result_by_id(request_id: str) -> dict[str, Any] | None:
    """按 request_id 读取历史回测目录中的 response.json。"""
    if not request_id or ".." in request_id or "/" in request_id or "\\" in request_id:
        return None
    path = RESULTS_DIR / request_id / "response.json"
    data = _read_json(path)
    if not data:
        return None
    data["_source"] = "history"
    data["_request_id"] = request_id
    return data


def list_cached_results(limit: int = 20) -> list[dict[str, Any]]:
    """列出参数缓存与历史回测（按时间倒序）。"""
    items: list[dict[str, Any]] = []

    if CACHE_DIR.exists():
        for d in CACHE_DIR.iterdir():
            if not d.is_dir():
                continue
            meta = _read_json(d / "meta.json")
            if meta:
                items.append(
                    {
                        "kind": "cache",
                        "cache_key": meta.get("cache_key", d.name),
                        "request_id": meta.get("request_id"),
                        "query_summary": meta.get("query_summary"),
                        "saved_at": meta.get("saved_at"),
                    }
                )

    if RESULTS_DIR.exists():
        for d in RESULTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            resp = d / "response.json"
            if not resp.exists():
                continue
            data = _read_json(resp)
            if not data:
                continue
            items.append(
                {
                    "kind": "run",
                    "request_id": d.name,
                    "query_summary": data.get("query_summary"),
                    "saved_at": data.get("timestamp"),
                    "status": data.get("status", "success"),
                }
            )

    items.sort(key=lambda x: x.get("saved_at") or "", reverse=True)
    return items[: max(1, limit)]


def get_demo_info() -> dict[str, Any]:
    data = get_demo_result()
    if not data:
        return {"available": False, "static_url": DEMO_STATIC_URL}
    return {
        "available": True,
        "demo_id": data.get("demo_id", "roadshow"),
        "label": data.get("demo_label", "路演官方演示"),
        "query_summary": data.get("query_summary"),
        "endpoint": "/api/backtest/demo",
        "static_url": DEMO_STATIC_URL,
        "has_replay": bool(data.get("demo_replay")),
    }


def get_demo_result() -> dict[str, Any] | None:
    """路演官方演示包：优先静态 JSON（可离线），不依赖回测引擎。"""
    data = _read_json(DEMO_STATIC)
    if not data:
        return None
    data = dict(data)
    data["_source"] = "demo"
    data.setdefault("status", "success")
    return data


def _emit_cached_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    result: dict[str, Any],
    *,
    paced: str = "cache",
) -> None:
    """缓存/演示命中时分阶段回放进度（路演观感，非一次性灌入）。"""
    if not progress_callback:
        return
    replay = result.get("demo_replay") or {}
    is_demo = paced == "demo"
    delays = {
        "demo": {"stage": 1.15, "role": 1.05, "pipeline": 1.55, "shapley": 0.72, "snapshot": 0.95},
        "cache": {"stage": 0.55, "role": 0.45, "pipeline": 0.7, "shapley": 0.3, "snapshot": 0.45},
    }
    d = delays.get(paced, delays["cache"])

    if is_demo:
        stages = [
            ("parse", 8, "解析回测参数…"),
            ("init", 14, "加载沪深300行情与行业映射…"),
            ("factors", 28, "五类角色因子选股计算中…"),
            ("pipeline", 48, "多角色 Pipeline 组合回测…"),
            ("shapley", 72, "夏普利反事实对照实验…"),
            ("save", 92, "汇总贡献与生成报告…"),
        ]
    else:
        stages = [
            ("parse", 8, "命中缓存：解析参数"),
            ("init", 14, "命中缓存：加载数据快照"),
            ("factors", 28, "命中缓存：因子选股结果"),
            ("pipeline", 48, "命中缓存：组合回测"),
            ("shapley", 72, "命中缓存：夏普利归因"),
            ("save", 92, "命中缓存：结果就绪"),
        ]

    for stage, pct, msg in stages:
        progress_callback(
            {"type": "stage", "stage": stage, "percent": pct, "message": msg}
        )
        time.sleep(d["stage"])

    if replay.get("stocks") is not None:
        progress_callback(
            {
                "type": "data_snapshot",
                "stocks": replay.get("stocks"),
                "trading_days": replay.get("trading_days"),
            }
        )
        time.sleep(d["snapshot"])

    role_order = replay.get("role_order") or [
        "行业分析师",
        "个股分析师",
        "策略分析师",
        "量化分析师",
        "风控分析师",
    ]
    roles = replay.get("roles") or {}
    for i, role in enumerate(role_order):
        info = roles.get(role, {})
        if not info and not is_demo:
            continue
        progress_callback(
            {
                "type": "role_factor",
                "role": role,
                "months": info.get("months", 0),
                "sample_stocks": info.get("sample", []),
                "sample_labels": info.get("sample_labels", info.get("sample", [])),
                "percent": 22 + (i + 1) * 5,
            }
        )
        time.sleep(d["role"])

    if replay.get("pipeline_return") is not None:
        time.sleep(d["pipeline"] * 0.35)
        progress_callback(
            {
                "type": "pipeline",
                "total_return": replay.get("pipeline_return"),
                "monthly": replay.get("pipeline_monthly", []),
                "percent": 55,
            }
        )
        time.sleep(d["pipeline"])

    shapley_pts = replay.get("shapley_points", [])
    total_sp = max(len(shapley_pts), 1)
    for pt in shapley_pts:
        progress_callback(
            {
                "type": "shapley",
                "subset": pt.get("subset", []),
                "subset_label": pt.get("label"),
                "subset_full": pt.get("fullLabel"),
                "subset_return": (pt.get("y") or 0) / 100,
                "metric": pt.get("metric", "角色Shapley超额贡献"),
                "current": pt.get("index"),
                "total": total_sp,
                "percent": 72 + int((pt.get("index") or 0) / total_sp * 18),
            }
        )
        time.sleep(d["shapley"])

    progress_callback(
        {
            "type": "stage",
            "stage": "complete",
            "percent": 100,
            "message": "计算完成，正在生成业务结论…",
        }
    )
    time.sleep(0.75 if is_demo else 0.35)


def normalize_request(raw: dict[str, Any]) -> dict[str, Any]:
    """兼容嵌套 query 与扁平 query 两种 JSON 格式。"""
    if "query" in raw and isinstance(raw["query"], dict):
        query_json = dict(raw)
        query_json.setdefault("request_id", f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        query_json.setdefault("timestamp", datetime.now().isoformat())
        return query_json

    return {
        "request_id": raw.get("request_id") or f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "timestamp": raw.get("timestamp") or datetime.now().isoformat(),
        "query": {
            "time_range": {
                "start_date": raw.get("start_date"),
                "end_date": raw.get("end_date"),
            },
            "target_role": raw.get("target_role") or None,
            "industry": raw.get("industry") or None,
            "role_weights": raw.get("role_weights") or None,
            "benchmark": raw.get("benchmark") or "hs300",
            "rebalance_freq": raw.get("rebalance_freq") or "monthly",
            "granularity": raw.get("granularity") or "monthly",
        },
    }


def run_backtest_query(
    raw: dict[str, Any],
    progress_callback=None,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
    demo_mode: bool = False,
) -> dict[str, Any]:
    """
    执行一次回测查询，返回引擎标准 JSON。

    - demo_mode=True：直接返回路演演示包（离线可用）
    - use_cache=True：相同参数命中 `_cache/` 时秒开
    - force_refresh=True：忽略缓存强制重算
    """
    if demo_mode:
        demo = get_demo_result()
        if not demo:
            return {
                "status": "error",
                "error_code": "NO_DATA",
                "error_message": "路演演示包未找到，请确认 engine/web/demo/backtest_demo.json 存在。",
            }
        _emit_cached_progress(progress_callback, demo, paced="demo")
        return demo

    query_json = normalize_request(raw)
    query = query_json.get("query") or {}

    if use_cache and not force_refresh:
        cached = load_cached_result(query)
        if cached:
            _emit_cached_progress(progress_callback, cached, paced="cache")
            return cached

    if not data_available():
        return {
            "status": "error",
            "error_code": "NO_DATA",
            "error_message": f"回测数据未找到，请确认 {DATA_DIR} 已随仓库提供。",
        }

    engine = get_engine()
    result = engine["run_query"](query_json, progress_callback=progress_callback)
    if use_cache and result.get("status") != "error" and "results" in result:
        key = save_result_cache(query, result)
        if key:
            result["_cache_key"] = key
            result["_source"] = "computed"
    return result


def map_error_status(error_code: str) -> int:
    return {
        "INDUSTRY_NOT_FOUND": 400,
        "ROLE_NOT_FOUND": 400,
        "INVALID_PARAM": 400,
        "NO_DATA": 404,
        "BENCHMARK_DATA_MISSING": 422,
        "COALITION_BACKTEST_FAILED": 500,
        "EXECUTION_ERROR": 500,
    }.get(error_code, 400)
