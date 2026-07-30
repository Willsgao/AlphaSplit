"""agentic / scenario 层基础测试。"""
from __future__ import annotations

import unittest

from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import run_negotiation
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


class TestQuantFundCalibration(unittest.TestCase):
    """公式终值须满足：张 > 李 > 陈，且接近 38/34/28。"""

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

    def test_explicit_impact_scores(self):
        by_name = {c["name"]: c for c in self.contributors}
        self.assertAlmostEqual(by_name["张经理"]["impact"], 0.78, places=3)
        self.assertAlmostEqual(by_name["李量化"]["impact"], 0.55, places=3)
        self.assertAlmostEqual(by_name["陈经理"]["impact"], 0.55, places=3)

    def test_share_order_zhang_gt_li_gt_chen(self):
        self.assertGreater(self.shares["张经理"], self.shares["李量化"])
        self.assertGreater(self.shares["李量化"], self.shares["陈经理"])

    def test_share_targets_near_38_34_28(self):
        self.assertAlmostEqual(self.shares["张经理"], 38.0, delta=2.5)
        self.assertAlmostEqual(self.shares["李量化"], 34.0, delta=2.5)
        self.assertAlmostEqual(self.shares["陈经理"], 28.0, delta=2.5)

    def test_chen_factor_reliance_higher_than_zhang(self):
        """叙事：市场中性更依赖因子。"""
        zhang = next(a for a in self.scenario["agents"] if a["name"] == "张经理")
        chen = next(a for a in self.scenario["agents"] if a["name"] == "陈经理")
        z_rel = zhang["contributions"][0]["metrics"]["factor_reliance"]
        c_rel = chen["contributions"][0]["metrics"]["factor_reliance"]
        self.assertGreater(c_rel, z_rel)


class TestNegotiation(unittest.TestCase):
    def test_mock_negotiation_settlement_order(self):
        out = run_negotiation("quant_fund", mode="mock")
        self.assertEqual(out["mode"], "mock")
        self.assertGreaterEqual(len(out["rounds"]), 3)
        final = {k: v["final_share"] for k, v in out["settlement"].items()}
        self.assertGreater(final["张经理"], final["李量化"])
        self.assertGreater(final["李量化"], final["陈经理"])

    def test_mock_last_round_claims_align_with_formula(self):
        out = run_negotiation("quant_fund", mode="mock")
        last = out["rounds"][-1]
        claims = last["claims"]
        # 末轮意向：张 > 李 > 陈，并向公式收敛
        self.assertGreater(claims["张经理"], claims["李量化"])
        self.assertGreater(claims["李量化"], claims["陈经理"])
        for name, s in out["settlement"].items():
            self.assertLess(abs(claims[name] - s["final_share"]), 0.08)

    def test_arbiter_statement_present(self):
        out = run_negotiation("quant_fund", mode="mock")
        self.assertIn("公式", out["arbiter_statement"])
        self.assertIn("张经理", out["arbiter_statement"])


class TestEvolution(unittest.TestCase):
    def test_evolution_summary_keys(self):
        out = run_evolution("quant_fund", rounds=20, seed=1)
        for g in ("kpi", "formula", "agent"):
            self.assertIn(g, out["summary"])
            self.assertIn("gini", out["summary"][g])
            self.assertIn("satisfaction", out["summary"][g])
        # Agent 组满意度应不低于公式组（制度设计）
        self.assertGreaterEqual(
            out["summary"]["agent"]["satisfaction"],
            out["summary"]["formula"]["satisfaction"] - 0.02,
        )
        self.assertIn("disclaimer", out)


if __name__ == "__main__":
    unittest.main()
