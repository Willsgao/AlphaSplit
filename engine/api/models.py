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
