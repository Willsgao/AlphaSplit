"""
Agent 层桥接 —— engine 调用 Agent 的唯一入口。

请勿在 engine 其他位置直接 import agent_layer.impl；替换实现请改 registry 或 AGENT_LAYER_IMPL。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_layer import create_runtime  # noqa: E402
from agent_layer.contracts import AgentMode  # noqa: E402
from agent_layer.impl.factor_agent import propose_with_factor_agent  # noqa: E402
from agent_layer.impl.llm import llm_status  # noqa: E402
from agent_layer.impl.offline_cache import offline_cache_status  # noqa: E402
from engine.integrations.quantskills_backtest import get_meta, run_backtest_query  # noqa: E402
from backtest.factor_config import factor_config_meta  # noqa: E402


def _load_industries() -> list[str]:
    path = ROOT / "data" / "processed" / "stock_industry_mapping.csv"
    if not path.exists():
        return []
    try:
        import pandas as pd

        df = pd.read_csv(path, encoding="utf-8-sig")
        return sorted(df["industry"].astype(str).str.strip().unique().tolist())
    except Exception:
        return []


def _agent_meta() -> dict[str, Any]:
    bt = get_meta()
    return {
        "roles": bt.get("roles") or [],
        "industries": _load_industries(),
        "benchmarks": bt.get("benchmarks") or [],
        "rebalance_freq": bt.get("rebalance_freq") or [],
        "default_impl": "agent_layer.impl.orchestrator",
        "swap_hint": "设置 AGENT_LAYER_IMPL 或修改 agent_layer/registry.py",
        "llm": llm_status(),
    }


def get_agent_runtime():
    return create_runtime(meta=_agent_meta())


def list_presets() -> list[dict[str, str]]:
    return get_agent_runtime().list_presets()


def get_factor_config_meta() -> dict[str, Any]:
    return {
        **factor_config_meta(),
        "agent": {
            **llm_status(),
            "offline_cache": offline_cache_status(),
        },
    }


def propose_agent_factor_config(
    *, text: str | None = None, current_config: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    quick_preferences: dict[str, Any] | None = None,
    mode: AgentMode = "mock",
) -> dict[str, Any]:
    """生成变更预览；数值最终始终经过后端配置校验。"""
    return propose_with_factor_agent(
        text=text,
        current_config=current_config,
        messages=messages,
        quick_preferences=quick_preferences,
        mode=mode,
    )


def plan_backtest(
    *,
    text: str | None = None,
    preset_id: str | None = None,
    query: dict[str, Any] | None = None,
    mode: AgentMode = "mock",
) -> dict[str, Any]:
    runtime = get_agent_runtime()
    plan = runtime.plan_backtest(
        text=text,
        preset_id=preset_id,
        query_override=query,
        mode=mode,
    )
    return {
        "status": "ok",
        "mode": mode,
        "plan": plan.to_dict(),
    }


def interpret_backtest(
    backtest: dict[str, Any],
    plan: dict[str, Any] | None = None,
    *,
    mode: AgentMode = "mock",
) -> dict[str, Any]:
    runtime = get_agent_runtime()
    report = runtime.interpret_backtest(backtest, plan, mode=mode)
    return {
        "status": "ok",
        "mode": report.mode,
        "report": report.to_dict(),
    }


def run_agent_pipeline(
    *,
    text: str | None = None,
    preset_id: str | None = None,
    query: dict[str, Any] | None = None,
    mode: AgentMode = "mock",
    demo_mode: bool = False,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    runtime = get_agent_runtime()

    def _run(payload: dict[str, Any]) -> dict[str, Any]:
        return run_backtest_query(
            payload,
            demo_mode=demo_mode or payload.get("demo_mode", False),
            use_cache=use_cache,
            force_refresh=force_refresh,
        )

    result = runtime.run_pipeline(
        text=text,
        preset_id=preset_id,
        query_override=query,
        mode=mode,
        run_backtest=_run,
        demo_mode=demo_mode,
        use_cache=use_cache,
    )
    out = result.to_dict()
    out["mode"] = mode
    return out
