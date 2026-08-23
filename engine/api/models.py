"""AlphaSplit FastAPI 数据模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CalculateRequest(BaseModel):
    scenario: str = "quant_fund"
    contributors: Optional[list[dict[str, Any]]] = None
    profit: Optional[float] = None
    platform_share: Optional[float] = None


class SimulateRequest(BaseModel):
    scenario: str = "quant_fund"
    num_calls: int = Field(default=5, ge=1, le=50)


class NegotiateRequest(BaseModel):
    scenario: str = "hs300_five_roles"
    mode: str = Field(default="mock", pattern="^(mock|llm)$")
    backtest: Optional[dict[str, Any]] = Field(
        default=None,
        description="HS300 回测结果；传入后五角色协商与夏普利证据对齐",
    )
    bonus_pool: float = Field(default=10_000_000, ge=0)
    baseline_weights: Optional[dict[str, float]] = Field(
        default=None,
        description="旧池 60% 现行份额",
    )


class EvolutionRequest(BaseModel):
    scenario: str = "quant_fund"
    rounds: int = Field(default=100, ge=10, le=500)
    seed: int = 42


class ConfirmRequest(BaseModel):
    scenario: str = "hs300_five_roles"
    shares: dict[str, float] = Field(
        ..., description="人工确认的份额，可未归一化"
    )
    negotiated: Optional[dict[str, float]] = None
    proposed: Optional[dict[str, float]] = None
    allow_outside_band: bool = False
    role_model: Optional[str] = Field(default=None, description="five_roles 时使用协商上下文")
    settlement_context: Optional[dict[str, Any]] = Field(default=None)


class SensitivityRequest(BaseModel):
    scenario: str = "quant_fund"
    factor_weight: Optional[float] = Field(
        default=0.45,
        ge=0.15,
        le=0.85,
        description="因子/模型归因权重 w：越高，知识资产方份额越高",
    )
    impact_overrides: Optional[dict[str, float]] = None
    rho: Optional[float] = Field(default=None, ge=0.0, le=0.5)
    sweep: bool = True
    sweep_points: int = Field(default=13, ge=5, le=25)


class RebalanceRequest(BaseModel):
    scenario: str = "quant_fund"
    target_shares: dict[str, float] = Field(
        ...,
        description="用户设定的分配目标，如 {'张经理': 0.45, '李量化': 0.40, '陈经理': 0.15}",
    )
    steps: int = Field(default=24, ge=8, le=60)
    start_weight: float = Field(default=0.45, ge=0.15, le=0.85)


class AttributionRequest(BaseModel):
    scenario: str = "quant_fund"
    mode: str = Field(default="mock", pattern="^(mock|llm)$")
    seed: int = 42


class BacktestTimeRange(BaseModel):
    start_date: str | None = None
    end_date: str | None = None


class BacktestRunRequest(BaseModel):
    """QuantSkills 回测引擎请求（嵌套 query 格式）。"""

    request_id: str | None = None
    timestamp: str | None = None
    query: dict[str, Any] = Field(
        default_factory=dict,
        description="time_range / industry / target_role / role_weights / benchmark 等",
    )
    use_cache: bool = Field(
        default=True,
        description="相同参数优先读取缓存（路演/重复演示秒开）",
    )
    force_refresh: bool = Field(
        default=False,
        description="忽略缓存，强制重新计算",
    )
    demo_mode: bool = Field(
        default=False,
        description="路演演示模式：加载官方预置结果，不触发真实回测",
    )


class AgentPlanRequest(BaseModel):
    """Agent 规划回测（不执行）。"""

    text: str | None = Field(default=None, description="自然语言需求")
    preset_id: str | None = Field(default=None, description="内置预设 id")
    query: dict[str, Any] | None = Field(default=None, description="覆盖/补充 query 字段")
    mode: str = Field(default="mock", pattern="^(mock|llm)$")


class AgentInterpretRequest(BaseModel):
    """Agent 解读已完成回测。"""

    backtest: dict[str, Any]
    plan: dict[str, Any] | None = None
    mode: str = Field(default="mock", pattern="^(mock|llm)$")


class AgentPipelineRequest(BaseModel):
    """Agent 规划 + 执行回测 + 解读（一条龙）。"""

    text: str | None = None
    preset_id: str | None = None
    query: dict[str, Any] | None = None
    mode: str = Field(default="mock", pattern="^(mock|llm)$")
    demo_mode: bool = False
    use_cache: bool = True
    force_refresh: bool = False
