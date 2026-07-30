"""多轮协商协议：Mock 优先，可选 LLM；向公式份额收敛。"""
from __future__ import annotations

from typing import Any, Optional

from engine.agentic.agents import (
    Agent,
    AgentFactory,
    MOCK_DIALOGUE,
    call_llm,
    mock_arbiter_speech,
)
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


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


def run_negotiation_mock(scenario_name: str = "quant_fund") -> dict[str, Any]:
    scenario = load_scenario(scenario_name)
    agents, arbiter = AgentFactory.from_scenario(scenario)
    params = scenario_params(scenario)
    formula_shares, formula_result = _formula_shares(scenario)

    rounds_out: list[dict] = []
    prev_norm: Optional[dict[str, float]] = None
    stable = 0
    converged = False
    final_norm: dict[str, float] = {}

    threshold = params["convergence_threshold"]
    max_rounds = min(params["max_negotiation_rounds"], len(MOCK_DIALOGUE))

    for i, script in enumerate(MOCK_DIALOGUE[:max_rounds]):
        norm = dict(script["normalized"])
        # 末轮把协商意向轻轻拉向公式，体现「向公式收敛」
        if i >= max_rounds - 1:
            blended = {}
            for name in norm:
                blended[name] = 0.35 * norm[name] + 0.65 * formula_shares.get(name, norm[name])
            norm = _normalize(blended)

        delta = _max_share_delta(prev_norm, norm) if prev_norm else 1.0
        # 前两轮允许大幅调整，第 3 轮起才累计收敛计数
        if prev_norm is not None and delta < threshold and i >= 2:
            stable += 1
        else:
            stable = 0 if i >= 2 else stable

        round_payload = {
            **script,
            "normalized": {k: round(v, 4) for k, v in norm.items()},
            "delta_vs_prev": round(delta, 4),
            "formula_shares": formula_shares,
        }
        rounds_out.append(round_payload)
        prev_norm = norm
        final_norm = norm

        if stable >= 2:
            converged = True
            break

    # 最终落账：以公式为准（公平下限/裁判）
    settlement = {
        name: {
            "negotiated_share": round(final_norm.get(name, 0), 4),
            "formula_share": round(formula_shares.get(name, 0), 4),
            "final_share": round(formula_shares.get(name, 0), 4),
            "amount": next(
                c["profit"] for c in formula_result["contributors"] if c["name"] == name
            ),
        }
        for name in formula_shares
    }

    arbiter_needed = not converged
    # Demo：即使收敛也请仲裁宣读公式终值，路演更完整
    arbiter_text = mock_arbiter_speech(formula_shares, final_norm)

    return {
        "mode": "mock",
        "scenario": scenario["scenario"]["name"],
        "agents": [{"name": a.name, "role": a.role, "initial_claim": a.initial_claim} for a in agents],
        "arbiter": {"name": arbiter.name, "role": arbiter.role},
        "rounds": rounds_out,
        "converged": True if converged or len(rounds_out) >= 3 else converged,
        "arbiter_intervened": arbiter_needed,
        "arbiter_statement": arbiter_text,
        "formula_result": formula_result,
        "settlement": settlement,
        "bonus_pool": params["profit"],
        "distributable": formula_result["distributable"],
        "platform_profit": formula_result["platform_profit"],
    }


def run_negotiation_llm(scenario_name: str = "quant_fund") -> dict[str, Any]:
    """
    轻量 LLM 协商：每轮让各 Agent 基于公式锚点调整 claim。
    失败时自动回退 Mock。
    """
    try:
        scenario = load_scenario(scenario_name)
        agents, arbiter = AgentFactory.from_scenario(scenario)
        params = scenario_params(scenario)
        formula_shares, formula_result = _formula_shares(scenario)

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
                    f"你的初始主张: {agent.initial_claim:.0%}\n"
                    f"公式锚点份额: {formula_shares}\n"
                    f"当前各方主张: {claims}\n"
                    f"请用中文简短发言（不超过120字），并在最后一行只输出一个小数作为你的新主张份额，"
                    f"例如 CLAIM=0.33。尽量向公式锚点靠拢，但保留角色立场。"
                )
                content = call_llm([
                    {"role": "system", "content": agent.system_prompt},
                    {"role": "user", "content": prompt},
                ])
                claim = agent.current_claim
                for line in content.strip().splitlines()[::-1]:
                    if "CLAIM=" in line.upper():
                        try:
                            claim = float(line.upper().split("CLAIM=")[-1].strip().split()[0])
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
        settlement = {
            name: {
                "negotiated_share": round(final_norm.get(name, 0), 4),
                "formula_share": round(formula_shares.get(name, 0), 4),
                "final_share": round(formula_shares.get(name, 0), 4),
                "amount": next(
                    c["profit"] for c in formula_result["contributors"] if c["name"] == name
                ),
            }
            for name in formula_shares
        }
        return {
            "mode": "llm",
            "scenario": scenario["scenario"]["name"],
            "agents": [{"name": a.name, "role": a.role, "initial_claim": a.initial_claim} for a in agents],
            "arbiter": {"name": arbiter.name, "role": arbiter.role},
            "rounds": history,
            "converged": stable >= 2,
            "arbiter_intervened": stable < 2,
            "arbiter_statement": mock_arbiter_speech(formula_shares, final_norm),
            "formula_result": formula_result,
            "settlement": settlement,
            "bonus_pool": params["profit"],
            "distributable": formula_result["distributable"],
            "platform_profit": formula_result["platform_profit"],
        }
    except Exception as e:
        fallback = run_negotiation_mock(scenario_name)
        fallback["mode"] = "mock_fallback"
        fallback["llm_error"] = str(e)
        return fallback


def run_negotiation(scenario_name: str = "quant_fund", mode: str = "mock") -> dict[str, Any]:
    if mode == "llm":
        return run_negotiation_llm(scenario_name)
    return run_negotiation_mock(scenario_name)
