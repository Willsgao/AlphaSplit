"""
AlphaSplit 贡献值计算引擎（金融场景版）

四维贡献值：
  C_i = Labor_i × Impact_i × Scarcity_i × Reuse_i

  Labor    = hours × (complexity / 5)
  Impact   = 归一化后的业务影响（PnL 归因权重或 accuracy）
  Scarcity = 1 / (1 + k · pool_size)   稀缺技能溢价
  Reuse    = 1 + ρ · (reuse_count - 1) 因子被多策略复用时加成

分配：可分配池按 C_i 占比切分，并受 cap = C_i × cap_multiplier 约束。
"""
from __future__ import annotations

from typing import Any


def calc_scarcity(pool_size: int | float, k: float = 0.01) -> float:
    """S = round(1 / (1 + k * N), 4)"""
    return round(1 / (1 + k * float(pool_size)), 4)


def calc_reuse_factor(reuse_count: int, rho: float = 0.15) -> float:
    """复用加成：单场景=1.0，每多一条策略线 +ρ。"""
    n = max(1, int(reuse_count))
    return round(1.0 + rho * (n - 1), 4)


def calc_labor(hours: float, complexity: int | float) -> float:
    """劳动投入：工时 × 复杂度归一（1–5 档）。"""
    c = max(1.0, min(5.0, float(complexity)))
    return round(float(hours) * (c / 5.0), 4)


def calc_contribution(
    hours: float,
    impact: float,
    complexity: int | float,
    scarcity: float,
    reuse_count: int = 1,
    rho: float = 0.15,
) -> float:
    """
    C = Labor × Impact × Scarcity × Reuse
    impact 建议落在 (0, 1]，也兼容 accuracy 字段。
    """
    labor = calc_labor(hours, complexity)
    reuse = calc_reuse_factor(reuse_count, rho)
    imp = max(0.0, float(impact))
    return round(labor * imp * float(scarcity) * reuse, 2)


def _derive_impact(raw: dict) -> float:
    """从场景字段推导 Impact；优先显式 impact/accuracy，其次 PnL 归因。"""
    if "impact" in raw and raw["impact"] is not None:
        return float(raw["impact"])
    if "accuracy" in raw and raw["accuracy"] is not None:
        return float(raw["accuracy"])
    # 无显式字段时给中性默认，避免除零
    return 0.5


def enrich_contributor(
    raw: dict,
    *,
    k: float,
    cap_multiplier: float,
    traditional_rate: float,
    rho: float = 0.15,
) -> dict:
    pool_size = int(raw.get("pool_size", 100))
    hours = float(raw.get("hours", 0))
    complexity = raw.get("complexity", 3)
    reuse_count = int(raw.get("reuse_count", 1))
    impact = _derive_impact(raw)

    s = calc_scarcity(pool_size, k)
    contrib = calc_contribution(
        hours, impact, complexity, s, reuse_count=reuse_count, rho=rho
    )
    cap = round(contrib * cap_multiplier, 2)
    trad = hours * traditional_rate

    return {
        **raw,
        "impact": impact,
        "accuracy": raw.get("accuracy", impact),  # 兼容旧字段名
        "scarcity": s,
        "reuse_factor": calc_reuse_factor(reuse_count, rho),
        "labor": calc_labor(hours, complexity),
        "contribution": contrib,
        "cap": cap,
        "traditional_income": trad,
    }


def calculate_once(
    contributors: list[dict],
    *,
    profit: float = 3_750_000.0,
    platform_share: float = 0.25,
    k: float = 0.01,
    cap_multiplier: float = 300.0,
    traditional_rate: float = 500.0,
    rho: float = 0.15,
    apply_platform_deduction: bool = True,
) -> dict[str, Any]:
    """
    单次利润/奖金池分配。

    profit: 若 apply_platform_deduction=True，视为总额，先扣平台份额；
            否则视为已扣除后的可分配池。
    """
    enriched = [
        enrich_contributor(
            c, k=k, cap_multiplier=cap_multiplier,
            traditional_rate=traditional_rate, rho=rho,
        )
        for c in contributors
    ]
    total_contrib = sum(c["contribution"] for c in enriched)

    if apply_platform_deduction:
        distributable = round(profit * (1 - platform_share), 2)
        platform_profit = round(profit * platform_share, 2)
    else:
        distributable = round(profit, 2)
        platform_profit = 0.0

    total_traditional = sum(c["traditional_income"] for c in enriched)

    results = []
    for c in enriched:
        if total_contrib > 0:
            share_pct = round(c["contribution"] / total_contrib * 100, 1)
            raw_profit = round(c["contribution"] / total_contrib * distributable, 2)
        else:
            share_pct = 0.0
            raw_profit = 0.0
        results.append({
            "name": c["name"],
            "role": c.get("role", ""),
            "hours": c.get("hours", 0),
            "impact": c["impact"],
            "accuracy": c["accuracy"],
            "complexity": c.get("complexity", 3),
            "pool_size": c.get("pool_size", 100),
            "reuse_count": c.get("reuse_count", 1),
            "scarcity": c["scarcity"],
            "reuse_factor": c["reuse_factor"],
            "labor": c["labor"],
            "contribution": c["contribution"],
            "share_pct": share_pct,
            "profit": raw_profit,
            "cap": c["cap"],
            "traditional_income": c["traditional_income"],
        })

    return {
        "contributors": results,
        "total_contribution": round(total_contrib, 2),
        "distributable": distributable,
        "platform_profit": platform_profit,
        "total_traditional": round(total_traditional, 2),
        "formula": "C = Labor × Impact × Scarcity × Reuse",
    }


def simulate_calls(
    contributors: list[dict],
    *,
    profit_per_call: float = 3_750_000.0,
    num_calls: int = 5,
    platform_share: float = 0.25,
    k: float = 0.01,
    cap_multiplier: float = 300.0,
    traditional_rate: float = 500.0,
    rho: float = 0.15,
    apply_platform_deduction: bool = False,
) -> dict[str, Any]:
    """
    多轮持续调用模拟：超额部分进入公共池（cap 约束）。
    默认 profit_per_call 视为可分配池（已扣平台）。
    """
    enriched = [
        enrich_contributor(
            c, k=k, cap_multiplier=cap_multiplier,
            traditional_rate=traditional_rate, rho=rho,
        )
        for c in contributors
    ]
    total_contrib = sum(c["contribution"] for c in enriched)

    if apply_platform_deduction:
        distributable = round(profit_per_call * (1 - platform_share), 2)
        per_call_platform = round(profit_per_call * platform_share, 2)
    else:
        distributable = round(profit_per_call, 2)
        per_call_platform = 0.0

    cumulative = {c["name"]: 0.0 for c in enriched}
    excess = {c["name"]: 0.0 for c in enriched}
    caps = {c["name"]: c["cap"] for c in enriched}
    trad = {c["name"]: c["traditional_income"] for c in enriched}

    calls = []
    for call_idx in range(num_calls):
        items = []
        for c in enriched:
            share = (c["contribution"] / total_contrib) if total_contrib > 0 else 0.0
            raw = round(share * distributable, 2)
            available = max(0.0, caps[c["name"]] - cumulative[c["name"]])

            if raw <= available:
                credited, to_pool = raw, 0.0
            elif available > 0:
                credited, to_pool = available, round(raw - available, 2)
            else:
                credited, to_pool = 0.0, raw

            cumulative[c["name"]] = round(cumulative[c["name"]] + credited, 2)
            excess[c["name"]] = round(excess[c["name"]] + to_pool, 2)
            items.append({
                "name": c["name"],
                "raw_profit": raw,
                "credited": credited,
                "to_pool": to_pool,
            })

        calls.append({
            "call_index": call_idx + 1,
            "platform_profit": per_call_platform,
            "items": items,
        })

    meta = []
    for c in enriched:
        share_pct = (
            round(c["contribution"] / total_contrib * 100, 1)
            if total_contrib > 0 else 0.0
        )
        meta.append({
            "name": c["name"],
            "hours": c.get("hours", 0),
            "impact": c["impact"],
            "complexity": c.get("complexity", 3),
            "pool_size": c.get("pool_size", 100),
            "reuse_count": c.get("reuse_count", 1),
            "scarcity": c["scarcity"],
            "reuse_factor": c["reuse_factor"],
            "contribution": c["contribution"],
            "share_pct": share_pct,
            "cap": c["cap"],
            "traditional_income": c["traditional_income"],
        })

    return {
        "contributors_meta": meta,
        "total_contribution": round(total_contrib, 2),
        "calls": calls,
        "cumulative_by_contributor": {k: round(v, 2) for k, v in cumulative.items()},
        "excess_to_pool": {k: round(v, 2) for k, v in excess.items()},
        "cap_by_contributor": caps,
        "traditional_by_contributor": trad,
        "total_platform": round(per_call_platform * num_calls, 2),
        "total_pool": round(sum(excess.values()), 2),
        "total_worker_income": round(sum(cumulative.values()), 2),
        "total_traditional": round(sum(trad.values()), 2),
    }


def gini_coefficient(values: list[float]) -> float:
    """计算 Gini 系数；全零返回 0。"""
    arr = sorted(float(v) for v in values)
    n = len(arr)
    if n == 0:
        return 0.0
    total = sum(arr)
    if total <= 0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(arr))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def shares_from_result(result: dict) -> list[float]:
    return [float(c["share_pct"]) / 100.0 for c in result["contributors"]]
