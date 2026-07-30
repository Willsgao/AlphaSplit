"""从场景 JSON 构建贡献者输入与公式侧参数。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = ROOT / "data" / "scenarios"


def load_scenario(name: str = "quant_fund") -> dict[str, Any]:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"场景不存在: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _sum_hours(agent: dict) -> float:
    return float(sum(c.get("hours", 0) for c in agent.get("contributions", [])))


def _max_complexity(agent: dict) -> int:
    vals = [int(c.get("complexity", 3)) for c in agent.get("contributions", [])]
    return max(vals) if vals else 3


def _metrics_block(contrib: dict) -> dict:
    """兼容旧字段 impact(dict) 与新字段 metrics。"""
    if isinstance(contrib.get("metrics"), dict):
        return contrib["metrics"]
    raw = contrib.get("impact")
    return raw if isinstance(raw, dict) else {}


def _reuse_count(agent: dict, scenario: dict) -> int:
    if "reuse_count" in agent and agent["reuse_count"] is not None:
        return max(1, int(agent["reuse_count"]))
    for c in agent.get("contributions", []):
        metrics = _metrics_block(c)
        strategies = [k for k in metrics if str(k).startswith("策略_")]
        if strategies:
            return len(strategies)
    reused = scenario.get("factor", {}).get("reused_by") or []
    if agent.get("name") == scenario.get("factor", {}).get("developer"):
        return max(1, len(reused))
    return 1


def _impact_score(agent: dict) -> float:
    """
    Impact 优先级：
      1) agent.impact_score（场景显式标定，Demo 可审计）
      2) 自动推导（无显式字段时的回退）
    """
    if agent.get("impact_score") is not None:
        return round(float(agent["impact_score"]), 4)

    role = (agent.get("role_en") or agent.get("role") or "").lower()
    for c in agent.get("contributions", []):
        if c.get("impact_score") is not None:
            return round(float(c["impact_score"]), 4)
        metrics = _metrics_block(c)
        if "factor_reliance" in metrics:
            reliance = float(metrics["factor_reliance"])
            exec_score = max(0.25, min(0.9, 1.0 - reliance))
            aum = float(metrics.get("aum", 0) or 0)
            aum_boost = min(0.12, aum / 5_000_000_000 * 0.12) if aum else 0.0
            return round(min(0.92, exec_score + aum_boost), 4)
        pcts = [
            float(v.get("contribution_pct", 0))
            for k, v in metrics.items()
            if isinstance(v, dict) and "contribution_pct" in v
        ]
        if pcts:
            mean_pct = sum(pcts) / len(pcts)
            return round(max(0.4, min(0.8, 0.22 + mean_pct)), 4)

    if "researcher" in role or "研究员" in (agent.get("role") or ""):
        return 0.55
    return 0.50


def _pool_size(agent: dict) -> int:
    if agent.get("pool_size") is not None:
        return int(agent["pool_size"])
    role = agent.get("role") or ""
    if "研究员" in role or "Researcher" in (agent.get("role_en") or ""):
        return 55
    if "市场中性" in role or "Market Neutral" in (agent.get("role_en") or ""):
        return 70
    if "指数增强" in role or "Index" in (agent.get("role_en") or ""):
        return 65
    return 100


def agents_to_contributors(scenario: dict) -> list[dict]:
    """把协商 Agent 转成 calculator 输入。"""
    out = []
    for agent in scenario.get("agents", []):
        out.append({
            "name": agent["name"],
            "role": agent.get("role", ""),
            "hours": _sum_hours(agent),
            "complexity": _max_complexity(agent),
            "impact": _impact_score(agent),
            "pool_size": _pool_size(agent),
            "reuse_count": _reuse_count(agent, scenario),
            "initial_claim": agent.get("initial_claim", 0.33),
            "impact_note": agent.get("impact_note", ""),
        })
    return out


def scenario_params(scenario: dict) -> dict[str, Any]:
    p = scenario.get("simulation_params") or {}
    fund = scenario.get("fund") or {}
    bonus = float(fund.get("total_bonus_pool", 5_000_000))
    platform_share = float(p.get("platform_share", fund.get("platform_share", 0.25)))
    return {
        "profit": bonus,
        "platform_share": platform_share,
        "k": float(p.get("k", 0.01)),
        "cap_multiplier": float(p.get("cap_multiplier", 300)),
        "traditional_rate": float(p.get("traditional_rate", 500)),
        "rho": float(p.get("rho", 0.15)),
        "evolution_rounds": int(p.get("evolution_rounds", 100)),
        "convergence_threshold": float(p.get("convergence_threshold", 0.05)),
        "max_negotiation_rounds": int(p.get("max_negotiation_rounds", 10)),
        "distributable": round(bonus * (1 - platform_share), 2),
    }
