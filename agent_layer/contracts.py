"""
Agent 层对外契约（稳定接口）。

engine 仅依赖本文件中的类型与 runtime 入口；实现细节在 agent_layer/impl/，
可由其他队员整体替换，只需保持同名方法与返回结构。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


AgentMode = Literal["mock", "llm"]


@dataclass
class PlanStep:
    id: str
    title: str
    detail: str


@dataclass
class BacktestPlan:
    """Agent 输出的回测执行计划（对应 query_engine v4 query 字段）。"""

    query: dict[str, Any]
    summary: str
    reasoning: str
    steps: list[PlanStep] = field(default_factory=list)
    preset_id: Optional[str] = None
    source: str = "rule"  # rule | llm | preset
    factor_config: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReport:
    """对已完成回测结果的解读（供治理责任人 / 业务阅读）。"""

    headline: str
    body: str
    bullets: list[str] = field(default_factory=list)
    focus_role: Optional[str] = None
    dual_pool_note: str = ""
    mode: str = "mock"
    trust: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    llm_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentPipelineResult:
    plan: BacktestPlan
    backtest: Optional[dict[str, Any]] = None
    report: Optional[AgentReport] = None
    status: str = "planned"  # planned | completed | error
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error_message": self.error_message,
            "plan": self.plan.to_dict(),
            "backtest": self.backtest,
            "report": self.report.to_dict() if self.report else None,
        }
