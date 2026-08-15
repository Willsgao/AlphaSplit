"""
因子权重敏感性分析：动态调整因子归因权重，观察分配份额变化。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


def _asset_owner_name(contributors: list[dict]) -> str:
    """复用次数最高者视为知识资产方（因子/模型开发者）。"""
    return max(contributors, key=lambda c: (c.get("reuse_count", 1), c.get("hours", 0)))["name"]


def apply_factor_weight(
    contributors: list[dict],
    factor_weight: float,
) -> list[dict]:
    """
    factor_weight ∈ [0.15, 0.85]：策略超额中归因到因子/模型的比重。
    - 资产方 Impact ↑
    - 业务/PM 方 Impact 随 (1 − w) 上升，并保留彼此相对比例
    """
    w = max(0.15, min(0.85, float(factor_weight)))
    out = deepcopy(contributors)
    owner = _asset_owner_name(out)
    others = [c for c in out if c["name"] != owner]
    base_other = sum(float(c.get("impact", 0.5)) for c in others) or 1.0

    for c in out:
        if c["name"] == owner:
            # w=0.15 → ~0.42；w=0.85 → ~0.78
            c["impact"] = round(0.35 + 0.50 * w, 4)
        else:
            rel = float(c.get("impact", 0.5)) / base_other
            # 执行侧总强度随 (1-w) 变化
            exec_mass = 0.40 + 0.50 * (1.0 - w)
            c["impact"] = round(max(0.25, min(0.90, exec_mass * rel * len(others))), 4)
    return out


def apply_overrides(
    contributors: list[dict],
    *,
    impact_overrides: dict[str, float] | None = None,
    rho: float | None = None,
) -> tuple[list[dict], float | None]:
    out = deepcopy(contributors)
    if impact_overrides:
        for c in out:
            if c["name"] in impact_overrides:
                c["impact"] = round(max(0.15, min(0.95, float(impact_overrides[c["name"]]))), 4)
    return out, rho


def run_sensitivity(
    scenario_name: str = "quant_fund",
    *,
    factor_weight: float | None = None,
    impact_overrides: dict[str, float] | None = None,
    rho: float | None = None,
    sweep: bool = True,
    sweep_points: int = 13,
) -> dict[str, Any]:
    scenario = load_scenario(scenario_name)
    params = scenario_params(scenario)
    base = agents_to_contributors(scenario)
    owner = _asset_owner_name(base)

    # 当前点
    current = deepcopy(base)
    effective_w = factor_weight
    if factor_weight is not None:
        current = apply_factor_weight(current, factor_weight)
        effective_w = max(0.15, min(0.85, float(factor_weight)))
    current, rho_override = apply_overrides(
        current, impact_overrides=impact_overrides, rho=rho
    )
    use_rho = float(rho_override if rho_override is not None else params["rho"])

    result = calculate_once(
        current,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=use_rho,
    )

    payload: dict[str, Any] = {
        "scenario": scenario["scenario"]["name"],
        "scenario_id": scenario_name,
        "asset_owner": owner,
        "factor_weight": effective_w,
        "rho": use_rho,
        "contributors": result["contributors"],
        "distributable": result["distributable"],
        "platform_profit": result["platform_profit"],
        "formula": result["formula"],
        "baseline_impacts": {c["name"]: c["impact"] for c in base},
        "note": (
            "因子权重 w 表示策略超额中归因到知识资产（因子/模型）的比重；"
            "提高 w → 资产方份额上升，业务执行方份额下降。"
        ),
    }

    if sweep:
        xs: list[float] = []
        series: dict[str, list[float]] = {c["name"]: [] for c in base}
        amounts: dict[str, list[float]] = {c["name"]: [] for c in base}
        n = max(5, min(25, int(sweep_points)))
        for i in range(n):
            w = 0.15 + (0.85 - 0.15) * i / (n - 1)
            xs.append(round(w, 4))
            point = apply_factor_weight(base, w)
            # 扫线时不叠手工 override，避免曲线失真；仅用场景 rho（或请求 rho）
            r = calculate_once(
                point,
                profit=params["profit"],
                platform_share=params["platform_share"],
                k=params["k"],
                cap_multiplier=params["cap_multiplier"],
                traditional_rate=params["traditional_rate"],
                rho=use_rho,
            )
            by_name = {c["name"]: c for c in r["contributors"]}
            for name in series:
                series[name].append(by_name[name]["share_pct"])
                amounts[name].append(by_name[name]["profit"])
        payload["sweep"] = {
            "factor_weight": xs,
            "share_pct": series,
            "amount": amounts,
        }

    return payload


def _normalize_shares(shares: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in shares.values())
    if total <= 0:
        n = len(shares) or 1
        return {k: 1.0 / n for k in shares}
    return {k: max(0.0, float(v)) / total for k, v in shares.items()}


def _shares_from_result(result: dict) -> dict[str, float]:
    return {c["name"]: c["share_pct"] / 100.0 for c in result["contributors"]}


def _mse(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    return sum((a.get(k, 0) - b.get(k, 0)) ** 2 for k in keys) / max(len(keys), 1)


def _eval_at_weight(
    base: list[dict],
    w: float,
    *,
    params: dict,
    rho: float,
) -> tuple[dict, dict[str, float]]:
    point = apply_factor_weight(base, w)
    result = calculate_once(
        point,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=rho,
    )
    return result, _shares_from_result(result)


def run_rebalance_demo(
    scenario_name: str = "quant_fund",
    *,
    target_shares: dict[str, float],
    steps: int = 24,
    start_weight: float = 0.45,
    band: float | None = None,
) -> dict[str, Any]:
    """
    自动回平衡演示：
    1) 用户给出分配目标（可偏激）
    2) 投影到公式锚点 ±band 的「合理目标」
    3) 搜索因子权重 w，使公式份额尽量贴近合理目标
    4) 输出从 start_weight → best_w 的逐步轨迹，供前端动画播放
    """
    scenario = load_scenario(scenario_name)
    params = scenario_params(scenario)
    base = agents_to_contributors(scenario)
    owner = _asset_owner_name(base)
    names = [c["name"] for c in base]
    use_band = float(band if band is not None else params.get("band", 0.05))
    rho = float(params["rho"])

    # 公式锚点（场景默认 Impact，不强制 w）
    anchor_result = calculate_once(
        base,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=rho,
    )
    formula_anchor = _shares_from_result(anchor_result)

    # 用户目标归一化
    raw_target = {n: float(target_shares.get(n, formula_anchor.get(n, 0.33))) for n in names}
    user_target = _normalize_shares(raw_target)

    # 合理目标 = 夹入锚点带宽后归一（防止目标过激）
    reasonable = {}
    for n in names:
        a = formula_anchor[n]
        reasonable[n] = min(a + use_band, max(a - use_band, user_target[n]))
    reasonable = _normalize_shares(reasonable)

    # 网格搜索最优 w
    best_w = float(start_weight)
    best_loss = float("inf")
    best_shares = dict(formula_anchor)
    best_result = anchor_result
    grid = 41
    for i in range(grid):
        w = 0.15 + (0.85 - 0.15) * i / (grid - 1)
        result, shares = _eval_at_weight(base, w, params=params, rho=rho)
        loss = _mse(shares, reasonable)
        if loss < best_loss:
            best_loss = loss
            best_w = w
            best_shares = shares
            best_result = result

    # 轨迹：权重从 start → best，份额同步变化
    n_steps = max(8, min(60, int(steps)))
    w0 = max(0.15, min(0.85, float(start_weight)))
    trajectory: list[dict[str, Any]] = []
    for i in range(n_steps + 1):
        t = i / n_steps
        # ease-out
        ease = 1 - (1 - t) ** 2
        w = w0 + (best_w - w0) * ease
        result, shares = _eval_at_weight(base, w, params=params, rho=rho)
        # 显示层：份额也向合理目标柔和靠拢（演示「回归合理」）
        display = {}
        for n in names:
            display[n] = shares[n] * (1 - 0.35 * ease) + reasonable[n] * (0.35 * ease)
        display = _normalize_shares(display)
        trajectory.append({
            "step": i,
            "progress": round(t, 4),
            "factor_weight": round(w, 4),
            "shares": {k: round(v, 4) for k, v in display.items()},
            "formula_shares_at_w": {k: round(v, 4) for k, v in shares.items()},
            "amounts": {
                k: round(v * best_result["distributable"], 2) for k, v in display.items()
            },
            "loss_to_reasonable": round(_mse(display, reasonable), 6),
        })

    return {
        "scenario": scenario["scenario"]["name"],
        "scenario_id": scenario_name,
        "asset_owner": owner,
        "band": use_band,
        "user_target": {k: round(v, 4) for k, v in user_target.items()},
        "formula_anchor": {k: round(v, 4) for k, v in formula_anchor.items()},
        "reasonable_target": {k: round(v, 4) for k, v in reasonable.items()},
        "best_factor_weight": round(best_w, 4),
        "best_shares": {k: round(v, 4) for k, v in best_shares.items()},
        "final_shares": trajectory[-1]["shares"],
        "distributable": anchor_result["distributable"],
        "trajectory": trajectory,
        "explanation": (
            "你设定的是主观分配目标；系统先将其投影到公式锚点±带宽内的「合理目标」，"
            "再自动搜索因子权重 w，使计量结果向合理配比收敛。动画展示权重与份额的动态回平衡过程。"
        ),
    }
