"""用户专属因子配置：登记、方向、默认值、校验与规则兜底。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


ROLE_ORDER = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]

# 与 quant_engine.ROLE_FACTORS 的 40 个因子保持同名，避免前端/Agent 传入自由文本。
ROLE_FACTOR_KEYS = {
    "行业分析师": [
        "ind_momentum_5d", "ind_momentum_10d", "ind_sma_gap_5d", "ind_sma_slope_5d",
        "ind_trend_5d", "ind_efficiency_5d", "ind_breakout_5d", "ind_range_pos_5d",
    ],
    "个股分析师": [
        "stk_reversal_5d", "stk_reversal_10d", "stk_rsi_5d", "stk_rsi_rev_5d",
        "stk_stoch_5d", "stk_drawdown_5d", "stk_lower_wick_5d", "stk_breakdown_5d",
    ],
    "策略分析师": [
        "str_skip_ret_10d", "str_gap_sum_5d", "str_intraday_5d", "str_rvol_5d",
        "str_atr_5d", "str_range_5d", "str_skew_5d", "str_kurt_5d",
    ],
    "量化分析师": [
        "quant_vol_ratio_5d", "quant_vol_z_5d", "quant_dollar_5d", "quant_pv_corr_5d",
        "quant_obv_5d", "quant_ts_close_5d", "quant_ts_vol_5d", "quant_down_vol_5d",
    ],
    "风控分析师": [
        "risk_rvol_5d", "risk_rvol_10d", "risk_down_vol_5d", "risk_atr_5d",
        "risk_range_5d", "risk_drawdown_5d", "risk_skew_5d", "risk_kurt_5d",
    ],
}

FACTOR_LABELS = {
    "ind_momentum_5d": "5日动量", "ind_momentum_10d": "10日动量", "ind_sma_gap_5d": "均线偏离",
    "ind_sma_slope_5d": "均线斜率", "ind_trend_5d": "趋势强度", "ind_efficiency_5d": "趋势效率",
    "ind_breakout_5d": "突破信号", "ind_range_pos_5d": "区间位置",
    "stk_reversal_5d": "5日反转", "stk_reversal_10d": "10日反转", "stk_rsi_5d": "RSI强度",
    "stk_rsi_rev_5d": "RSI反转", "stk_stoch_5d": "随机指标", "stk_drawdown_5d": "回撤",
    "stk_lower_wick_5d": "下影线支撑", "stk_breakdown_5d": "下轨突破",
    "str_skip_ret_10d": "跳过期间动量", "str_gap_sum_5d": "跳空溢价", "str_intraday_5d": "日内收益",
    "str_rvol_5d": "已实现波动率", "str_atr_5d": "ATR比率", "str_range_5d": "区间波动比",
    "str_skew_5d": "收益偏度", "str_kurt_5d": "收益峰度",
    "quant_vol_ratio_5d": "成交量比率", "quant_vol_z_5d": "成交量Z分数", "quant_dollar_5d": "成交额活跃度",
    "quant_pv_corr_5d": "量价相关性", "quant_obv_5d": "OBV斜率", "quant_ts_close_5d": "收盘时序排名",
    "quant_ts_vol_5d": "成交量时序排名", "quant_down_vol_5d": "下行波动率",
    "risk_rvol_5d": "5日已实现波动率", "risk_rvol_10d": "10日已实现波动率", "risk_down_vol_5d": "下行波动率",
    "risk_atr_5d": "ATR比率", "risk_range_5d": "区间波动比", "risk_drawdown_5d": "回撤",
    "risk_skew_5d": "收益偏度", "risk_kurt_5d": "收益峰度",
}

# direction=1 表示原始因子越高越符合角色目标；direction=-1 表示越低越好。
# 部分基础信号（如 reversal、breakdown）已在 quant_engine 中完成反向处理，
# 因此这里登记的是最终因子列参与综合评分时的方向。
FACTOR_DIRECTIONS = {
    "ind_momentum_5d": 1, "ind_momentum_10d": 1, "ind_sma_gap_5d": 1,
    "ind_sma_slope_5d": 1, "ind_trend_5d": 1, "ind_efficiency_5d": 1,
    "ind_breakout_5d": 1, "ind_range_pos_5d": 1,
    "stk_reversal_5d": 1, "stk_reversal_10d": 1, "stk_rsi_5d": 1,
    "stk_rsi_rev_5d": 1, "stk_stoch_5d": 1, "stk_drawdown_5d": 1,
    "stk_lower_wick_5d": 1, "stk_breakdown_5d": 1,
    "str_skip_ret_10d": 1, "str_gap_sum_5d": 1, "str_intraday_5d": 1,
    "str_rvol_5d": -1, "str_atr_5d": -1, "str_range_5d": -1,
    "str_skew_5d": 1, "str_kurt_5d": -1,
    "quant_vol_ratio_5d": 1, "quant_vol_z_5d": 1, "quant_dollar_5d": 1,
    "quant_pv_corr_5d": 1, "quant_obv_5d": 1, "quant_ts_close_5d": 1,
    "quant_ts_vol_5d": 1, "quant_down_vol_5d": -1,
    "risk_rvol_5d": -1, "risk_rvol_10d": -1, "risk_down_vol_5d": -1,
    "risk_atr_5d": -1, "risk_range_5d": -1, "risk_drawdown_5d": 1,
    "risk_skew_5d": 1, "risk_kurt_5d": -1,
}

FACTOR_CATEGORIES = {
    "ind_momentum_5d": "动量", "ind_momentum_10d": "动量", "ind_sma_gap_5d": "趋势",
    "ind_sma_slope_5d": "趋势", "ind_trend_5d": "趋势", "ind_efficiency_5d": "趋势",
    "ind_breakout_5d": "突破", "ind_range_pos_5d": "位置",
    "stk_reversal_5d": "反转", "stk_reversal_10d": "反转", "stk_rsi_5d": "强弱",
    "stk_rsi_rev_5d": "反转", "stk_stoch_5d": "强弱", "stk_drawdown_5d": "风险",
    "stk_lower_wick_5d": "形态", "stk_breakdown_5d": "反转",
    "str_skip_ret_10d": "动量", "str_gap_sum_5d": "收益", "str_intraday_5d": "收益",
    "str_rvol_5d": "风险", "str_atr_5d": "风险", "str_range_5d": "风险",
    "str_skew_5d": "分布", "str_kurt_5d": "风险",
    "quant_vol_ratio_5d": "量能", "quant_vol_z_5d": "量能", "quant_dollar_5d": "流动性",
    "quant_pv_corr_5d": "量价", "quant_obv_5d": "量价", "quant_ts_close_5d": "动量",
    "quant_ts_vol_5d": "量能", "quant_down_vol_5d": "风险",
    "risk_rvol_5d": "波动", "risk_rvol_10d": "波动", "risk_down_vol_5d": "下行风险",
    "risk_atr_5d": "波动", "risk_range_5d": "波动", "risk_drawdown_5d": "回撤",
    "risk_skew_5d": "尾部风险", "risk_kurt_5d": "尾部风险",
}

FACTOR_DESCRIPTIONS = {
    "ind_momentum_5d": "衡量行业近5日价格动量", "ind_momentum_10d": "衡量行业近10日价格动量",
    "ind_sma_gap_5d": "价格相对短期均线的偏离", "ind_sma_slope_5d": "短期均线变化斜率",
    "ind_trend_5d": "波动调整后的趋势强度", "ind_efficiency_5d": "价格沿单一方向运行的效率",
    "ind_breakout_5d": "价格突破近期高位的程度", "ind_range_pos_5d": "价格在近期区间中的位置",
    "stk_reversal_5d": "近5日弱势后的反转信号", "stk_reversal_10d": "近10日弱势后的反转信号",
    "stk_rsi_5d": "短期相对强弱水平", "stk_rsi_rev_5d": "短期超卖反转信号",
    "stk_stoch_5d": "收盘价在近期高低区间的位置", "stk_drawdown_5d": "相对近期高点的回撤，越接近0越好",
    "stk_lower_wick_5d": "下影线体现的价格支撑", "stk_breakdown_5d": "下轨跌破后的反转信号",
    "str_skip_ret_10d": "跳过最近区间后的中短期动量", "str_gap_sum_5d": "近期隔夜跳空收益",
    "str_intraday_5d": "近期日内收益", "str_rvol_5d": "近期已实现波动，低值优先",
    "str_atr_5d": "真实波幅相对价格比例，低值优先", "str_range_5d": "日内振幅比例，低值优先",
    "str_skew_5d": "收益分布偏度，较高值偏向正偏", "str_kurt_5d": "收益分布峰度，低值减少极端波动",
    "quant_vol_ratio_5d": "成交量相对均值的扩张", "quant_vol_z_5d": "成交量异常程度",
    "quant_dollar_5d": "成交额活跃程度", "quant_pv_corr_5d": "价格与成交量的相关性",
    "quant_obv_5d": "能量潮变化斜率", "quant_ts_close_5d": "收盘价时序位置",
    "quant_ts_vol_5d": "成交量时序位置", "quant_down_vol_5d": "下行波动，低值优先",
    "risk_rvol_5d": "5日已实现波动，低值优先", "risk_rvol_10d": "10日已实现波动，低值优先",
    "risk_down_vol_5d": "负收益区间波动，低值优先", "risk_atr_5d": "真实波幅比例，低值优先",
    "risk_range_5d": "日内振幅比例，低值优先", "risk_drawdown_5d": "相对近期高点回撤，越接近0越好",
    "risk_skew_5d": "收益偏度，较高值减少左尾倾向", "risk_kurt_5d": "收益峰度，低值减少极端风险",
}

FACTOR_WEIGHT_MIN = 0.0
FACTOR_WEIGHT_MAX = 0.35

DEFAULT_MODULE_PARAMS = {
    "行业分析师": {"top_industries": 4},
    "策略分析师": {
        "target_vol": 0.15, "lookback": 20, "defensive_position_cap": 0.50,
    },
    "风控分析师": {"max_single": 0.10, "max_industry": 0.30, "stop_loss_monthly": -0.05},
}

PARAM_BOUNDS = {
    "行业分析师": {"top_industries": (2, 6)},
    "策略分析师": {
        "target_vol": (0.05, 0.30), "lookback": (10, 60),
        "defensive_position_cap": (0.20, 1.00),
    },
    "风控分析师": {
        "max_single": (0.01, 0.20), "max_industry": (0.10, 0.60),
        "stop_loss_monthly": (-0.30, -0.01),
    },
}


def default_factor_config() -> dict[str, Any]:
    return {
        "config_id": "diversified_defensive_v4",
        "version": 4,
        "provenance": {"source": "default", "model": None, "confirmed_at": None},
        "roles": {
            role: {
                "enabled": True,
                "factor_weights": {key: 1.0 / len(keys) for key in keys},
                "module_params": copy.deepcopy(DEFAULT_MODULE_PARAMS.get(role, {})),
            }
            for role, keys in ROLE_FACTOR_KEYS.items()
        },
    }


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是数字") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} 必须是有限数")
    return number


def normalize_factor_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """将部分覆盖配置合并到默认配置，并校验角色、因子和模块参数。"""
    result = default_factor_config()
    if config is None:
        return result
    if not isinstance(config, dict):
        raise ValueError("factor_config 必须是对象")
    allowed_config_fields = {"config_id", "version", "provenance", "roles"}
    unknown_config_fields = sorted(set(config) - allowed_config_fields)
    if unknown_config_fields:
        raise ValueError(f"factor_config 包含不支持的字段：{unknown_config_fields}")
    incoming_roles = config.get("roles") or {}
    if not isinstance(incoming_roles, dict):
        raise ValueError("factor_config.roles 必须是对象")
    unknown_roles = sorted(set(incoming_roles) - set(ROLE_ORDER))
    if unknown_roles:
        raise ValueError(f"factor_config 包含无效角色：{unknown_roles}")

    for role, patch in incoming_roles.items():
        if not isinstance(patch, dict):
            raise ValueError(f"{role} 配置必须是对象")
        allowed_role_fields = {"enabled", "factor_weights", "module_params"}
        unknown_role_fields = sorted(set(patch) - allowed_role_fields)
        if unknown_role_fields:
            raise ValueError(f"{role} 配置包含不支持的字段：{unknown_role_fields}")
        target = result["roles"][role]
        if "enabled" in patch:
            if not isinstance(patch["enabled"], bool):
                raise ValueError(f"{role}.enabled 必须是布尔值")
            target["enabled"] = patch["enabled"]
        weights = patch.get("factor_weights") or {}
        if not isinstance(weights, dict):
            raise ValueError(f"{role}.factor_weights 必须是对象")
        unknown_factors = sorted(set(weights) - set(ROLE_FACTOR_KEYS[role]))
        if unknown_factors:
            raise ValueError(f"{role} 包含无效因子：{unknown_factors}")
        merged_weights = dict(target["factor_weights"])
        for key, value in weights.items():
            number = _finite_number(value, f"{role}.{key}")
            if number < FACTOR_WEIGHT_MIN:
                raise ValueError(f"{role}.{key} 不能为负数")
            merged_weights[key] = number
        total = sum(merged_weights.values())
        if total <= 0:
            raise ValueError(f"{role}.factor_weights 合计必须大于 0")
        normalized_weights = {key: value / total for key, value in merged_weights.items()}
        overweight = {
            key: value for key, value in normalized_weights.items()
            if value > FACTOR_WEIGHT_MAX + 1e-12
        }
        if overweight:
            labels = ", ".join(
                f"{FACTOR_LABELS.get(key, key)}={value:.2%}"
                for key, value in overweight.items()
            )
            raise ValueError(
                f"{role}.factor_weights 归一化后单因子不得超过 "
                f"{FACTOR_WEIGHT_MAX:.0%}：{labels}"
            )
        target["factor_weights"] = normalized_weights

        module_params = patch.get("module_params") or {}
        if not isinstance(module_params, dict):
            raise ValueError(f"{role}.module_params 必须是对象")
        for key, value in module_params.items():
            if key not in PARAM_BOUNDS.get(role, {}):
                raise ValueError(f"{role}.module_params 包含不支持的参数：{key}")
            number = _finite_number(value, f"{role}.module_params.{key}")
            low, high = PARAM_BOUNDS[role][key]
            if not low <= number <= high:
                raise ValueError(f"{role}.module_params.{key} 必须在 {low} 到 {high} 之间")
            target["module_params"][key] = (
                int(number) if key in {"lookback", "top_industries"} else number
            )

    result["config_id"] = str(config.get("config_id") or "custom")
    result["version"] = int(config.get("version") or 2)
    provenance = config.get("provenance")
    if provenance is not None:
        if not isinstance(provenance, dict):
            raise ValueError("factor_config.provenance 必须是对象")
        allowed_provenance = {"source", "model", "confirmed_at", "summary"}
        unknown_provenance = sorted(set(provenance) - allowed_provenance)
        if unknown_provenance:
            raise ValueError(f"factor_config.provenance 包含不支持的字段：{unknown_provenance}")
        result["provenance"] = {
            "source": str(provenance.get("source") or "unknown")[:50],
            "model": str(provenance["model"])[:100] if provenance.get("model") else None,
            "confirmed_at": str(provenance["confirmed_at"])[:50] if provenance.get("confirmed_at") else None,
            "summary": str(provenance["summary"])[:500] if provenance.get("summary") else None,
        }
    return result


def config_fingerprint(config: dict[str, Any]) -> str:
    """生成不含敏感信息的稳定配置标识。"""
    normalized = normalize_factor_config(config)
    payload = {"version": normalized["version"], "roles": normalized["roles"]}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def factor_direction(key: str) -> int:
    return FACTOR_DIRECTIONS.get(key, 1)


def factor_config_meta() -> dict[str, Any]:
    return {
        "roles": [
            {
                "role": role,
                "factors": [
                    {
                        "key": key,
                        "label": FACTOR_LABELS.get(key, key),
                        "direction": factor_direction(key),
                        "preference": "高值优先" if factor_direction(key) > 0 else "低值优先",
                        "category": FACTOR_CATEGORIES.get(key, "其他"),
                        "description": FACTOR_DESCRIPTIONS.get(key, ""),
                        "min_weight": FACTOR_WEIGHT_MIN,
                        "max_weight": FACTOR_WEIGHT_MAX,
                    }
                    for key in ROLE_FACTOR_KEYS[role]
                ],
                "module_params": DEFAULT_MODULE_PARAMS.get(role, {}),
                "param_bounds": PARAM_BOUNDS.get(role, {}),
            }
            for role in ROLE_ORDER
        ],
        "weight_policy": {
            "scope": "每个角色内部归一化为100%",
            "default": "8个因子等权",
            "max_single_factor": FACTOR_WEIGHT_MAX,
        },
        "default_config": default_factor_config(),
    }


def propose_factor_config(text: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """规则型 Agent 建议；LLM 可在同一契约上替换，数值仍由校验器约束。"""
    base = normalize_factor_config(current)
    original = copy.deepcopy(base)
    text = (text or "").strip()
    changes: list[dict[str, Any]] = []

    def adjust(role: str, factor_keys: list[str], factor_scale: float, reason: str):
        weights = base["roles"][role]["factor_weights"]
        for key in factor_keys:
            old = weights[key]
            weights[key] = old * factor_scale
            changes.append({
                "role": role,
                "factor": key,
                "label": FACTOR_LABELS.get(key, key),
                "direction": factor_direction(key),
                "old_weight": old,
                "new_weight": weights[key],
                "reason": reason,
            })

    if any(k in text for k in ("稳健", "保守", "低风险", "回撤")):
        adjust("风控分析师", ["risk_down_vol_5d", "risk_drawdown_5d"], 2.0, "用户偏好稳健，提高低下行波动与低回撤信号的重要性")
        base["roles"]["策略分析师"]["module_params"]["target_vol"] = 0.10
        changes.append({"role": "策略分析师", "parameter": "target_vol", "old_value": 0.15,
                        "new_value": 0.10, "reason": "稳健偏好降低目标波动率"})
    if any(k in text for k in ("成长", "进攻", "动量", "趋势")):
        adjust("行业分析师", ["ind_momentum_5d", "ind_momentum_10d", "ind_trend_5d", "ind_breakout_5d"], 1.8, "用户偏好成长，提升趋势与突破因子")
        adjust("量化分析师", ["quant_ts_close_5d", "quant_vol_ratio_5d"], 1.6, "用户偏好成长，提升价格动量与量能因子")
    if "风控" in text and "稳健" not in text:
        adjust("风控分析师", ["risk_down_vol_5d", "risk_drawdown_5d"], 1.5, "用户明确要求加强低风险与回撤控制信号")
    if "量化" in text and any(k in text for k in ("加强", "偏重", "重视")):
        adjust("量化分析师", ["quant_pv_corr_5d", "quant_obv_5d", "quant_dollar_5d"], 1.5, "用户要求提高量化量价信号权重")

    normalized = normalize_factor_config(base)
    for change in changes:
        role = change["role"]
        if "factor" in change:
            change["new_weight"] = normalized["roles"][role]["factor_weights"][change["factor"]]
        elif "parameter" in change:
            change["new_value"] = normalized["roles"][role]["module_params"][change["parameter"]]
    if changes:
        normalized["config_id"] = f"client_{config_fingerprint(normalized)}"
    return {
        "config": normalized,
        "changes": changes,
        "base_config": original,
        "summary": "已生成因子配置建议" if changes else "未识别到可执行的因子调整，沿用当前配置",
        "assistant_message": (
            "我已把你的偏好转换为可审查的因子调整建议，请确认后再用于回测。"
            if changes else "我还需要更明确的风险、目标或角色偏好，当前配置暂不改变。"
        ),
        "preferences": {},
        "clarification_needed": not changes,
        "clarification_question": (
            "你更希望控制回撤、增强趋势、提高量价信号，还是侧重某个投资角色？"
            if not changes else None
        ),
    }


def _validate_registry() -> None:
    keys = {key for role_keys in ROLE_FACTOR_KEYS.values() for key in role_keys}
    for name, mapping in (
        ("FACTOR_LABELS", FACTOR_LABELS),
        ("FACTOR_DIRECTIONS", FACTOR_DIRECTIONS),
        ("FACTOR_CATEGORIES", FACTOR_CATEGORIES),
        ("FACTOR_DESCRIPTIONS", FACTOR_DESCRIPTIONS),
    ):
        missing = sorted(keys - set(mapping))
        extra = sorted(set(mapping) - keys)
        if missing or extra:
            raise RuntimeError(f"{name} 与40因子登记不一致：missing={missing}, extra={extra}")


_validate_registry()
