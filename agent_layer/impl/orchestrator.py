"""Agent 编排：规划 →（可选）执行回测 → 解读。"""

from __future__ import annotations

from typing import Any, Callable

from agent_layer.contracts import AgentMode, AgentPipelineResult, AgentReport, BacktestPlan
from agent_layer.impl.interpreter import BacktestInterpreter
from agent_layer.impl.planner import BacktestPlanner


class AgentRuntime:
    """
    默认 Agent 运行时。

    队员替换实现时，保持本类公开方法签名不变：
      - plan_backtest
      - interpret_backtest
      - run_pipeline
    """

    def __init__(self, meta: dict[str, Any] | None = None):
        self.meta = meta or {}
        self.planner = BacktestPlanner(meta=self.meta)
        self.interpreter = BacktestInterpreter()

    def list_presets(self) -> list[dict[str, str]]:
        return self.planner.list_presets()

    def plan_backtest(
        self,
        *,
        text: str | None = None,
        preset_id: str | None = None,
        query_override: dict[str, Any] | None = None,
        mode: AgentMode = "mock",
    ) -> BacktestPlan:
        return self.planner.plan(
            text=text,
            preset_id=preset_id,
            query_override=query_override,
            mode=mode,
        )

    def interpret_backtest(
        self,
        backtest: dict[str, Any],
        plan: BacktestPlan | dict | None = None,
        *,
        mode: AgentMode = "mock",
    ) -> AgentReport:
        plan_obj = None
        if isinstance(plan, BacktestPlan):
            plan_obj = plan
        elif isinstance(plan, dict):
            plan_obj = BacktestPlan(
                query=plan.get("query") or {},
                summary=plan.get("summary") or "",
                reasoning=plan.get("reasoning") or "",
                preset_id=plan.get("preset_id"),
                source=plan.get("source") or "unknown",
            )
        return self.interpreter.interpret(backtest, plan_obj, mode=mode)

    def run_pipeline(
        self,
        *,
        text: str | None = None,
        preset_id: str | None = None,
        query_override: dict[str, Any] | None = None,
        mode: AgentMode = "mock",
        run_backtest: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        demo_mode: bool = False,
        use_cache: bool = True,
    ) -> AgentPipelineResult:
        plan = self.plan_backtest(
            text=text,
            preset_id=preset_id,
            query_override=query_override,
            mode=mode,
        )
        if run_backtest is None:
            return AgentPipelineResult(plan=plan, status="planned")

        payload = {
            "query": plan.query,
            "demo_mode": demo_mode,
            "use_cache": use_cache,
        }
        try:
            backtest = run_backtest(payload)
        except Exception as exc:
            return AgentPipelineResult(
                plan=plan,
                status="error",
                error_message=str(exc),
            )

        if backtest.get("status") == "error":
            return AgentPipelineResult(
                plan=plan,
                backtest=backtest,
                status="error",
                error_message=backtest.get("error_message") or "回测失败",
            )

        report = self.interpret_backtest(backtest, plan, mode=mode)
        return AgentPipelineResult(
            plan=plan,
            backtest=backtest,
            report=report,
            status="completed",
        )
