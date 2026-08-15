"""
多轮协商协议：Mock 优先，可选 LLM。

机制：
  公式锚点 → 带宽内协商建议案 → 等待人工确认落账
"""
from __future__ import annotations

from typing import Any, Optional

from engine.agentic.agents import (
    AgentFactory,
    MOCK_DIALOGUE,
    call_llm,
)
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params
from engine.core.settlement import (
    apply_human_confirm,
    build_settlement_rows,
    propose_from_negotiation,
)


def _normalize(claims: dict[str, float]) -> dict[str, float]:
    total = sum(claims.values())
    if total <= 0:
        n = len(claims) or 1
        return {k: 1.0 / n for k in claims}
    return {k: v / total for k, v in claims.items()}


def _max_share_delta(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    return max(abs(a.get(k, 0) - b.get(k, 0)) for k in keys) if keys else 0.0


def _formula_shares(scenario: dict) -> tuple[dict[str, float], dict]:
    contributors = agents_to_contributors(scenario)
    params = scenario_params(scenario)
    result = calculate_once(
        contributors,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
        apply_platform_deduction=True,
    )
    shares = {
        c["name"]: round(c["share_pct"] / 100.0, 4)
        for c in result["contributors"]
    }
    return shares, result


def _mock_scripts(scenario: dict) -> list[dict]:
    custom = scenario.get("mock_dialogue")
    if isinstance(custom, list) and custom:
        return custom
    return MOCK_DIALOGUE


def _arbiter_speech(
    formula_shares: dict[str, float],
    proposed: dict[str, float],
    bands: dict[str, dict[str, float]],
    negotiated: dict[str, float],
) -> str:
    band = next(iter(bands.values()))["band"] if bands else 0.05
    lines = [
        "协商已形成建议案。制度规则如下：",
        f"1) 贡献值公式给出可审计锚点；2) 各方可在锚点 ±{band:.0%} 带宽内协商；"
        "3) 最终须人工确认后落账（合规定责）。",
        "C = Labor × Impact × Scarcity × Reuse。",
    ]
    for name, anchor in formula_shares.items():
        b = bands[name]
        lines.append(
            f"- {name}：锚点 {anchor:.1%}（带宽 {b['low']:.1%}–{b['high']:.1%}），"
            f"协商意向 {negotiated.get(name, 0):.1%}，系统建议 {proposed.get(name, anchor):.1%}。"
        )
    lines.append("请负责人在下方确认或微调建议案后生效。")
    return "\n".join(lines)


def _pack_result(
    *,
    mode: str,
    scenario: dict,
    agents,
    arbiter,
    rounds_out: list,
    converged: bool,
    formula_shares: dict[str, float],
    formula_result: dict,
    final_norm: dict[str, float],
    params: dict,
) -> dict[str, Any]:
    band = float(params.get("band", 0.05))
    proposed, bands = propose_from_negotiation(
        final_norm, formula_shares, band=band, blend=0.45
    )
    settle = build_settlement_rows(
        formula_shares=formula_shares,
        negotiated=final_norm,
        proposed=proposed,
        bands=bands,
        distributable=formula_result["distributable"],
        final_shares=proposed,
        status="pending_human_confirm",
    )
    return {
        "mode": mode,
        "scenario_id": scenario.get("_id") or scenario.get("scenario", {}).get("id", ""),
        "scenario": scenario["scenario"]["name"],
        "domain": scenario["scenario"].get("domain", "general"),
        "framework": "知识资产贡献计量 · 锚点带宽协商 · 人工确认",
        "agents": [
            {"name": a.name, "role": a.role, "initial_claim": a.initial_claim}
            for a in agents
        ],
        "arbiter": {"name": arbiter.name, "role": arbiter.role},
        "rounds": rounds_out,
        "converged": converged,
        "arbiter_intervened": not converged,
        "arbiter_statement": _arbiter_speech(
            formula_shares, proposed, bands, final_norm
        ),
        "formula_result": formula_result,
        "formula_shares": formula_shares,
        "bands": bands,
        "proposed_shares": proposed,
        "status": settle["status"],
        "settlement": settle["rows"],
        "bonus_pool": params["profit"],
        "distributable": formula_result["distributable"],
        "platform_profit": formula_result["platform_profit"],
        "band": band,
        "awaiting_human_confirm": True,
    }


def run_negotiation_mock(scenario_name: str = "quant_fund") -> dict[str, Any]:
    scenario = load_scenario(scenario_name)
    scenario["_id"] = scenario_name
    agents, arbiter = AgentFactory.from_scenario(scenario)
    params = scenario_params(scenario)
    formula_shares, formula_result = _formula_shares(scenario)
    scripts = _mock_scripts(scenario)

    rounds_out: list[dict] = []
    prev_norm: Optional[dict[str, float]] = None
    stable = 0
    converged = False
    final_norm: dict[str, float] = {}

    threshold = params["convergence_threshold"]
    max_rounds = min(params["max_negotiation_rounds"], len(scripts))

    for i, script in enumerate(scripts[:max_rounds]):
        norm = dict(script.get("normalized") or _normalize(script.get("claims", {})))
        if i >= max_rounds - 1:
            blended = {
                name: 0.4 * norm.get(name, formula_shares[name])
                + 0.6 * formula_shares.get(name, norm.get(name, 0))
                for name in formula_shares
            }
            norm = _normalize(blended)

        delta = _max_share_delta(prev_norm, norm) if prev_norm else 1.0
        if prev_norm is not None and delta < threshold and i >= 2:
            stable += 1
        else:
            stable = 0 if i >= 2 else stable

        rounds_out.append({
            **script,
            "normalized": {k: round(v, 4) for k, v in norm.items()},
            "delta_vs_prev": round(delta, 4),
            "formula_shares": formula_shares,
        })
        prev_norm = norm
        final_norm = norm
        if stable >= 2:
            converged = True
            break

    if not final_norm:
        final_norm = dict(formula_shares)

    return _pack_result(
        mode="mock",
        scenario=scenario,
        agents=agents,
        arbiter=arbiter,
        rounds_out=rounds_out,
        converged=converged or len(rounds_out) >= 3,
        formula_shares=formula_shares,
        formula_result=formula_result,
        final_norm=final_norm,
        params=params,
    )


def run_negotiation_llm(scenario_name: str = "quant_fund") -> dict[str, Any]:
    try:
        scenario = load_scenario(scenario_name)
        scenario["_id"] = scenario_name
        agents, arbiter = AgentFactory.from_scenario(scenario)
        params = scenario_params(scenario)
        formula_shares, formula_result = _formula_shares(scenario)
        band = float(params.get("band", 0.05))

        history: list[dict] = []
        claims = {a.name: a.initial_claim for a in agents}
        prev_norm = None
        stable = 0
        max_rounds = params["max_negotiation_rounds"]
        threshold = params["convergence_threshold"]

        for r in range(1, max_rounds + 1):
            utterances = []
            for agent in agents:
                prompt = (
                    f"当前轮次: {r}/{max_rounds}\n"
                    f"你的角色: {agent.role}\n"
                    f"初始主张: {agent.initial_claim:.0%}\n"
                    f"公式锚点: {formula_shares}\n"
                    f"允许带宽: 锚点±{band:.0%}\n"
                    f"当前主张: {claims}\n"
                    f"请用中文简短发言（≤120字），最后一行输出 CLAIM=0.xx。"
                    f"尽量落在带宽内，保留角色立场。"
                )
                content = call_llm([
                    {"role": "system", "content": agent.system_prompt},
                    {"role": "user", "content": prompt},
                ])
                claim = agent.current_claim
                for line in content.strip().splitlines()[::-1]:
                    if "CLAIM=" in line.upper():
                        try:
                            claim = float(
                                line.upper().split("CLAIM=")[-1].strip().split()[0]
                            )
                            break
                        except ValueError:
                            pass
                claim = max(0.05, min(0.7, claim))
                agent.current_claim = claim
                claims[agent.name] = claim
                utterances.append({
                    "speaker": agent.name,
                    "role": agent.role,
                    "claim": claim,
                    "text": content.strip(),
                })

            norm = _normalize(claims)
            delta = _max_share_delta(prev_norm, norm) if prev_norm else 1.0
            if prev_norm is not None and delta < threshold:
                stable += 1
            else:
                stable = 0
            history.append({
                "round": r,
                "phase": "llm",
                "utterances": utterances,
                "claims": dict(claims),
                "normalized": {k: round(v, 4) for k, v in norm.items()},
                "delta_vs_prev": round(delta, 4),
                "consensus": round(max(0.0, 1.0 - delta * 8), 2),
                "formula_shares": formula_shares,
            })
            prev_norm = norm
            if stable >= 2:
                break

        final_norm = prev_norm or _normalize(claims)
        return _pack_result(
            mode="llm",
            scenario=scenario,
            agents=agents,
            arbiter=arbiter,
            rounds_out=history,
            converged=stable >= 2,
            formula_shares=formula_shares,
            formula_result=formula_result,
            final_norm=final_norm,
            params=params,
        )
    except Exception as e:
        fallback = run_negotiation_mock(scenario_name)
        fallback["mode"] = "mock_fallback"
        fallback["llm_error"] = str(e)
        return fallback


def run_negotiation(scenario_name: str = "quant_fund", mode: str = "mock") -> dict[str, Any]:
    if mode == "llm":
        return run_negotiation_llm(scenario_name)
    return run_negotiation_mock(scenario_name)


def confirm_settlement(
    scenario_name: str,
    human_shares: dict[str, float],
    *,
    negotiated: dict[str, float] | None = None,
    proposed: dict[str, float] | None = None,
    allow_outside_band: bool = False,
) -> dict[str, Any]:
    """人工确认接口：输入份额（可未归一），返回确认后的落账。"""
    scenario = load_scenario(scenario_name)
    params = scenario_params(scenario)
    formula_shares, formula_result = _formula_shares(scenario)
    band = float(params.get("band", 0.05))

    if proposed is None or negotiated is None:
        # 无上下文时：用公式锚点作为协商/建议默认
        negotiated = negotiated or dict(formula_shares)
        proposed, _ = propose_from_negotiation(
            negotiated, formula_shares, band=band
        )

    result = apply_human_confirm(
        human_shares,
        formula_shares=formula_shares,
        negotiated=negotiated,
        proposed=proposed,
        distributable=formula_result["distributable"],
        band=band,
        allow_outside_band=allow_outside_band,
    )
    result["scenario"] = scenario["scenario"]["name"]
    result["scenario_id"] = scenario_name
    result["formula_shares"] = formula_shares
    result["platform_profit"] = formula_result["platform_profit"]
    result["bonus_pool"] = params["profit"]
    return result
