"""
AlphaSplit FastAPI 入口。

启动：
  python -m engine.api.main
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.agentic.attribution_agent import run_attribution_pipeline
from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import confirm_settlement, run_negotiation
from engine.api.models import (
    AttributionRequest,
    CalculateRequest,
    ConfirmRequest,
    EvolutionRequest,
    NegotiateRequest,
    RebalanceRequest,
    SensitivityRequest,
    SimulateRequest,
)
from engine.core.calculator import calculate_once, simulate_calls
from engine.core.scenario import (
    agents_to_contributors,
    list_scenarios,
    load_scenario,
    scenario_params,
)
from engine.core.sensitivity import run_rebalance_demo, run_sensitivity

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(
    title="AlphaSplit",
    description="金融知识资产贡献计量 · 多方协商 · 人工确认",
    version="0.3.0",
)

app.state.mode = "mock"


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": app.state.mode,
        "version": "0.3.0",
        "framework": "attribution-plan-negotiate-confirm",
    }


@app.get("/api/scenarios")
def api_list_scenarios():
    return {"scenarios": list_scenarios()}


@app.get("/api/scenario")
def get_scenario(name: str = Query(default="quant_fund")):
    try:
        return load_scenario(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/calculate")
def api_calculate(body: CalculateRequest):
    try:
        scenario = load_scenario(body.scenario)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    params = scenario_params(scenario)
    contributors = body.contributors or agents_to_contributors(scenario)
    result = calculate_once(
        contributors,
        profit=body.profit if body.profit is not None else params["profit"],
        platform_share=(
            body.platform_share
            if body.platform_share is not None
            else params["platform_share"]
        ),
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
    )
    result["band"] = params["band"]
    return result


@app.post("/api/simulate")
def api_simulate(body: SimulateRequest):
    try:
        scenario = load_scenario(body.scenario)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    params = scenario_params(scenario)
    contributors = agents_to_contributors(scenario)
    per = params["distributable"] / max(body.num_calls, 1)
    return simulate_calls(
        contributors,
        profit_per_call=per,
        num_calls=body.num_calls,
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
        apply_platform_deduction=False,
    )


@app.post("/api/negotiate")
def api_negotiate(body: NegotiateRequest):
    mode = body.mode or app.state.mode or "mock"
    try:
        return run_negotiation(body.scenario, mode=mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/confirm")
def api_confirm(body: ConfirmRequest):
    if not body.shares:
        raise HTTPException(status_code=400, detail="shares 不能为空")
    try:
        return confirm_settlement(
            body.scenario,
            body.shares,
            negotiated=body.negotiated,
            proposed=body.proposed,
            allow_outside_band=body.allow_outside_band,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/evolution")
def api_evolution(body: EvolutionRequest):
    try:
        return run_evolution(body.scenario, rounds=body.rounds, seed=body.seed)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/sensitivity")
def api_sensitivity(body: SensitivityRequest):
    try:
        return run_sensitivity(
            body.scenario,
            factor_weight=body.factor_weight,
            impact_overrides=body.impact_overrides,
            rho=body.rho,
            sweep=body.sweep,
            sweep_points=body.sweep_points,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/rebalance")
def api_rebalance(body: RebalanceRequest):
    if not body.target_shares:
        raise HTTPException(status_code=400, detail="target_shares 不能为空")
    try:
        return run_rebalance_demo(
            body.scenario,
            target_shares=body.target_shares,
            steps=body.steps,
            start_weight=body.start_weight,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/attribution")
def api_attribution(body: AttributionRequest):
    try:
        return run_attribution_pipeline(
            body.scenario,
            mode=body.mode,
            seed=body.seed,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/")
def index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="前端未找到")
    return FileResponse(index_path)


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def main():
    parser = argparse.ArgumentParser(description="AlphaSplit API")
    parser.add_argument("--mode", choices=["mock", "llm"], default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app.state.mode = args.mode

    import uvicorn
    print(f"AlphaSplit starting in {args.mode} mode → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
