"""
AlphaSplit FastAPI 入口。

启动：
  python -m engine.api.main
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.agentic.attribution_agent import run_attribution_pipeline
from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import confirm_settlement, run_negotiation
from engine.agentic.role_negotiation import confirm_role_settlement, run_role_negotiation
from engine.api.models import (
    AgentCredentialRequest,
    AgentInterpretRequest,
    AgentFactorConfigRequest,
    AgentPipelineRequest,
    AgentPlanRequest,
    AttributionRequest,
    BacktestRunRequest,
    CalculateRequest,
    ConfirmRequest,
    EvolutionRequest,
    NegotiateRequest,
    RebalanceRequest,
    SensitivityRequest,
    SimulateRequest,
)
from agent_layer.impl.llm import clear_runtime_api_key, configure_runtime_api_key
from engine.integrations.agent_bridge import (
    interpret_backtest as agent_interpret,
    list_presets as agent_list_presets,
    plan_backtest as agent_plan,
    get_factor_config_meta,
    propose_agent_factor_config,
    run_agent_pipeline,
    _agent_meta as agent_meta_payload,
)
from engine.integrations.quantskills_backtest import (
    data_available,
    get_demo_info,
    get_demo_result,
    get_meta,
    list_cached_results,
    load_cached_result,
    load_result_by_id,
    map_error_status,
    run_backtest_query,
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
_backtest_run_lock = threading.Lock()


def _require_backtest_access(token: str | None) -> None:
    """保护真实回测与历史结果；健康检查和官方演示包保持公开。"""
    expected = os.getenv("ALPHASPLIT_API_TOKEN", "").strip()
    demo_only = os.getenv("ALPHASPLIT_PUBLIC_DEMO_ONLY", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if expected:
        if token is None or not hmac.compare_digest(token, expected):
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "UNAUTHORIZED",
                    "error_message": "需要有效的 X-AlphaSplit-Token",
                },
            )
        return
    if demo_only:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PUBLIC_DEMO_ONLY",
                "error_message": "公开演示模式仅开放预计算演示包",
            },
        )


def _acquire_backtest_slot() -> None:
    if not _backtest_run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "BACKTEST_BUSY",
                "error_message": "已有回测正在执行，请稍后重试",
            },
        )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": app.state.mode,
        "version": "0.3.0",
        "framework": "attribution-plan-negotiate-confirm",
        "agent_layer": {
            "endpoint": "/api/agent/plan",
            "pipeline_endpoint": "/api/agent/pipeline",
            "impl": agent_meta_payload().get("default_impl"),
            "llm": agent_meta_payload().get("llm"),
        },
        "backtest_engine": {
            "available": data_available(),
            "endpoint": "/api/backtest/run",
            "demo_endpoint": "/api/backtest/demo",
            "demo_available": get_demo_info().get("available", False),
        },
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
        if body.scenario == "hs300_five_roles" or body.backtest is not None:
            return run_role_negotiation(
                body.backtest,
                baseline_weights=body.baseline_weights,
                bonus_pool=body.bonus_pool,
                mode=mode,
            )
        return run_negotiation(body.scenario, mode=mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/confirm")
def api_confirm(body: ConfirmRequest):
    if not body.shares:
        raise HTTPException(status_code=400, detail="shares 不能为空")
    try:
        if body.role_model == "five_roles" and body.settlement_context:
            return confirm_role_settlement(
                body.shares,
                body.settlement_context,
                allow_outside_band=body.allow_outside_band,
            )
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


@app.get("/api/agent/meta")
def api_agent_meta():
    """可替换 Agent 层元信息（实现切换说明）。"""
    return {"status": "ok", **agent_meta_payload()}


@app.get("/api/agent/presets")
def api_agent_presets():
    return {"status": "ok", "presets": agent_list_presets()}


@app.get("/api/agent/factor-config")
def api_agent_factor_config_meta():
    """五角色默认因子配置与可调整因子元信息。"""
    return {"status": "ok", **get_factor_config_meta()}


@app.put("/api/agent/credentials")
def api_configure_agent_credentials(
    body: AgentCredentialRequest,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """为当前服务进程配置模型凭证，不写入磁盘或日志。"""
    _require_backtest_access(x_alphasplit_token)
    try:
        status = configure_runtime_api_key(body.api_key.get_secret_value())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"status": "ok", "agent": status}


@app.delete("/api/agent/credentials")
def api_clear_agent_credentials(
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """清除页面设置的进程内凭证，恢复环境变量或离线模式。"""
    _require_backtest_access(x_alphasplit_token)
    return {"status": "ok", "agent": clear_runtime_api_key()}


@app.post("/api/agent/factor-config")
def api_agent_factor_config(
    body: AgentFactorConfigRequest,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """根据用户描述生成配置变更预览；不触发回测。"""
    if body.mode == "llm":
        _require_backtest_access(x_alphasplit_token)
    try:
        return {
            "status": "ok",
            **propose_agent_factor_config(
                text=body.text,
                current_config=body.current_config,
                messages=body.messages,
                quick_preferences=body.quick_preferences,
                mode=body.mode,  # type: ignore[arg-type]
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agent/plan")
def api_agent_plan(body: AgentPlanRequest):
    try:
        return agent_plan(
            text=body.text,
            preset_id=body.preset_id,
            query=body.query,
            mode=body.mode,  # type: ignore[arg-type]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/agent/interpret")
def api_agent_interpret(body: AgentInterpretRequest):
    try:
        return agent_interpret(body.backtest, body.plan, mode=body.mode)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/agent/pipeline")
def api_agent_pipeline(
    body: AgentPipelineRequest,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """Agent 规划 → 回测执行 → 解读（同步；前端流式回测请用 plan + /backtest/run/stream）。"""
    _require_backtest_access(x_alphasplit_token)
    _acquire_backtest_slot()
    try:
        result = run_agent_pipeline(
            text=body.text,
            preset_id=body.preset_id,
            query=body.query,
            mode=body.mode,  # type: ignore[arg-type]
            demo_mode=body.demo_mode,
            use_cache=body.use_cache,
            force_refresh=body.force_refresh,
        )
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail={
                    "error_message": result.get("error_message"),
                    "plan": result.get("plan"),
                },
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        _backtest_run_lock.release()


@app.get("/api/backtest/meta")
def api_backtest_meta():
    """QuantSkills 回测引擎元信息（角色、基准、合法枚举）。"""
    return get_meta()


@app.get("/api/backtest/demo")
def api_backtest_demo():
    """路演官方演示包（预计算结果，秒开，可离线）。"""
    data = get_demo_result()
    if not data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NO_DATA",
                "error_message": "路演演示包未找到，请运行 scripts/gen_backtest_demo.py 生成。",
                "static_url": "/static/demo/backtest_demo.json",
            },
        )
    return data


@app.get("/api/backtest/results")
def api_backtest_results(
    limit: int = Query(default=15, ge=1, le=50),
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """列出参数缓存与历史回测记录。"""
    _require_backtest_access(x_alphasplit_token)
    return {"items": list_cached_results(limit=limit)}


@app.get("/api/backtest/results/{request_id}")
def api_backtest_result(
    request_id: str,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """读取某次历史回测的 response.json。"""
    _require_backtest_access(x_alphasplit_token)
    data = load_result_by_id(request_id)
    if not data:
        raise HTTPException(status_code=404, detail="未找到该回测结果")
    return data


def _strip_run_options(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in ("use_cache", "force_refresh", "demo_mode"):
        out.pop(key, None)
    return out


def _backtest_run_options(body: BacktestRunRequest) -> dict[str, bool]:
    return {
        "use_cache": body.use_cache,
        "force_refresh": body.force_refresh,
        "demo_mode": body.demo_mode,
    }


@app.post("/api/backtest/run")
def api_backtest_run(
    body: BacktestRunRequest,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """
    执行 HS300 多角色回测与 Shapley 归因（徐远交付引擎）。

    示例 query：
      {"time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
       "benchmark": "hs300", "rebalance_freq": "monthly"}
    """
    _require_backtest_access(x_alphasplit_token)
    payload = _strip_run_options(body.model_dump(exclude_none=True))
    opts = _backtest_run_options(body)
    _acquire_backtest_slot()
    try:
        result = run_backtest_query(payload, **opts)
    finally:
        _backtest_run_lock.release()
    if result.get("status") == "error":
        code = result.get("error_code", "EXECUTION_ERROR")
        raise HTTPException(
            status_code=map_error_status(code),
            detail={
                "error_code": code,
                "error_message": result.get("error_message", "回测执行失败"),
                "request_id": result.get("request_id"),
            },
        )
    return result


@app.post("/api/backtest/run/stream")
async def api_backtest_run_stream(
    body: BacktestRunRequest,
    x_alphasplit_token: str | None = Header(default=None, alias="X-AlphaSplit-Token"),
):
    """SSE 流式回测：边执行边推送阶段进度与 Shapley 子集结果。"""
    _require_backtest_access(x_alphasplit_token)
    payload = _strip_run_options(body.model_dump(exclude_none=True))
    opts = _backtest_run_options(body)
    _acquire_backtest_slot()

    async def event_stream():
        q: Queue = Queue()

        def on_progress(event: dict) -> None:
            q.put(event)

        def worker() -> None:
            try:
                result = run_backtest_query(payload, progress_callback=on_progress, **opts)
                if result.get("status") == "error":
                    q.put(
                        {
                            "type": "error",
                            "error_code": result.get("error_code", "EXECUTION_ERROR"),
                            "error_message": result.get("error_message", "回测执行失败"),
                            "request_id": result.get("request_id"),
                        }
                    )
                else:
                    q.put({"type": "complete", "result": result})
            except Exception as exc:
                q.put(
                    {
                        "type": "error",
                        "error_code": "EXECUTION_ERROR",
                        "error_message": str(exc),
                    }
                )
            finally:
                _backtest_run_lock.release()

        thread = threading.Thread(target=worker, daemon=True)
        try:
            thread.start()
        except Exception:
            _backtest_run_lock.release()
            raise

        while thread.is_alive() or not q.empty():
            try:
                item = q.get_nowait()
            except Empty:
                await asyncio.sleep(0.2)
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            if item.get("type") in ("complete", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
