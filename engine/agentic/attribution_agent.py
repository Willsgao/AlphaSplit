"""
Agent 回测规划与归因解读。

默认 Mock：稳定输出实验矩阵与结论；可选 LLM 生成解读文案。
"""
from __future__ import annotations

from typing import Any, Optional

from engine.agentic.agents import call_llm
from engine.core.backtest import (
    CATEGORIES,
    PERIODS,
    map_weights_to_impact_overrides,
    run_backtest_matrix,
)
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


def build_default_plan() -> dict[str, Any]:
    return {
        "goal": "区分超额来源：量化策略 Alpha vs 行业/政策 vs 偶然宏观",
        "periods": PERIODS,
        "categories": CATEGORIES,
        "experiments": [
            {
                "id": "cross_regime",
                "name": "跨市场状态稳健性",
                "desc": "在顺风/冲击/逆风/修复四段上重复回测，观察 Alpha 是否稳定",
            },
            {
                "id": "cross_category",
                "name": "跨品类对照",
                "desc": "成长/价值/防御三类上对比，识别是否主要吃行业与政策beta",
            },
            {
                "id": "residual_check",
                "name": "剥离市场与行业后的残差",
                "desc": "控制市场与行业暴露后，残差收益视为策略贡献候选",
            },
        ],
        "decision_rule": (
            "Alpha 跨期跨品类稳定 → 提高 strategy_alpha；"
            "与行业贡献同步抬升 → 提高 industry_policy；"
            "冲击期噪声与跨切片波动大 → 提高 luck_macro"
        ),
    }


def _mock_interpretation(result: dict[str, Any]) -> str:
    w = result["weights"]
    d = result["diagnostics"]
    lines = [
        "【Agent 归因结论】基于规划的多时段×多品类对照回测：",
        f"1) 策略 Alpha 权重 {w['strategy_alpha']:.1%}："
        f"年化残差均值 {d['mean_alpha_ann']:.2%}，稳定性 {d['stability']:.2f}。"
        + ("跨切片较稳健，策略本身具备可计量贡献。" if d["stability"] >= 0.55
           else "跨切片波动偏大，策略贡献需保守估计。"),
        f"2) 行业/政策 权重 {w['industry_policy']:.1%}："
        f"行业贡献年化约 {d['mean_industry_contrib_ann']:.2%}。"
        + ("超额中有明显赛道/政策同步成分。" if w["industry_policy"] >= 0.28
           else "行业选择解释力有限。"),
        f"3) 偶然/宏观 权重 {w['luck_macro']:.1%}："
        f"平均噪声份额 {d['mean_noise_share']:.1%}。"
        + ("冲击期与残差不稳提示运气/宏观干扰不可忽视。" if w["luck_macro"] >= 0.25
           else "偶然因素相对可控。"),
        "建议：将上述三因素权重写入分配 Impact 锚点；协商与人工确认仍保留最终责任。",
    ]
    # 补充分时期/品类要点
    best_p = max(result["alpha_by_period"], key=result["alpha_by_period"].get)
    worst_p = min(result["alpha_by_period"], key=result["alpha_by_period"].get)
    best_c = max(result["alpha_by_category"], key=result["alpha_by_category"].get)
    lines.append(
        f"切片观察：Alpha 最强时段「{best_p}」，最弱「{worst_p}」；"
        f"品类上「{best_c}」更强——用于判断是选对赛道还是策略普适。"
    )
    return "\n".join(lines)


def _llm_interpretation(plan: dict, result: dict) -> Optional[str]:
    try:
        prompt = (
            "你是量化归因助手。根据下列回测诊断，用中文写不超过180字结论，"
            "明确策略Alpha/行业政策/偶然宏观三者谁主谁次，并给分配建议。\n"
            f"计划: {plan['goal']}\n"
            f"权重: {result['weights']}\n"
            f"诊断: {result['diagnostics']}\n"
            f"分时段Alpha: {result['alpha_by_period']}\n"
            f"分品类Alpha: {result['alpha_by_category']}\n"
        )
        return call_llm([
            {"role": "system", "content": "你是严谨的金融归因分析Agent，避免过度承诺因果。"},
            {"role": "user", "content": prompt},
        ])
    except Exception:
        return None


def run_attribution_pipeline(
    scenario_name: str = "quant_fund",
    *,
    mode: str = "mock",
    seed: int = 42,
) -> dict[str, Any]:
    plan = build_default_plan()
    backtest = run_backtest_matrix(plan, seed=seed)
    interpretation = _mock_interpretation(backtest)
    if mode == "llm":
        llm_text = _llm_interpretation(plan, backtest)
        if llm_text:
            interpretation = llm_text

    scenario = load_scenario(scenario_name)
    params = scenario_params(scenario)
    contributors = agents_to_contributors(scenario)
    overrides = map_weights_to_impact_overrides(contributors, backtest["weights"])

    # 应用 override 后的锚点分配
    adjusted = []
    for c in contributors:
        row = dict(c)
        if c["name"] in overrides:
            row["impact"] = overrides[c["name"]]
        adjusted.append(row)

    baseline = calculate_once(
        contributors,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
    )
    attributed = calculate_once(
        adjusted,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
    )

    return {
        "scenario_id": scenario_name,
        "scenario": scenario["scenario"]["name"],
        "mode": mode if mode == "llm" else "mock",
        "plan": plan,
        "backtest": backtest,
        "interpretation": interpretation,
        "impact_overrides": overrides,
        "baseline_allocation": {
            c["name"]: {"share_pct": c["share_pct"], "profit": c["profit"], "impact": c["impact"]}
            for c in baseline["contributors"]
        },
        "attributed_allocation": {
            c["name"]: {"share_pct": c["share_pct"], "profit": c["profit"], "impact": c["impact"]}
            for c in attributed["contributors"]
        },
        "distributable": attributed["distributable"],
        "framework": "Agent规划回测 → 三因素归因 → 分配锚点",
    }
