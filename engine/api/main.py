"""
AlphaSplit FastAPI 入口。

启动：
  cd AlphaSplit
  pip install -r requirements.txt
  python -m engine.api.main

或：
  uvicorn engine.api.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 保证以多种启动方式都能 import engine.*
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import run_negotiation
from engine.api.models import (
    CalculateRequest,
    EvolutionRequest,
    NegotiateRequest,
    SimulateRequest,
)
from engine.core.calculator import calculate_once, simulate_calls
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(
    title="AlphaSplit",
    description="多智能体协商的金融知识工作贡献计量与公平分配",
    version="0.1.0",
)

# 运行模式：由启动参数写入
app.state.mode = "mock"


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": app.state.mode, "version": "0.1.0"}


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
    return result


@app.post("/api/simulate")
def api_simulate(body: SimulateRequest):
    try:
        scenario = load_scenario(body.scenario)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    params = scenario_params(scenario)
    contributors = agents_to_contributors(scenario)
    # 多轮：每轮分「可分配池」的 1/num 近似，演示 cap 溢出
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
    # 请求显式指定优先；否则用进程启动 --mode
    mode = body.mode or app.state.mode or "mock"
    try:
        return run_negotiation(body.scenario, mode=mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/evolution")
def api_evolution(body: EvolutionRequest):
    try:
        return run_evolution(body.scenario, rounds=body.rounds, seed=body.seed)
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
