"""agentic / settlement / 多场景 基础测试。"""
from __future__ import annotations

import unittest

from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import confirm_settlement, run_negotiation
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, list_scenarios, load_scenario, scenario_params
from engine.core.settlement import build_bands, propose_from_negotiation


class TestScenarioCatalog(unittest.TestCase):
    def test_two_scenarios_listed(self):
        ids = {s["id"] for s in list_scenarios()}
        self.assertIn("quant_fund", ids)
        self.assertIn("credit_model", ids)


class TestQuantFundCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = load_scenario("quant_fund")
        cls.params = scenario_params(cls.scenario)
        cls.contributors = agents_to_contributors(cls.scenario)
        cls.result = calculate_once(
            cls.contributors,
            profit=cls.params["profit"],
            platform_share=cls.params["platform_share"],
            k=cls.params["k"],
            cap_multiplier=cls.params["cap_multiplier"],
            traditional_rate=cls.params["traditional_rate"],
            rho=cls.params["rho"],
        )
        cls.shares = {c["name"]: c["share_pct"] for c in cls.result["contributors"]}

    def test_share_order_zhang_gt_li_gt_chen(self):
        self.assertGreater(self.shares["张经理"], self.shares["李量化"])
        self.assertGreater(self.shares["李量化"], self.shares["陈经理"])

    def test_band_param(self):
        self.assertAlmostEqual(self.params["band"], 0.05)


class TestCreditModelScene(unittest.TestCase):
    def test_credit_share_order(self):
        scenario = load_scenario("credit_model")
        params = scenario_params(scenario)
        result = calculate_once(
            agents_to_contributors(scenario),
            profit=params["profit"],
            platform_share=params["platform_share"],
            k=params["k"],
            cap_multiplier=params["cap_multiplier"],
            traditional_rate=params["traditional_rate"],
            rho=params["rho"],
        )
        shares = {c["name"]: c["share_pct"] for c in result["contributors"]}
        self.assertGreater(shares["赵经理"], shares["王模型"])
        self.assertGreater(shares["王模型"], shares["孙经理"])


class TestSettlementBand(unittest.TestCase):
    def test_propose_stays_near_anchor_with_default_blend(self):
        formula = {"A": 0.40, "B": 0.35, "C": 0.25}
        negotiated = {"A": 0.55, "B": 0.30, "C": 0.15}
        proposed, bands = propose_from_negotiation(
            negotiated, formula, band=0.05, blend=0.45
        )
        self.assertAlmostEqual(sum(proposed.values()), 1.0, places=3)
        for name, s in proposed.items():
            # 允许归一化带来的微小越界，但应贴近带宽
            self.assertGreaterEqual(s, bands[name]["low"] - 0.02)
            self.assertLessEqual(s, bands[name]["high"] + 0.02)
            self.assertLess(abs(s - formula[name]), 0.08)


class TestNegotiation(unittest.TestCase):
    def test_mock_awaits_human(self):
        out = run_negotiation("quant_fund", mode="mock")
        self.assertTrue(out.get("awaiting_human_confirm"))
        self.assertEqual(out["status"], "pending_human_confirm")
        self.assertIn("band", out)
        for row in out["settlement"].values():
            self.assertIn("band_low", row)
            self.assertIn("proposed_share", row)

    def test_credit_mock_runs(self):
        out = run_negotiation("credit_model", mode="mock")
        self.assertGreaterEqual(len(out["rounds"]), 2)
        self.assertIn("王模型", out["settlement"])

    def test_human_confirm(self):
        nego = run_negotiation("quant_fund", mode="mock")
        proposed = {k: v["proposed_share"] for k, v in nego["settlement"].items()}
        confirmed = confirm_settlement(
            "quant_fund",
            proposed,
            negotiated={k: v["negotiated_share"] for k, v in nego["settlement"].items()},
            proposed=proposed,
        )
        self.assertIn(confirmed["status"], ("confirmed", "confirmed_override"))
        total = sum(v["final_share"] for v in confirmed["settlement"].values())
        self.assertAlmostEqual(total, 1.0, places=3)


class TestSensitivity(unittest.TestCase):
    def test_owner_share_rises_with_factor_weight(self):
        from engine.core.sensitivity import run_sensitivity

        low = run_sensitivity("quant_fund", factor_weight=0.2, sweep=False)
        high = run_sensitivity("quant_fund", factor_weight=0.8, sweep=False)
        owner = low["asset_owner"]
        low_share = next(c["share_pct"] for c in low["contributors"] if c["name"] == owner)
        high_share = next(c["share_pct"] for c in high["contributors"] if c["name"] == owner)
        self.assertGreater(high_share, low_share)

    def test_sweep_series(self):
        from engine.core.sensitivity import run_sensitivity

        out = run_sensitivity("quant_fund", factor_weight=0.45, sweep=True, sweep_points=9)
        self.assertEqual(len(out["sweep"]["factor_weight"]), 9)
        self.assertIn(out["asset_owner"], out["sweep"]["share_pct"])

    def test_rebalance_projects_extreme_target(self):
        from engine.core.sensitivity import run_rebalance_demo

        out = run_rebalance_demo(
            "quant_fund",
            target_shares={"李量化": 0.70, "张经理": 0.20, "陈经理": 0.10},
            steps=10,
            start_weight=0.2,
        )
        self.assertGreaterEqual(len(out["trajectory"]), 8)
        for name in out["formula_anchor"]:
            user_gap = abs(out["user_target"][name] - out["formula_anchor"][name])
            reason_gap = abs(out["reasonable_target"][name] - out["formula_anchor"][name])
            self.assertLessEqual(reason_gap, user_gap + 1e-6)


class TestAttribution(unittest.TestCase):
    def test_pipeline_three_weights(self):
        from engine.agentic.attribution_agent import run_attribution_pipeline

        out = run_attribution_pipeline("quant_fund", mode="mock", seed=42)
        w = out["backtest"]["weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=3)
        for k in ("strategy_alpha", "industry_policy", "luck_macro"):
            self.assertIn(k, w)
            self.assertGreaterEqual(w[k], 0.0)
        self.assertGreater(len(out["backtest"]["cells"]), 5)
        self.assertIn("李量化", out["impact_overrides"])
        self.assertIn("interpretation", out)
        self.assertEqual(len(out["plan"]["experiments"]), 3)

    def test_strategy_weight_positive(self):
        from engine.agentic.attribution_agent import run_attribution_pipeline

        out = run_attribution_pipeline("quant_fund", seed=42)
        self.assertGreater(out["backtest"]["weights"]["strategy_alpha"], 0.05)


if __name__ == "__main__":
    unittest.main()
