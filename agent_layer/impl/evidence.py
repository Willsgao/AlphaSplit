"""为 Agent 解读构建只读、可追溯的回测证据白名单。"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


ALLOWED_ROLES = {
    "行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"
}
OVERVIEW_FIELDS = (
    "total_return", "benchmark_return", "excess_return", "sharpe_ratio", "max_drawdown"
)
METRIC_LABELS = {
    "total_return": "组合累计收益",
    "benchmark_return": "基准累计收益",
    "excess_return": "区间超额收益",
    "sharpe_ratio": "夏普比率",
    "max_drawdown": "最大回撤",
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_backtest_evidence(backtest: dict[str, Any]) -> dict[str, Any]:
    """校验结果内部一致性，并生成可安全传给解释 Agent 的最小证据集。"""
    warnings: list[dict[str, str]] = []
    excluded: set[str] = set()

    def warn(code: str, message: str, field: str) -> None:
        warnings.append({"code": code, "message": message, "field": field})
        excluded.add(field)

    results = backtest.get("results") if isinstance(backtest, dict) else None
    if not isinstance(results, dict):
        warn("RESULTS_MISSING", "回测结果缺少 results 对象。", "results")
        return {
            "status": "warning",
            "warnings": warnings,
            "excluded_fields": sorted(excluded),
            "overview": {},
            "roles": [],
            "items": [],
        }

    raw_overview = results.get("overview") or {}
    if not isinstance(raw_overview, dict):
        raw_overview = {}
        warn("OVERVIEW_INVALID", "overview 不是合法对象。", "results.overview")

    overview: dict[str, float] = {}
    for field in OVERVIEW_FIELDS:
        if field not in raw_overview:
            continue
        value = _finite_number(raw_overview.get(field))
        path = f"results.overview.{field}"
        if value is None:
            warn("NON_FINITE_METRIC", f"{field} 不是有限数。", path)
            continue
        overview[field] = value

    drawdown = overview.get("max_drawdown")
    if drawdown is not None and not -1.0 <= drawdown <= 0.0:
        overview.pop("max_drawdown", None)
        warn(
            "MAX_DRAWDOWN_OUT_OF_RANGE",
            "最大回撤应处于 -100% 到 0% 之间。",
            "results.overview.max_drawdown",
        )

    total = overview.get("total_return")
    benchmark = overview.get("benchmark_return")
    excess = overview.get("excess_return")
    if total is not None and benchmark is not None and excess is not None:
        expected = total - benchmark
        if not math.isclose(excess, expected, rel_tol=1e-8, abs_tol=1e-8):
            overview.pop("excess_return", None)
            warn(
                "EXCESS_RETURN_MISMATCH",
                "超额收益与组合收益减基准收益不一致。",
                "results.overview.excess_return",
            )

    raw_roles = results.get("role_breakdown") or []
    if not isinstance(raw_roles, list):
        raw_roles = []
        warn("ROLE_BREAKDOWN_INVALID", "role_breakdown 不是合法数组。", "results.role_breakdown")

    allocation_policy = results.get("allocation_policy") or {}
    allowed_role_weight = 0.5
    if isinstance(allocation_policy, dict):
        configured_cap = _finite_number(
            allocation_policy.get("configured_max_role_weight")
        )
        effective_cap = _finite_number(
            allocation_policy.get("effective_max_role_weight")
        )
        transparent_relaxation = (
            allocation_policy.get("method") == "positive_shapley_capped"
            and allocation_policy.get("negative_contribution_rewarded") is False
            and allocation_policy.get("cap_relaxed") is True
            and configured_cap is not None
            and effective_cap is not None
            and 0.0 < configured_cap <= 0.5 + 1e-12
            and configured_cap <= effective_cap <= 1.0
        )
        if transparent_relaxation:
            allowed_role_weight = effective_cap

    roles: list[dict[str, Any]] = []
    invalid_weight = False
    seen_roles: set[str] = set()
    for index, raw_role in enumerate(raw_roles):
        path = f"results.role_breakdown[{index}]"
        if not isinstance(raw_role, dict):
            warn("ROLE_ITEM_INVALID", "角色贡献项不是合法对象。", path)
            continue
        role = raw_role.get("role")
        if role not in ALLOWED_ROLES or role in seen_roles:
            warn("ROLE_NAME_INVALID", "角色名称无效或重复。", f"{path}.role")
            continue
        seen_roles.add(role)
        item: dict[str, Any] = {"role": role}
        for field in ("weight", "shapley_raw"):
            if field not in raw_role:
                continue
            value = _finite_number(raw_role.get(field))
            field_path = f"{path}.{field}"
            if value is None:
                warn("NON_FINITE_ROLE_VALUE", f"{role} 的 {field} 不是有限数。", field_path)
                continue
            if field == "weight" and not 0.0 <= value <= allowed_role_weight + 1e-12:
                invalid_weight = True
                warn(
                    "ROLE_WEIGHT_OUT_OF_RANGE",
                    f"{role} 的建议权重超出本次声明上限 {allowed_role_weight:.0%}。",
                    field_path,
                )
                continue
            item[field] = value
        roles.append(item)

    if (
        isinstance(allocation_policy, dict)
        and allocation_policy.get("negative_contribution_rewarded") is False
    ):
        for item in roles:
            weight = item.get("weight")
            shapley = item.get("shapley_raw")
            if weight is not None and shapley is not None and shapley < 0 and weight > 1e-12:
                invalid_weight = True
                warn(
                    "NEGATIVE_CONTRIBUTION_WEIGHT_MISMATCH",
                    f"{item['role']} 为负贡献，但结果声明负贡献不获得建议权重。",
                    "results.role_breakdown[].weight",
                )
                break

    weights = [item.get("weight") for item in roles]
    if invalid_weight:
        for item in roles:
            item.pop("weight", None)
    elif weights and all(value is not None for value in weights):
        if not math.isclose(sum(weights), 1.0, rel_tol=1e-8, abs_tol=1e-8):
            for item in roles:
                item.pop("weight", None)
            warn(
                "ROLE_WEIGHT_SUM_MISMATCH",
                "角色建议权重之和不等于100%。",
                "results.role_breakdown[].weight",
            )

    characteristic = raw_overview.get("characteristic_function")
    shapley_values = [item.get("shapley_raw") for item in roles]
    verified_excess = overview.get("excess_return")
    if (
        characteristic == "excess_return_vs_hs300"
        and verified_excess is not None
        and shapley_values
        and all(value is not None for value in shapley_values)
        and not math.isclose(sum(shapley_values), verified_excess, rel_tol=1e-7, abs_tol=1e-8)
    ):
        for item in roles:
            item.pop("shapley_raw", None)
        warn(
            "SHAPLEY_SUM_MISMATCH",
            "Shapley贡献之和与声明的超额收益口径不一致。",
            "results.role_breakdown[].shapley_raw",
        )

    items: list[dict[str, Any]] = []

    def add(label: str, value: Any, unit: str, source_path: str) -> None:
        items.append({
            "id": f"E{len(items) + 1:03d}",
            "label": label,
            "value": deepcopy(value),
            "unit": unit,
            "source_path": source_path,
        })

    for field in OVERVIEW_FIELDS:
        if field in overview:
            unit = "ratio" if field != "sharpe_ratio" else "number"
            add(METRIC_LABELS[field], overview[field], unit, f"results.overview.{field}")
    for index, item in enumerate(roles):
        if "shapley_raw" in item:
            add(
                f"{item['role']} Shapley贡献",
                item["shapley_raw"],
                "ratio",
                f"results.role_breakdown[{index}].shapley_raw",
            )
        if "weight" in item:
            add(
                f"{item['role']} 新池建议权重",
                item["weight"],
                "ratio",
                f"results.role_breakdown[{index}].weight",
            )

    return {
        "status": "trusted" if not warnings else "warning",
        "warnings": warnings,
        "excluded_fields": sorted(excluded),
        "overview": overview,
        "roles": roles,
        "items": items,
    }
