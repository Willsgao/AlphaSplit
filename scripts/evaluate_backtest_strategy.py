"""Run repeatable pipeline-only diagnostics across periods and risk settings.

This intentionally skips Shapley attribution. It is a development gate for
portfolio construction changes, not a replacement for the official backtest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKTEST_DIR = ROOT / "backtest"
if str(BACKTEST_DIR) not in sys.path:
    sys.path.insert(0, str(BACKTEST_DIR))

from factor_config import default_factor_config  # noqa: E402
from query_engine import (  # noqa: E402
    BacktestExecutor,
    DataLoader,
    build_benchmark_info,
)


DEFAULT_PERIODS = [
    ("2022-07-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", "2025-06-30"),
]


class NullRecorder:
    def record_selection(self, *args, **kwargs):
        pass

    def record_factor_score(self, *args, **kwargs):
        pass

    def record_rebalance(self, *args, **kwargs):
        pass

    def record_daily_return(self, *args, **kwargs):
        pass


class NullProgress:
    def stage(self, *args, **kwargs):
        pass

    def log(self, *args, **kwargs):
        pass

    def data_snapshot(self, *args, **kwargs):
        pass

    def role_factor_done(self, *args, **kwargs):
        pass


def parse_period(value: str) -> tuple[str, str]:
    try:
        start, end = value.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("period must be START:END") from exc
    return start, end


def variants() -> dict[str, dict]:
    return {
        "strict_5pct": {
            "risk": {"max_single": 0.05, "max_industry": 0.25, "stop_loss_monthly": -0.05},
            "stock_signal_weight": 0.50,
            "industry_count": 3,
        },
        "concentrated_2industry": {
            "risk": {"max_single": 0.10, "max_industry": 0.50, "stop_loss_monthly": -0.05},
            "stock_signal_weight": 0.50,
            "industry_count": 2,
        },
        "balanced_3industry": {
            "risk": {"max_single": 0.10, "max_industry": 0.40, "stop_loss_monthly": -0.05},
            "stock_signal_weight": 0.50,
            "industry_count": 3,
        },
        "diversified_4industry": {
            "risk": {"max_single": 0.10, "max_industry": 0.30, "stop_loss_monthly": -0.05},
            "stock_signal_weight": 0.50,
            "industry_count": 4,
        },
    }


def evaluate_period(loader: DataLoader, start: str, end: str) -> list[dict]:
    executor = BacktestExecutor(loader, NullRecorder(), progress=NullProgress())
    config = default_factor_config()
    params = {
        "start_date": start,
        "end_date": end,
        "industry": None,
        "benchmark": "hs300",
        "rebalance_freq": "monthly",
        "granularity": "monthly",
        "factor_config": config,
    }
    trade_daily = loader.filter_by_date(start, end)
    analysis_start = pd.Timestamp(start) - pd.Timedelta(
        days=executor.FACTOR_WARMUP_CALENDAR_DAYS
    )
    daily = loader.filter_by_date(str(analysis_start.date()), end)
    dates = sorted(trade_daily["date"].unique())
    stocks = sorted(trade_daily["symbol"].unique())
    selections = executor._compute_factors_and_select(
        daily, stocks, executor.DYNAMIC_ROLES, params
    )
    benchmark = loader.get_index_returns(str(analysis_start.date()), end)

    rows = []
    for name, settings in variants().items():
        executor.risk_control.config.update(settings["risk"])
        executor.STOCK_SIGNAL_WEIGHT = settings["stock_signal_weight"]
        executor.INDUSTRY_COUNT = settings["industry_count"]
        result = executor._run_pipeline_backtest(
            daily, dates, selections, benchmark, params
        )
        benchmark_info = build_benchmark_info(
            benchmark,
            result["monthly_returns"],
            portfolio_return=result["total_return"],
        )
        rows.append(
            {
                "period": f"{start}..{end}",
                "variant": name,
                "portfolio_return": float(result["total_return"]),
                "benchmark_return": benchmark_info["return"],
                "excess_return": benchmark_info["excess"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--period",
        action="append",
        type=parse_period,
        help="START:END; repeat for multiple periods",
    )
    args = parser.parse_args()
    periods = args.period or DEFAULT_PERIODS

    loader = DataLoader()
    loader.load()
    rows = []
    for start, end in periods:
        rows.extend(evaluate_period(loader, start, end))
    print("EVALUATION_JSON=" + json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
