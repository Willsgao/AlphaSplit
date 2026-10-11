"""生成路演演示用 backtest_demo.json（含 demo_replay）。"""
from __future__ import annotations

import csv
import argparse
import json
import math
import statistics
from datetime import date
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def monthly_stats(rows: list[dict], key: str) -> dict[str, float | None]:
    """Use the same monthly-return definitions as the frontend comparison table."""
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return {"total_return": None, "sharpe_ratio": None, "max_drawdown": None}

    nav = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in values:
        nav *= 1.0 + value
        peak = max(peak, nav)
        max_drawdown = min(max_drawdown, nav / peak - 1.0)

    total_return = nav - 1.0
    annual_return = (1.0 + total_return) ** (12.0 / len(values)) - 1.0
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    annual_volatility = deviation * math.sqrt(12.0)
    return {
        "total_return": total_return,
        "sharpe_ratio": (
            (annual_return - 0.02) / annual_volatility
            if annual_volatility > 0
            else None
        ),
        "max_drawdown": max_drawdown,
    }


def stock_labels_from_daily() -> dict[str, str]:
    names: dict[str, str] = {}
    daily = ROOT / "data/processed/hs300_daily_qfq.csv.gz"
    if not daily.exists():
        daily = ROOT / "data/processed/hs300_daily_qfq.csv"
    if not daily.exists():
        daily = ROOT / "data/processed/hs300_daily_cleaned.csv"
    if not daily.exists():
        return names
    import pandas as pd

    df = pd.read_csv(daily, usecols=["stock_code", "stock_name"])
    for sym, name in df.drop_duplicates("stock_code").values:
        code = str(sym).split(".")[0].zfill(6)
        n = str(name).strip()
        if n:
            names[code] = n
    return names


def label(code: str, names: dict[str, str]) -> str:
    c = str(code).split(".")[0].zfill(6)
    n = names.get(c, "")
    return f"{n}（{c}）" if n else c


def main() -> None:
    parser = argparse.ArgumentParser(description="从指定回测结果生成路演演示包")
    parser.add_argument("--request-id", required=True, help="backtest/results 下的请求目录名")
    parser.add_argument(
        "--default-request-id",
        help="同口径默认方案请求目录名；提供后生成新策略/默认策略/HS300三方对照",
    )
    parser.add_argument("--start-date", required=True, help="演示回测开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="演示回测结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    result_dir = ROOT / "backtest" / "results" / args.request_id
    resp_path = result_dir / "response.json"
    sel_path = result_dir / "selections.csv"
    if not resp_path.exists():
        raise SystemExit(f"missing {resp_path}")

    data = json.loads(resp_path.read_text(encoding="utf-8"))
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end:
        raise SystemExit("start-date must not be after end-date")
    data["demo_id"] = f"roadshow_hs300_{start:%Y%m%d}_{end:%Y%m%d}_comparison"
    data["demo_label"] = "路演官方演示 · 新策略 / 默认策略 / HS300 三方对照"
    data["query"] = {
        "time_range": {"start_date": args.start_date, "end_date": args.end_date},
        "industry": None,
        "benchmark": "hs300",
        "rebalance_freq": "monthly",
        "granularity": "monthly",
        "target_role": None,
    }

    names = stock_labels_from_daily()
    roles: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    if sel_path.exists():
        with sel_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                role = row.get("role") or row.get("\ufeffrole", "")
                roles[role][row["period"]].append(row["stock"])

    role_order = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]
    role_replay: dict[str, dict] = {}
    for role in role_order:
        periods = sorted(roles.get(role, {}).keys())
        last = periods[-1] if periods else None
        samples = roles[role][last][:3] if last else []
        role_replay[role] = {
            "months": len(periods),
            "sample": samples,
            "sample_labels": [label(s, names) for s in samples],
            "done": True,
        }

    ts = data.get("results", {}).get("time_series", [])
    monthly = []
    cum = 1.0
    for row in ts:
        cum *= 1 + float(row.get("return", 0))
        monthly.append(
            {
                "month": row["period"],
                "return": row["return"],
                "cumulative": cum - 1.0,
            }
        )

    ov = data.get("results", {}).get("overview", {})
    bd = data.get("results", {}).get("role_breakdown", [])
    shapley_pts = []
    for i, r in enumerate(bd):
        contribution = float(r.get("shapley_raw", 0))
        weight = float(r.get("weight", 0))
        if contribution < 0:
            r["highlight"] = (
                f"Shapley超额贡献 {contribution:.2%}（负贡献），"
                f"证据轨建议权重 {weight:.1%}"
            )
        else:
            r["highlight"] = (
                f"Shapley超额贡献 {contribution:+.2%}，"
                f"证据轨建议权重 {weight:.1%}"
            )
        shapley_pts.append(
            {
                "index": i + 1,
                "subset": [r["role"]],
                "label": r["role"][:2],
                "fullLabel": r["role"],
                "y": round(float(r.get("shapley_raw", 0)) * 100, 2),
                "metric": "角色Shapley超额贡献",
            }
        )

    unique_stocks = {
        stock
        for role_periods in roles.values()
        for stocks in role_periods.values()
        for stock in stocks
    }
    daily_dates: set[str] = set()
    daily_path = result_dir / "daily_returns.csv"
    if daily_path.exists():
        with daily_path.open(encoding="utf-8-sig") as f:
            daily_dates = {row["date"] for row in csv.DictReader(f) if row.get("date")}

    data["demo_replay"] = {
        "stocks": len(unique_stocks),
        "trading_days": len(daily_dates),
        "pipeline_return": ov.get("total_return"),
        "pipeline_monthly": monthly,
        "roles": role_replay,
        "role_order": role_order,
        "shapley_points": shapley_pts,
    }

    if args.default_request_id:
        default_path = (
            ROOT / "backtest" / "results" / args.default_request_id / "response.json"
        )
        if not default_path.exists():
            raise SystemExit(f"missing {default_path}")
        default_data = json.loads(default_path.read_text(encoding="utf-8"))
        customer_results = data.get("results", {})
        default_results = default_data.get("results", {})
        customer_overview = customer_results.get("overview")
        default_overview = default_results.get("overview")
        if not customer_overview or not default_overview:
            raise SystemExit("customer/default response missing results.overview")

        customer_config = customer_results.get("factor_config") or {}
        default_config = default_results.get("factor_config") or {}
        data["comparison"] = {
            "loading": False,
            "source": "precomputed_verified_pair",
            "customer": customer_overview,
            "default": default_overview,
            "benchmark": monthly_stats(customer_results.get("time_series", []), "benchmark"),
            "customer_time_series": customer_results.get("time_series", []),
            "default_time_series": default_results.get("time_series", []),
            "customer_config_id": customer_config.get("config_id"),
            "default_config_id": default_config.get("config_id"),
            "customer_request_id": data.get("request_id"),
            "default_request_id": default_data.get("request_id"),
            "same_scope": data.get("query_summary") == default_data.get("query_summary"),
        }

    out = ROOT / "engine/web/demo/backtest_demo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
