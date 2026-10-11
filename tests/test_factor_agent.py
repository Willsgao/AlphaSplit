"""DeepSeek 因子 Agent 的结构化输出、校验与降级测试。"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agent_layer.impl.factor_agent import propose_with_factor_agent
from backtest.factor_config import default_factor_config


LLM_STATUS = {"available": True, "provider": "deepseek", "model": "deepseek-chat"}


def _model_response(**overrides):
    payload = {
        "summary": "稳健型客户方案",
        "assistant_message": "已提高回撤控制信号的重要性。",
        "preferences": {"risk_level": "稳健"},
        "clarification_needed": False,
        "clarification_question": None,
        "factor_changes": [
            {
                "role": "风控分析师",
                "factor": "risk_drawdown_5d",
                "new_weight": 0.20,
                "reason": "更重视低回撤信号",
            }
        ],
        "module_changes": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class TestFactorAdjustmentAgent(unittest.TestCase):
    def _run_llm(self, raw: str):
        with (
            patch("agent_layer.impl.factor_agent.llm_available", return_value=True),
            patch("agent_layer.impl.factor_agent.llm_status", return_value=LLM_STATUS),
            patch("agent_layer.impl.factor_agent.call_llm", return_value=raw),
        ):
            return propose_with_factor_agent(
                text="希望更稳健",
                current_config=default_factor_config(),
                mode="llm",
            )

    def test_valid_deepseek_json_generates_bounded_proposal(self):
        result = self._run_llm(_model_response())

        self.assertEqual(result["source"], "deepseek")
        self.assertEqual(result["mode"], "llm")
        self.assertIsNone(result["fallback_reason"])
        self.assertTrue(result["config"]["config_id"].startswith("client_"))
        weights = result["config"]["roles"]["风控分析师"]["factor_weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertLessEqual(max(weights.values()), 0.35)
        self.assertTrue(result["requires_confirmation"])
        self.assertTrue(result["audit"]["audit_id"].startswith("fa_"))
        self.assertEqual(result["audit"]["change_count"], 1)
        self.assertFalse(result["audit"]["input_summary"]["raw_prompt_stored"])

    def test_unknown_factor_falls_back_without_applying_model_output(self):
        raw = _model_response(factor_changes=[{
            "role": "风控分析师",
            "factor": "invented_factor",
            "new_weight": 0.20,
            "reason": "非法因子",
        }])
        result = self._run_llm(raw)

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("FactorAgentResponseError", result["fallback_reason"])
        self.assertNotIn(
            "invented_factor",
            result["config"]["roles"]["风控分析师"]["factor_weights"],
        )

    def test_malformed_json_falls_back(self):
        result = self._run_llm("not-json")

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("JSONDecodeError", result["fallback_reason"])

    def test_missing_api_key_uses_explicit_rule_fallback(self):
        with (
            patch("agent_layer.impl.factor_agent.llm_available", return_value=False),
            patch(
                "agent_layer.impl.factor_agent.llm_status",
                return_value={"available": False, "provider": "none", "model": "deepseek-chat"},
            ),
        ):
            result = propose_with_factor_agent(text="偏稳健", current_config=None, mode="llm")

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("DEEPSEEK_API_KEY", result["fallback_reason"])
        with (
            patch("agent_layer.impl.factor_agent.llm_available", return_value=False),
            patch(
                "agent_layer.impl.factor_agent.llm_status",
                return_value={"available": False, "provider": "none", "model": "deepseek-chat"},
            ),
        ):
            result = propose_with_factor_agent(
                text="我计划中长期持有，希望优先控制最大回撤。",
                current_config=default_factor_config(),
                quick_preferences={
                    "risk_level": "稳健",
                    "objectives": ["控制回撤"],
                    "focus_roles": ["风控分析师"],
                },
                mode="llm",
            )

        self.assertEqual(result["source"], "agent_cache")
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["cache"]["id"], "steady_drawdown_control")
        self.assertFalse(result["cache"]["live_llm_used"])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["audit"]["stages"][1]["status"], "cached")
        self.assertLessEqual(
            max(result["config"]["roles"]["风控分析师"]["factor_weights"].values()),
            0.35,
        )

    def test_timeout_uses_explicit_rule_fallback(self):
        with (
            patch("agent_layer.impl.factor_agent.llm_available", return_value=True),
            patch("agent_layer.impl.factor_agent.llm_status", return_value=LLM_STATUS),
            patch("agent_layer.impl.factor_agent.call_llm", side_effect=TimeoutError("timed out")),
        ):
            result = propose_with_factor_agent(text="偏稳健", current_config=None, mode="llm")

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("TimeoutError", result["fallback_reason"])

    def test_clarification_does_not_change_configuration(self):
        raw = _model_response(
            clarification_needed=True,
            clarification_question="你更关注回撤还是收益弹性？",
            factor_changes=[],
        )
        result = self._run_llm(raw)

        self.assertEqual(result["source"], "deepseek")
        self.assertTrue(result["clarification_needed"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["config"], result["base_config"])
        self.assertFalse(result["requires_confirmation"])

    def test_out_of_range_module_parameter_falls_back(self):
        raw = _model_response(
            factor_changes=[],
            module_changes=[{
                "role": "策略分析师",
                "parameter": "target_vol",
                "new_value": 0.90,
                "reason": "越界参数",
            }],
        )
        result = self._run_llm(raw)

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("必须在", result["fallback_reason"])

    def test_safe_provenance_is_preserved_and_unknown_field_is_rejected(self):
        current = default_factor_config()
        current["provenance"] = {
            "source": "deepseek",
            "model": "deepseek-chat",
            "confirmed_at": "2026-08-26T10:00:00+08:00",
            "summary": "已确认配置",
        }
        with (
            patch("agent_layer.impl.factor_agent.llm_available", return_value=True),
            patch("agent_layer.impl.factor_agent.llm_status", return_value=LLM_STATUS),
            patch("agent_layer.impl.factor_agent.call_llm", return_value=_model_response()),
        ):
            result = propose_with_factor_agent(
                text="继续降低风险", current_config=current, mode="llm"
            )
        self.assertEqual(result["base_config"]["provenance"]["source"], "deepseek")

        current["provenance"]["api_key"] = "must-not-pass"
        with self.assertRaisesRegex(ValueError, "不支持的字段"):
            propose_with_factor_agent(text="调整", current_config=current, mode="mock")


if __name__ == "__main__":
    unittest.main()
