"""生成路演演示用 backtest_demo.json（含 demo_replay）。"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stock_labels_from_daily() -> dict[str, str]:
    names: dict[str, str] = {}
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
    resp_path = ROOT / "backtest/results/web_1787472944461/response.json"
    sel_path = ROOT / "backtest/results/web_1787472944461/selections.csv"
    if not resp_path.exists():
        raise SystemExit(f"missing {resp_path}")

    data = json.loads(resp_path.read_text(encoding="utf-8"))
    data["demo_id"] = "roadshow_hs300_2024h1"
    data["demo_label"] = "路演官方演示 · 2024上半年 HS300 五角色"
    data["query"] = {
        "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
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
        shapley_pts.append(
            {
                "index": i + 1,
                "subset": [r["role"]],
                "label": r["role"][:2],
                "fullLabel": r["role"],
                "y": round(float(r.get("shapley_raw", 0)) * 100, 2),
            }
        )

    data["demo_replay"] = {
        "stocks": 300,
        "trading_days": 121,
        "pipeline_return": ov.get("total_return"),
        "pipeline_monthly": monthly,
        "roles": role_replay,
        "role_order": role_order,
        "shapley_points": shapley_pts,
    }

    out = ROOT / "engine/web/demo/backtest_demo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
