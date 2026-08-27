"""用户专属因子配置的校验、合并和规则 Agent 建议测试。"""
from __future__ import annotations

import unittest

from backtest.factor_config import (
    FACTOR_DIRECTIONS,
    FACTOR_WEIGHT_MAX,
    ROLE_FACTOR_KEYS,
    default_factor_config,
    normalize_factor_config,
    propose_factor_config,
)


class TestFactorConfig(unittest.TestCase):
    def test_default_has_five_roles_and_forty_factors(self):
        config = default_factor_config()
        self.assertEqual(set(config["roles"]), set(ROLE_FACTOR_KEYS))
        self.assertEqual(sum(len(item) for item in ROLE_FACTOR_KEYS.values()), 40)
        for role, keys in ROLE_FACTOR_KEYS.items():
            self.assertAlmostEqual(sum(config["roles"][role]["factor_weights"].values()), 1.0)
            self.assertEqual(set(config["roles"][role]["factor_weights"]), set(keys))
        self.assertEqual(
            config["roles"]["行业分析师"]["module_params"]["top_industries"], 4
        )
        self.assertEqual(
            config["roles"]["风控分析师"]["module_params"]["max_single"], 0.10
        )
        self.assertEqual(
            config["roles"]["风控分析师"]["module_params"]["max_industry"], 0.30
        )
        self.assertEqual(
            config["roles"]["策略分析师"]["module_params"]["defensive_position_cap"],
            0.50,
        )

    def test_partial_override_preserves_other_factors(self):
        config = normalize_factor_config({
            "roles": {
                "风控分析师": {
                    "factor_weights": {"risk_drawdown_5d": 0.30},
                }
            }
        })
        weights = config["roles"]["风控分析师"]["factor_weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertGreater(weights["risk_drawdown_5d"], weights["risk_rvol_5d"])
        self.assertEqual(config["roles"]["策略分析师"]["module_params"]["target_vol"], 0.15)

    def test_invalid_factor_and_out_of_range_parameter_rejected(self):
        with self.assertRaises(ValueError):
            normalize_factor_config({"roles": {"风控分析师": {"factor_weights": {"unknown": 1}}}})
        with self.assertRaises(ValueError):
            normalize_factor_config({"roles": {"策略分析师": {"module_params": {"target_vol": 0.01}}}})
        with self.assertRaisesRegex(ValueError, "不支持的字段"):
            normalize_factor_config({"secret": "must-not-pass"})
        with self.assertRaisesRegex(ValueError, "不支持的字段"):
            normalize_factor_config({"roles": {"风控分析师": {"free_form": True}}})

    def test_normalized_single_factor_weight_is_capped(self):
        with self.assertRaisesRegex(ValueError, "单因子不得超过"):
            normalize_factor_config({
                "roles": {
                    "风控分析师": {
                        "factor_weights": {"risk_drawdown_5d": 100.0},
                    }
                }
            })

        config = normalize_factor_config({
            "roles": {
                "风控分析师": {
                    "factor_weights": {"risk_drawdown_5d": FACTOR_WEIGHT_MAX},
                }
            }
        })
        self.assertLessEqual(
            max(config["roles"]["风控分析师"]["factor_weights"].values()),
            FACTOR_WEIGHT_MAX,
        )

    def test_risk_and_volatility_factors_have_low_value_direction(self):
        low_value_factors = {
            "str_rvol_5d", "str_atr_5d", "str_range_5d", "str_kurt_5d",
            "quant_down_vol_5d", "risk_rvol_5d", "risk_rvol_10d",
            "risk_down_vol_5d", "risk_atr_5d", "risk_range_5d", "risk_kurt_5d",
        }
        self.assertTrue(low_value_factors)
        self.assertTrue(all(FACTOR_DIRECTIONS[key] == -1 for key in low_value_factors))

    def test_rule_agent_returns_stable_robustness_changes(self):
        proposal = propose_factor_config("我偏稳健，希望加强风控并降低波动")
        self.assertTrue(proposal["changes"])
        risk_changes = {
            item["factor"]: item for item in proposal["changes"] if item.get("factor")
        }
        self.assertEqual(risk_changes["risk_down_vol_5d"]["direction"], -1)
        # drawdown 原始值为负数，越接近0代表回撤越小，因此高值优先。
        self.assertEqual(risk_changes["risk_drawdown_5d"]["direction"], 1)
        self.assertEqual(proposal["config"]["roles"]["策略分析师"]["module_params"]["target_vol"], 0.10)
        self.assertAlmostEqual(
            sum(proposal["config"]["roles"]["风控分析师"]["factor_weights"].values()), 1.0
        )


if __name__ == "__main__":
    unittest.main()
