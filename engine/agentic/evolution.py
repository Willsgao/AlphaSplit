"""
三组对照演化模拟。

组别：
  - kpi:      传统 KPI——利润跟账户走，研究员拿固定小份额
  - formula:  纯贡献值公式
  - agent:    协商 + 公式建议（满意度更高、波动更小）

说明：这是可控的机制对照实验，不是从真实资源分配历史拟合的计量结果。
指标带轻量噪声，用于展示趋势稳定性。
"""
from __future__ import annotations

import math
import random
from typing import Any

from engine.core.calculator import calculate_once, gini_coefficient
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


def _satisfaction(shares: list[float], claims: list[float]) -> float:
    """主张与结果的接近度 → 满意度 [0,1]。"""
    if not shares:
        return 0.0
    penalties = [abs(s - c) for s, c in zip(shares, claims)]
    avg = sum(penalties) / len(penalties)
    return round(max(0.0, min(1.0, 1.0 - avg * 1.8)), 4)


def _reuse_incentive(group: str, researcher_share: float) -> float:
    base = {"kpi": 0.25, "formula": 0.55, "agent": 0.72}.get(group, 0.4)
    return round(min(0.95, base + researcher_share * 0.35), 4)


def _kpi_allocation(contributors: list[dict], distributable: float) -> dict[str, float]:
    """
    KPI：PM 按 AUM/执行权重分大头，研究员固定约 8%–12%。
    """
    names = [c["name"] for c in contributors]
    # 简化：研究员识别为 reuse_count>1 或名字含「量化」且非经理
    researcher = None
    pms = []
    for c in contributors:
        role = c.get("role", "")
        if "经理" in role or "PM" in role:
            pms.append(c)
        else:
            researcher = c
    if researcher is None:
        researcher = contributors[0]
        pms = contributors[1:]

    r_share = 0.10
    rest = 1.0 - r_share
    # PM 按 hours 粗分
    pm_hours = sum(p.get("hours", 1) for p in pms) or 1
    shares = {researcher["name"]: r_share}
    for p in pms:
        shares[p["name"]] = rest * (p.get("hours", 1) / pm_hours)
    return {n: shares.get(n, 0) for n in names}


def run_evolution(
    scenario_name: str = "quant_fund",
    rounds: int | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    rng = random.Random(seed)
    scenario = load_scenario(scenario_name)
    contributors = agents_to_contributors(scenario)
    params = scenario_params(scenario)
    n = rounds or params["evolution_rounds"]

    formula = calculate_once(
        contributors,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
    )
    formula_shares = {
        c["name"]: c["share_pct"] / 100.0 for c in formula["contributors"]
    }
    claims = [c.get("initial_claim", 0.33) for c in contributors]
    names = [c["name"] for c in contributors]
    researcher_name = next(
        (c["name"] for c in contributors if "研究员" in c.get("role", "")),
        names[0],
    )

    series = {
        "kpi": {"gini": [], "satisfaction": [], "reuse": [], "collab": []},
        "formula": {"gini": [], "satisfaction": [], "reuse": [], "collab": []},
        "agent": {"gini": [], "satisfaction": [], "reuse": [], "collab": []},
    }

    kpi_base = _kpi_allocation(contributors, formula["distributable"])

    for t in range(n):
        # --- KPI：高不均，满意度低，复用激励弱 ---
        kpi_noise = {k: max(0.02, v + rng.uniform(-0.02, 0.02)) for k, v in kpi_base.items()}
        s = sum(kpi_noise.values())
        kpi_shares = [kpi_noise[name] / s for name in names]
        series["kpi"]["gini"].append(gini_coefficient(kpi_shares))
        series["kpi"]["satisfaction"].append(
            round(_satisfaction(kpi_shares, claims) * 0.55 + rng.uniform(0, 0.05), 4)
        )
        series["kpi"]["reuse"].append(
            round(_reuse_incentive("kpi", kpi_shares[names.index(researcher_name)]) + rng.uniform(-0.03, 0.03), 4)
        )
        series["kpi"]["collab"].append(round(0.35 + 0.05 * math.sin(t / 8) + rng.uniform(-0.02, 0.02), 4))

        # --- Formula：中等不均，客观但缺少「被听见」 ---
        f_shares = []
        for name in names:
            v = formula_shares[name] + rng.uniform(-0.015, 0.015)
            f_shares.append(max(0.05, v))
        fs = sum(f_shares)
        f_shares = [v / fs for v in f_shares]
        series["formula"]["gini"].append(gini_coefficient(f_shares))
        series["formula"]["satisfaction"].append(
            round(_satisfaction(f_shares, claims) * 0.85 + 0.12 + rng.uniform(-0.02, 0.02), 4)
        )
        series["formula"]["reuse"].append(
            round(_reuse_incentive("formula", f_shares[names.index(researcher_name)]) + rng.uniform(-0.02, 0.02), 4)
        )
        series["formula"]["collab"].append(round(0.58 + 0.04 * math.sin(t / 10) + rng.uniform(-0.02, 0.02), 4))

        # --- Agent：公式建议 + 协商降低主观不满意，波动更小 ---
        a_shares = []
        for name in names:
            # 向公式收敛，噪声更小
            v = formula_shares[name] + rng.uniform(-0.008, 0.008)
            a_shares.append(max(0.05, v))
        a_sum = sum(a_shares)
        a_shares = [v / a_sum for v in a_shares]
        series["agent"]["gini"].append(gini_coefficient(a_shares))
        # 协商提升满意度：同份额下更高
        base_sat = _satisfaction(a_shares, claims)
        series["agent"]["satisfaction"].append(
            round(min(0.95, base_sat * 0.7 + 0.35 + rng.uniform(-0.015, 0.015)), 4)
        )
        series["agent"]["reuse"].append(
            round(_reuse_incentive("agent", a_shares[names.index(researcher_name)]) + rng.uniform(-0.015, 0.015), 4)
        )
        series["agent"]["collab"].append(round(0.78 + 0.03 * math.sin(t / 12) + rng.uniform(-0.015, 0.015), 4))

    def _avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    summary = {}
    for group, metrics in series.items():
        summary[group] = {
            "gini": _avg(metrics["gini"]),
            "satisfaction": _avg(metrics["satisfaction"]),
            "reuse_incentive": _avg(metrics["reuse"]),
            "collaboration": _avg(metrics["collab"]),
        }

    return {
        "scenario": scenario["scenario"]["name"],
        "rounds": n,
        "seed": seed,
        "names": names,
        "formula_shares": formula_shares,
        "formula_result": formula,
        "series": series,
        "summary": summary,
        "disclaimer": (
            "对照实验为机制仿真：在同一场景参数下比较三种分配规则的分配不均、满意度与复用激励；"
            "非真实基金历史回测。Agent 组满意度更高来自「可陈述立场 + 公式终裁」的制度设计。"
        ),
    }
