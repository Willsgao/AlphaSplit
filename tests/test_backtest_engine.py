"""回测引擎集成测试。"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import pandas as pd

from engine.integrations.quantskills_backtest import (
    _bootstrap,
    cache_key_from_query,
    data_available,
    get_demo_result,
    get_meta,
    normalize_request,
)

_bootstrap()
from query_engine import (  # type: ignore  # noqa: E402
    BacktestError,
    BacktestExecutor,
    allocate_new_pool_weights,
    build_benchmark_info,
    describe_excess_return,
    role_selection_limit,
    select_industries_from_ranked_stocks,
    calculate_portfolio_turnover,
    blend_stock_and_quant_rankings,
    complete_ranked_candidate_pool,
    select_neutral_stocks,
    select_without_quant,
)
from risk_control_module import RiskControlModule  # type: ignore  # noqa: E402
from timing_module import TimingModule  # type: ignore  # noqa: E402


class _SilentProgress:
    def shapley_subset(self, *args, **kwargs):
        pass

    def partial_shapley(self, *args, **kwargs):
        pass

    def log(self, *args, **kwargs):
        pass


class _SilentRecorder:
    def record_rebalance(self, *args, **kwargs):
        pass

    def record_daily_return(self, *args, **kwargs):
        pass


class TestQuantSkillsBacktest(unittest.TestCase):
    def test_data_available(self):
        self.assertTrue(data_available(), "data/processed 应随仓库提供")

    def test_meta_roles(self):
        meta = get_meta()
        self.assertIn("行业分析师", meta["roles"])
        self.assertEqual(meta["default_benchmark"], "hs300")
        self.assertIn("demo", meta)

    def test_demo_bundle_available(self):
        demo = get_demo_result()
        self.assertIsNotNone(demo, "路演演示包应随仓库提供")
        self.assertEqual(demo.get("_source"), "demo")
        self.assertIn("results", demo)
        self.assertIn("demo_replay", demo)

    def test_demo_bundle_financial_invariants(self):
        demo = get_demo_result()
        results = demo["results"]
        overview = results["overview"]
        breakdown = results["role_breakdown"]

        self.assertNotAlmostEqual(overview["benchmark_return"], 0.0, places=10)
        self.assertAlmostEqual(
            overview["excess_return"],
            overview["total_return"] - overview["benchmark_return"],
            places=10,
        )
        self.assertAlmostEqual(sum(row["weight"] for row in breakdown), 1.0, places=10)
        policy = results["allocation_policy"]
        self.assertLessEqual(
            max(row["weight"] for row in breakdown),
            policy["effective_max_role_weight"] + 1e-10,
        )
        self.assertEqual(
            overview.get("characteristic_function"),
            "excess_return_vs_hs300",
        )
        self.assertAlmostEqual(
            sum(row["shapley_raw"] for row in breakdown),
            overview["excess_return"],
            places=10,
        )
        for row in breakdown:
            self.assertIn("证据轨建议权重", row["highlight"])
            self.assertIn(f'{row["weight"]:.1%}', row["highlight"])
            if row["shapley_raw"] < 0:
                self.assertEqual(row["weight"], 0.0)

        self.assertEqual(policy["method"], "positive_shapley_capped")
        self.assertFalse(policy["negative_contribution_rewarded"])

    def test_cache_key_stable(self):
        q = {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
        }
        k1 = cache_key_from_query(q)
        k2 = cache_key_from_query(q)
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 16)

    def test_cache_key_changes_with_factor_config(self):
        q = {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
        }
        custom = {
            **q,
            "factor_config": {
                "roles": {
                    "风控分析师": {"factor_weights": {"risk_drawdown_5d": 2.0}}
                }
            },
        }
        self.assertNotEqual(cache_key_from_query(q), cache_key_from_query(custom))

    def test_normalize_nested_request(self):
        raw = {
            "request_id": "t1",
            "query": {"time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"}},
        }
        out = normalize_request(raw)
        self.assertEqual(out["request_id"], "t1")
        self.assertIn("query", out)

    def test_normalize_flat_request(self):
        raw = {"start_date": "2024-01-01", "end_date": "2024-06-30", "benchmark": "hs300"}
        out = normalize_request(raw)
        self.assertEqual(out["query"]["benchmark"], "hs300")

    def test_benchmark_info_aligns_with_portfolio_months(self):
        index = pd.Series(
            [0.10, -0.05, 0.20],
            index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]),
        )
        portfolio = pd.Series(
            [0.08, 0.04],
            index=pd.PeriodIndex(["2024-02", "2024-03"], freq="M"),
        )

        info = build_benchmark_info(index, portfolio, portfolio_return=0.1232)

        self.assertAlmostEqual(info["return"], 0.14, places=10)
        self.assertAlmostEqual(info["excess"], -0.0168, places=10)

    def test_benchmark_info_rejects_missing_portfolio_month(self):
        index = pd.Series(
            [0.02],
            index=pd.to_datetime(["2024-01-31"]),
        )
        portfolio = pd.Series(
            [0.01, 0.03],
            index=pd.PeriodIndex(["2024-01", "2024-02"], freq="M"),
        )

        with self.assertRaises(BacktestError) as ctx:
            build_benchmark_info(index, portfolio)

        self.assertEqual(ctx.exception.error_code, "BENCHMARK_DATA_MISSING")

    def test_neutral_selection_is_deterministic_and_order_independent(self):
        stocks = ["000004", "000002", "000005", "000001", "000003"]
        selected = select_neutral_stocks(stocks, limit=3, context="2024-02")

        self.assertEqual(
            selected,
            select_neutral_stocks(list(reversed(stocks)), limit=3, context="2024-02"),
        )
        self.assertEqual(len(selected), 3)

    def test_stock_analyst_produces_candidate_pool_for_quant(self):
        self.assertEqual(role_selection_limit("个股分析师", final_top_n=10), 100)
        self.assertEqual(role_selection_limit("行业分析师", final_top_n=10), 300)
        self.assertEqual(role_selection_limit("量化分析师", final_top_n=10), 10)

    def test_stock_and_quant_rankings_are_blended(self):
        stock_ranked = ["a", "b", "c", "d"]
        quant_ranked = ["d", "c", "b", "a"]

        selected = blend_stock_and_quant_rankings(
            stock_ranked, quant_ranked, limit=2, stock_weight=0.75
        )

        self.assertEqual(selected, ["a", "b"])

    def test_industry_role_ranking_is_aggregated_into_industries(self):
        ranked = ["b1", "b2", "a1", "c1", "a2", "d1"]
        mapping = {
            "a1": "行业A", "a2": "行业A",
            "b1": "行业B", "b2": "行业B",
            "c1": "行业C", "d1": "行业D",
        }

        selected = select_industries_from_ranked_stocks(ranked, mapping, limit=3)

        self.assertEqual(selected, ["行业B", "行业A", "行业C"])

    def test_sparse_role_candidates_are_completed_inside_selected_industries(self):
        completed = complete_ranked_candidate_pool(
            ["a", "outside"],
            ["a", "b", "c", "d"],
            target_size=3,
            context="2024-07",
        )

        self.assertEqual(completed[0], "a")
        self.assertEqual(len(completed), 3)
        self.assertTrue(set(completed).issubset({"a", "b", "c", "d"}))

    def test_risk_limits_do_not_renormalize_past_single_stock_cap(self):
        risk = RiskControlModule({"max_single": 0.05, "max_industry": 1.0})
        weights = {str(index): 0.10 for index in range(10)}

        adjusted = risk.apply_position_limits(weights)

        self.assertLessEqual(max(adjusted.values()), 0.05)
        self.assertAlmostEqual(sum(adjusted.values()), 0.50)

    def test_risk_constraints_preserve_timing_cash_position(self):
        risk = RiskControlModule({"max_single": 0.05, "max_industry": 0.25})
        weights = {str(index): 0.04 for index in range(10)}
        mapping = {
            str(index): "行业A" if index < 5 else "行业B"
            for index in range(10)
        }

        adjusted = risk.apply_all(weights, mapping)

        self.assertAlmostEqual(sum(adjusted.values()), 0.40)

    def test_industry_limit_does_not_renormalize_past_cap(self):
        risk = RiskControlModule({"max_single": 1.0, "max_industry": 0.25})
        weights = {"a": 0.30, "b": 0.30, "c": 0.20, "d": 0.20}
        mapping = {"a": "行业A", "b": "行业A", "c": "行业B", "d": "行业C"}

        adjusted = risk.apply_industry_limit(weights, mapping)

        industry_a = adjusted["a"] + adjusted["b"]
        self.assertAlmostEqual(industry_a, 0.25)
        self.assertAlmostEqual(sum(adjusted.values()), 0.65)

    def test_joint_risk_projection_redistributes_only_within_available_capacity(self):
        risk = RiskControlModule({"max_single": 0.10, "max_industry": 0.40})
        weights = {str(index): 0.10 for index in range(10)}
        mapping = {
            **{str(index): "行业A" for index in range(6)},
            **{str(index): "行业B" for index in range(6, 8)},
            **{str(index): "行业C" for index in range(8, 10)},
        }

        adjusted = risk.project_to_limits(weights, mapping)

        self.assertAlmostEqual(sum(adjusted.values()), 0.80)
        self.assertLessEqual(max(adjusted.values()), 0.10 + 1e-12)
        industry_a = sum(adjusted[str(index)] for index in range(6))
        self.assertLessEqual(industry_a, 0.40 + 1e-12)

    def test_joint_risk_projection_preserves_exposure_when_capacity_is_sufficient(self):
        risk = RiskControlModule({"max_single": 0.10, "max_industry": 0.40})
        weights = {str(index): 0.10 for index in range(10)}
        mapping = {
            str(index): f"行业{index // 4}"
            for index in range(10)
        }

        adjusted = risk.project_to_limits(weights, mapping)

        self.assertAlmostEqual(sum(adjusted.values()), 1.0)
        self.assertLessEqual(max(adjusted.values()), 0.10 + 1e-12)

    def test_turnover_uses_actual_weight_changes_and_cash(self):
        initial = calculate_portfolio_turnover({}, {"a": 0.5, "b": 0.5})
        unchanged = calculate_portfolio_turnover(
            {"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}
        )
        full_replacement = calculate_portfolio_turnover(
            {"a": 0.5, "b": 0.5}, {"c": 0.5, "d": 0.5}
        )

        self.assertAlmostEqual(initial, 1.0)
        self.assertAlmostEqual(unchanged, 0.0)
        self.assertAlmostEqual(full_replacement, 1.0)

    def test_without_quant_keeps_stock_analyst_ranking(self):
        ranked = [f"{i:06d}" for i in range(30)]

        selected = select_without_quant(
            ranked,
            limit=10,
            context="2024-02",
            stock_analyst_active=True,
        )

        self.assertEqual(selected, ranked[:10])

    def test_pipeline_routes_candidate_pool_to_quant_factors(self):
        class QuantSpy:
            def __init__(self):
                self.calls = []

            def optimize_selection(self, df, stocks, role, top_n):
                self.calls.append((list(stocks), role, top_n))
                return list(stocks)[:top_n], {}

        class IndustryStub:
            def select_industries(self, *args, **kwargs):
                return ["测试行业"]

        class TimingStub:
            def calculate_regime_aware_position(self, *args, **kwargs):
                return 1.0

        class RiskStub:
            def apply_all(self, weights, *args, **kwargs):
                return weights

        executor = object.__new__(BacktestExecutor)
        executor.loader = type("LoaderStub", (), {"df_index": pd.DataFrame()})()
        executor.recorder = _SilentRecorder()
        executor.quant_analyst = QuantSpy()
        executor.industry_analyst = IndustryStub()
        executor.timing = TimingStub()
        executor.risk_control = RiskStub()

        symbols = [f"{i:06d}" for i in range(30)]
        dates = pd.to_datetime(["2024-02-01", "2024-02-02"])
        all_dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
        df = pd.DataFrame(
            [
                {"date": day, "symbol": symbol, "close": 100.0 + day.day}
                for symbol in symbols
                for day in all_dates
            ]
        )
        selections = {"个股分析师": {"2024-02": symbols}}
        index = pd.Series(
            [0.001] * 25,
            index=pd.date_range("2024-01-01", periods=25, freq="D"),
        )
        params = {"industry": None}
        mapping = {symbol: "测试行业" for symbol in symbols}

        with patch("query_engine.get_industry_mapping", return_value=mapping):
            executor._run_pipeline_backtest(
                df,
                dates,
                selections,
                index,
                params,
                active_roles=set(executor.DYNAMIC_ROLES),
            )
            executor._run_pipeline_backtest(
                df,
                dates,
                selections,
                index,
                params,
                active_roles=set(executor.DYNAMIC_ROLES),
            )

        candidates, role, top_n = executor.quant_analyst.calls[0]
        self.assertEqual(len(executor.quant_analyst.calls), 1)
        self.assertEqual(len(candidates), 30)
        self.assertEqual(role, "量化分析师")
        self.assertEqual(top_n, 30)

    def test_regime_aware_timing_stays_invested_in_positive_trend(self):
        timing = TimingModule(target_vol=0.05, lookback=20)
        positive_history = pd.Series(
            [0.01] * 20,
            index=pd.date_range("2024-01-01", periods=20, freq="D"),
        )

        ratio = timing.calculate_regime_aware_position(positive_history, "2024-02")

        self.assertEqual(ratio, 1.0)

    def test_regime_aware_timing_can_reduce_negative_high_vol_regime(self):
        timing = TimingModule(target_vol=0.05, lookback=20)
        negative_volatile = pd.Series(
            [-0.03, 0.01] * 10,
            index=pd.date_range("2024-01-01", periods=20, freq="D"),
        )

        ratio = timing.calculate_regime_aware_position(negative_volatile, "2024-02")

        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 0.5)

    def test_shapley_uses_excess_return_characteristic_function(self):
        executor = object.__new__(BacktestExecutor)
        executor.DYNAMIC_ROLES = ["A", "B"]
        executor.progress = _SilentProgress()
        coalition_returns = {
            frozenset({"A"}): 0.10,
            frozenset({"B"}): 0.05,
            frozenset({"A", "B"}): 0.20,
        }

        def run_coalition(*args, active_roles, **kwargs):
            value = coalition_returns[frozenset(active_roles)]
            return {
                "total_return": value,
                "monthly_returns": pd.Series(
                    [value], index=pd.PeriodIndex(["2024-01"], freq="M")
                ),
            }

        executor._run_pipeline_backtest = run_coalition
        index = pd.Series([0.04], index=pd.to_datetime(["2024-01-31"]))
        full_results = run_coalition(None, active_roles={"A", "B"})

        result = executor._compute_shapley_attribution(
            None, None, None, index, {}, full_results
        )

        summary = result["_shapley_summary"]
        self.assertEqual(summary["characteristic_function"], "excess_return_vs_hs300")
        self.assertAlmostEqual(summary["sum"], 0.16, places=10)
        self.assertAlmostEqual(summary["full_excess_return"], 0.16, places=10)
        self.assertAlmostEqual(result["A"]["shapley_value"], 0.105, places=10)
        self.assertAlmostEqual(result["B"]["shapley_value"], 0.055, places=10)

    def test_shapley_fails_fast_when_any_coalition_fails(self):
        executor = object.__new__(BacktestExecutor)
        executor.DYNAMIC_ROLES = ["A", "B"]
        executor.progress = _SilentProgress()

        def run_coalition(*args, active_roles, **kwargs):
            if active_roles == {"B"}:
                raise RuntimeError("synthetic coalition failure")
            return {
                "total_return": 0.10,
                "monthly_returns": pd.Series(
                    [0.10], index=pd.PeriodIndex(["2024-01"], freq="M")
                ),
            }

        executor._run_pipeline_backtest = run_coalition
        index = pd.Series([0.04], index=pd.to_datetime(["2024-01-31"]))

        with self.assertRaises(BacktestError) as ctx:
            executor._compute_shapley_attribution(None, None, None, index, {})

        self.assertEqual(ctx.exception.error_code, "COALITION_BACKTEST_FAILED")
        self.assertIn("B", ctx.exception.error_message)

    def test_excess_description_has_three_states(self):
        self.assertIn("跑赢基准", describe_excess_return(0.01))
        self.assertIn("跑输基准", describe_excess_return(-0.01))
        self.assertIn("基本持平", describe_excess_return(0.0))

    def test_new_pool_uses_positive_shapley_only(self):
        weights = allocate_new_pool_weights(
            {"A": 0.12, "B": 0.03, "C": -0.01, "D": 0.04, "E": 0.03},
            max_weight=0.5,
        )

        self.assertAlmostEqual(sum(weights.values()), 1.0, places=10)
        self.assertEqual(weights["C"], 0.0)
        self.assertLessEqual(max(weights.values()), 0.5 + 1e-10)

    def test_new_pool_cap_redistributes_without_breaking_cap(self):
        weights = allocate_new_pool_weights(
            {"A": 0.90, "B": 0.05, "C": 0.05},
            max_weight=0.5,
        )

        self.assertAlmostEqual(weights["A"], 0.5, places=10)
        self.assertAlmostEqual(weights["B"], 0.25, places=10)
        self.assertAlmostEqual(weights["C"], 0.25, places=10)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=10)

    def test_new_pool_relaxes_cap_when_only_one_role_is_positive(self):
        weights = allocate_new_pool_weights(
            {"A": 0.10, "B": -0.01, "C": -0.02},
            max_weight=0.5,
        )

        self.assertEqual(weights, {"A": 1.0, "B": 0.0, "C": 0.0})

    def test_query_entry_runs_on_gbk_console(self):
        script = (
            "from engine.integrations.quantskills_backtest import get_engine; "
            "run_query=get_engine()['run_query']; "
            "result=run_query({'request_id':'encoding_test','query':{'target_role':'invalid'}}); "
            "print('STATUS', result.get('error_code'))"
        )
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "gbk"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("gbk", errors="replace"))
        self.assertIn(b"STATUS ROLE_NOT_FOUND", result.stdout)


if __name__ == "__main__":
    unittest.main()
