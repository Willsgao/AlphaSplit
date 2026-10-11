"""HS300 五角色贡献陈述与评审决策支持。"""
from __future__ import annotations

from typing import Any, Optional

from engine.core.settlement import (
    apply_human_confirm,
    build_bands,
    build_settlement_rows,
)

ROLE_ORDER = [
    "行业分析师",
    "个股分析师",
    "策略分析师",
    "量化分析师",
    "风控分析师",
]

OLD_POOL_RATIO = 0.6
NEW_POOL_RATIO = 0.4
DEFAULT_BASELINE = {r: 0.2 for r in ROLE_ORDER}
DEFAULT_BONUS_POOL = 10_000_000
DEFAULT_PLATFORM_SHARE = 0.0


def _normalize(shares: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in shares.values())
    if total <= 0:
        n = len(shares) or 1
        return {k: 1.0 / n for k in shares}
    return {k: max(0.0, float(v)) / total for k, v in shares.items()}


def _breakdown_map(backtest: dict[str, Any]) -> dict[str, dict]:
    rows = (backtest.get("results") or {}).get("role_breakdown") or []
    return {r["role"]: r for r in rows if r.get("role")}


def build_dual_track_weights(
    backtest: dict[str, Any] | None,
    baseline: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """返回 (现行 baseline, 新池夏普利, 6:4 合成)。"""
    base = _normalize({**DEFAULT_BASELINE, **(baseline or {})})
    new_pool: dict[str, float] = {}
    bmap = _breakdown_map(backtest) if backtest else {}

    if bmap:
        for role in ROLE_ORDER:
            new_pool[role] = float(bmap.get(role, {}).get("weight") or 0.0)
        new_pool = _normalize(new_pool)
    else:
        new_pool = dict(DEFAULT_BASELINE)

    composite = {
        role: OLD_POOL_RATIO * base[role] + NEW_POOL_RATIO * new_pool[role]
        for role in ROLE_ORDER
    }
    return base, new_pool, _normalize(composite)


def _utterance(
    role: str,
    *,
    shapley_pct: float,
    new_w: float,
    composite: float,
    claim: float,
    round_phase: str,
) -> str:
    short = role.replace("分析师", "")
    if round_phase == "opening":
        if shapley_pct >= 0.15:
            return (
                f"本轮夏普利边际贡献约 {shapley_pct:+.2f}%，新池建议权重 {new_w*100:.1f}%。"
                f"行业/岗位决策对组合超额贡献显著，6:4 合成仅 {composite*100:.1f}% 低估了我的边际价值，"
                f"我建议评审关注总资源池份额 {claim*100:.1f}%；仅供评审参考，不构成分配决定。"
            )
        if shapley_pct < 0:
            return (
                f"夏普利为负（{shapley_pct:+.2f}%），我接受考核问责，但现行 60% 制度份额应保留；"
                f"建议评审参考 {claim*100:.1f}% 并结合复盘改进；仅供评审参考，不构成分配决定。"
            )
        return (
            f"贡献证据 {shapley_pct:+.2f}%，新池 {new_w*100:.1f}%，6:4 合成 {composite*100:.1f}%。"
            f"我认可计量框架，建议评审参考 {claim*100:.1f}%；该陈述不构成分配决定。"
        )
    # rebuttal
    return (
        f"已听取其他岗位意见。我建议评审参考份额为 {claim*100:.1f}%，"
        f"但该意见仅供评审参考，不改变 6:4 合成建议 {composite*100:.1f}%。"
        f"最终比例由评审委员会（或机构治理责任人）独立判断。"
    )


def _build_claims(
    composite: dict[str, float],
    new_pool: dict[str, float],
    bmap: dict[str, dict],
    *,
    phase: str,
) -> dict[str, float]:
    claims: dict[str, float] = {}
    for role in ROLE_ORDER:
        comp = composite[role]
        sh = float(bmap.get(role, {}).get("shapley_raw") or 0.0)
        rank_bias = new_pool[role] - 0.2
        if phase == "opening":
            claim = comp + 0.06 * rank_bias + (0.04 if sh > 0.05 else -0.02 if sh < 0 else 0)
            claim = max(0.04, min(0.55, claim))
        else:
            claim = comp + 0.02 * rank_bias
            claim = max(0.04, min(0.5, claim))
        claims[role] = round(claim, 4)
    return claims


def _build_rounds(
    composite: dict[str, float],
    new_pool: dict[str, float],
    bmap: dict[str, dict],
) -> tuple[list[dict], dict[str, float]]:
    rounds: list[dict] = []
    prev_norm: Optional[dict[str, float]] = None

    for idx, phase in enumerate(("opening", "rebuttal"), start=1):
        claims = _build_claims(composite, new_pool, bmap, phase=phase)
        norm = _normalize(claims)
        utterances = []
        for role in ROLE_ORDER:
            sh = float(bmap.get(role, {}).get("shapley_raw") or 0.0)
            utterances.append({
                "speaker": role,
                "role": role,
                "claim": claims[role],
                "text": _utterance(
                    role,
                    shapley_pct=sh * 100,
                    new_w=new_pool[role],
                    composite=composite[role],
                    claim=claims[role],
                    round_phase=phase,
                ),
            })
        delta = 0.0
        if prev_norm:
            delta = max(abs(norm[k] - prev_norm.get(k, 0)) for k in ROLE_ORDER)
        rounds.append({
            "round": idx,
            "phase": phase,
            "utterances": utterances,
            "claims": claims,
            "normalized": {k: round(v, 4) for k, v in norm.items()},
            "delta_vs_prev": round(delta, 4),
            "consensus": round(max(0.0, 1.0 - delta * 6), 2),
            "formula_shares": {k: round(composite[k], 4) for k in ROLE_ORDER},
        })
        prev_norm = norm

    return rounds, prev_norm or composite


def _arbiter_speech(
    baseline: dict[str, float],
    new_pool: dict[str, float],
    composite: dict[str, float],
    proposed: dict[str, float],
    negotiated: dict[str, float],
    band: float,
) -> str:
    lines = [
        "【评审委员会 / 机构治理责任人决策说明】",
        "1) 计量锚点：HS300 回测夏普利边际贡献（新池 40%）；",
        f"2) 制度保留：现行分配占旧池 60%；合成公式 = 60%×现行 + 40%×夏普利；",
        "3) 五类角色陈述仅供评审参考，不参与建议份额计算，也不构成分配决定；",
        f"4) 评审委员会可参考角色意见，在 6:4 建议 ±{band:.0%} 范围内独立调整并确认；系统不自动执行分配。",
        "",
        "各岗位 6:4 合成建议与角色参考意见：",
    ]
    for role in ROLE_ORDER:
        lines.append(
            f"- {role}：现行 {baseline[role]:.1%} + 新池 {new_pool[role]:.1%} "
            f"→ 系统建议 {proposed.get(role, composite[role]):.1%}；"
            f"角色参考意见 {negotiated.get(role, 0):.1%}"
        )
    lines.append("\n请评审委员会（或机构治理责任人）在下方独立判断、调整并确认后再应用。")
    return "\n".join(lines)


def run_role_negotiation(
    backtest: dict[str, Any] | None = None,
    *,
    baseline_weights: dict[str, float] | None = None,
    bonus_pool: float = DEFAULT_BONUS_POOL,
    platform_share: float = DEFAULT_PLATFORM_SHARE,
    band: float = 0.05,
    mode: str = "mock",
) -> dict[str, Any]:
    baseline, new_pool, composite = build_dual_track_weights(backtest, baseline_weights)
    bmap = _breakdown_map(backtest) if backtest else {}
    rounds, final_norm = _build_rounds(composite, new_pool, bmap)

    distributable = round(bonus_pool * (1 - platform_share), 2)
    bands = build_bands(composite, band)
    proposed = {role: round(composite[role], 4) for role in ROLE_ORDER}

    settle = build_settlement_rows(
        formula_shares={k: round(composite[k], 4) for k in ROLE_ORDER},
        negotiated=final_norm,
        proposed=proposed,
        bands=bands,
        distributable=distributable,
        final_shares=proposed,
        status="pending_human_confirm",
    )

    query_summary = (backtest or {}).get("query_summary") or "未关联回测（使用默认均等权重演示）"

    return {
        "mode": mode,
        "scenario_id": "hs300_five_roles",
        "scenario": "HS300 五角色贡献陈述与评审决策",
        "domain": "equity_research",
        "framework": "夏普利证据 · 6:4双轨 · 角色陈述参考 · 评审委员会决策",
        "role_model": "five_roles",
        "agents": [
            {"name": r, "role": r, "initial_claim": round(final_norm.get(r, composite[r]), 4)}
            for r in ROLE_ORDER
        ],
        "arbiter": {"name": "评审委员会", "role": "评审委员会 / 机构治理责任人"},
        "rounds": rounds,
        "converged": True,
        "arbiter_intervened": False,
        "arbiter_statement": _arbiter_speech(
            baseline, new_pool, composite, proposed, final_norm, band
        ),
        "dual_track": {
            "old_pool_ratio": OLD_POOL_RATIO,
            "new_pool_ratio": NEW_POOL_RATIO,
            "baseline_weights": {k: round(v, 4) for k, v in baseline.items()},
            "new_pool_weights": {k: round(v, 4) for k, v in new_pool.items()},
            "composite_weights": {k: round(v, 4) for k, v in composite.items()},
        },
        "formula_shares": {k: round(composite[k], 4) for k in ROLE_ORDER},
        "bands": bands,
        "proposed_shares": proposed,
        "status": settle["status"],
        "settlement": settle["rows"],
        "bonus_pool": bonus_pool,
        "distributable": distributable,
        "platform_profit": round(bonus_pool * platform_share, 2),
        "band": band,
        "awaiting_human_confirm": True,
        "backtest_summary": query_summary,
    }


def confirm_role_settlement(
    human_shares: dict[str, float],
    nego: dict[str, Any],
    *,
    allow_outside_band: bool = False,
) -> dict[str, Any]:
    formula = nego["formula_shares"]
    proposed = nego.get("proposed_shares") or formula
    negotiated = {
        name: nego["settlement"][name]["negotiated_share"]
        for name in formula
        if name in nego.get("settlement", {})
    }
    band = float(nego.get("band", 0.05))
    distributable = float(nego.get("distributable", DEFAULT_BONUS_POOL))

    result = apply_human_confirm(
        human_shares,
        formula_shares=formula,
        negotiated=negotiated,
        proposed=proposed,
        distributable=distributable,
        band=band,
        allow_outside_band=allow_outside_band,
    )
    result["scenario"] = nego.get("scenario", "HS300 五角色贡献陈述与评审决策")
    result["scenario_id"] = "hs300_five_roles"
    result["role_model"] = "five_roles"
    return result
