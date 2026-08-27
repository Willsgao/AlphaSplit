"""Agent回测证据白名单和解读降级测试。"""
from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_layer.impl.evidence import build_backtest_evidence
from agent_layer.impl.interpreter import BacktestInterpreter


DEMO_PATH = Path(__file__).resolve().parents[1] / "engine" / "web" / "demo" / "backtest_demo.json"


class TestBacktestEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = json.loads(DEMO_PATH.read_text(encoding="utf-8"))

    def test_demo_result_passes_consistency_checks(self):
        evidence = build_backtest_evidence(self.demo)
        self.assertEqual(evidence["status"], "trusted")
        self.assertEqual(evidence["warnings"], [])
        self.assertEqual(len(evidence["roles"]), 5)
        self.assertGreaterEqual(len(evidence["items"]), 15)

    def test_inconsistent_excess_is_excluded_from_interpretation(self):
        payload = deepcopy(self.demo)
        payload["results"]["overview"]["excess_return"] += 0.1

        report = BacktestInterpreter().interpret(payload)

        self.assertEqual(report.trust["status"], "warning")
        self.assertIn(
            "results.overview.excess_return", report.trust["excluded_fields"]
        )
        self.assertEqual(report.headline, "回测完成")

    def test_invalid_weight_sum_is_not_used_for_ranking(self):
        payload = deepcopy(self.demo)
        positive = [
            row for row in payload["results"]["role_breakdown"]
            if row["shapley_raw"] > 0
        ]
        self.assertGreaterEqual(len(positive), 2)
        positive[0]["weight"] = 0.4
        positive[1]["weight"] = 0.4

        evidence = build_backtest_evidence(payload)

        self.assertTrue(all("weight" not in item for item in evidence["roles"]))
        self.assertTrue(
            any(w["code"] == "ROLE_WEIGHT_SUM_MISMATCH" for w in evidence["warnings"])
        )

    def test_unannounced_cap_relaxation_is_rejected(self):
        payload = deepcopy(self.demo)
        roles = payload["results"]["role_breakdown"]
        positive = next(row for row in roles if row["shapley_raw"] > 0)
        for row in roles:
            row["weight"] = 1.0 if row is positive else 0.0
        policy = payload["results"]["allocation_policy"]
        policy["configured_max_role_weight"] = 0.5
        policy["effective_max_role_weight"] = 1.0
        policy["cap_relaxed"] = False

        evidence = build_backtest_evidence(payload)

        self.assertTrue(all("weight" not in item for item in evidence["roles"]))
        self.assertTrue(
            any(w["code"] == "ROLE_WEIGHT_OUT_OF_RANGE" for w in evidence["warnings"])
        )

    def test_shapley_mismatch_is_excluded(self):
        payload = deepcopy(self.demo)
        payload["results"]["role_breakdown"][0]["shapley_raw"] += 0.1

        evidence = build_backtest_evidence(payload)

        self.assertTrue(all("shapley_raw" not in item for item in evidence["roles"]))
        self.assertTrue(
            any(w["code"] == "SHAPLEY_SUM_MISMATCH" for w in evidence["warnings"])
        )

    def test_llm_analysis_without_evidence_reference_falls_back(self):
        with (
            patch("agent_layer.impl.interpreter.llm_available", return_value=True),
            patch(
                "agent_layer.impl.interpreter.call_llm",
                return_value="组合累计收益为29.51%，建议直接采用。",
            ),
        ):
            report = BacktestInterpreter().interpret(self.demo, mode="llm")

        self.assertEqual(report.mode, "mock")
        self.assertFalse(report.llm_audit["used"])
        self.assertTrue(report.llm_audit["fallback_used"])

    def test_llm_analysis_with_known_evidence_reference_is_accepted(self):
        with (
            patch("agent_layer.impl.interpreter.llm_available", return_value=True),
            patch(
                "agent_layer.impl.interpreter.call_llm",
                return_value="组合收益来自回测证据[E001]，方案仍需人工确认。",
            ),
        ):
            report = BacktestInterpreter().interpret(self.demo, mode="llm")

        self.assertEqual(report.mode, "llm")
        self.assertTrue(report.llm_audit["used"])


if __name__ == "__main__":
    unittest.main()
