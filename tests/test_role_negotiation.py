"""五角色协商测试。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.agentic.role_negotiation import (
    ROLE_ORDER,
    build_dual_track_weights,
    confirm_role_settlement,
    run_role_negotiation,
)


class TestRoleNegotiation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        demo = Path(__file__).resolve().parents[1] / "engine" / "web" / "demo" / "backtest_demo.json"
        cls.backtest = json.loads(demo.read_text(encoding="utf-8"))

    def test_five_roles_in_output(self):
        out = run_role_negotiation(self.backtest)
        self.assertEqual(out["role_model"], "five_roles")
        self.assertEqual(len(out["agents"]), 5)
        self.assertEqual(set(out["formula_shares"].keys()), set(ROLE_ORDER))
        self.assertEqual(len(out["rounds"][0]["utterances"]), 5)

    def test_dual_track(self):
        base, new_pool, composite = build_dual_track_weights(self.backtest)
        self.assertAlmostEqual(sum(base.values()), 1.0, places=3)
        self.assertAlmostEqual(sum(composite.values()), 1.0, places=3)
        self.assertGreater(composite["行业分析师"], base["行业分析师"])

    def test_confirm(self):
        nego = run_role_negotiation(self.backtest)
        shares = dict(nego["proposed_shares"])
        result = confirm_role_settlement(shares, nego)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["role_model"], "five_roles")


if __name__ == "__main__":
    unittest.main()
