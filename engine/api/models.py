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
    scenario: str = "quant_fund"
    mode: str = Field(default="mock", pattern="^(mock|llm)$")


class EvolutionRequest(BaseModel):
    scenario: str = "quant_fund"
    rounds: int = Field(default=100, ge=10, le=500)
    seed: int = 42


class ConfirmRequest(BaseModel):
    scenario: str = "quant_fund"
    shares: dict[str, float] = Field(
        ..., description="人工确认的份额，可未归一化，如 {'张经理': 0.38, ...}"
    )
    negotiated: Optional[dict[str, float]] = None
    proposed: Optional[dict[str, float]] = None
    allow_outside_band: bool = False


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
