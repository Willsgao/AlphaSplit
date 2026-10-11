"""AlphaSplit FastAPI 数据模型。"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


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
        description="HS300 回测结果；传入后角色贡献陈述与夏普利证据对齐",
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
        description="用户设定的分配目标，如 {'行业分析师': 0.25, '量化分析师': 0.20}",
    )
    steps: int = Field(default=24, ge=8, le=60)
    start_weight: float = Field(default=0.45, ge=0.15, le=0.85)


class AttributionRequest(BaseModel):
    scenario: str = "quant_fund"
    mode: str = Field(default="mock", pattern="^(mock|llm)$")
    seed: int = 42


class BacktestTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: str | None = None
    end_date: str | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc
        return value

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.start_date and self.end_date:
            if date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
                raise ValueError("end_date 不能早于 start_date")
        return self


class BacktestQuery(BaseModel):
    """真实回测允许的查询字段；未知字段直接拒绝。"""

    model_config = ConfigDict(extra="forbid")

    time_range: BacktestTimeRange = Field(default_factory=BacktestTimeRange)
    target_role: Literal[
        "行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"
    ] | None = None
    industry: str | None = Field(default=None, max_length=50)
    role_weights: dict[str, float] | None = None
    benchmark: Literal["hs300", "csi500", "shanghai"] = "hs300"
    rebalance_freq: Literal["monthly", "quarterly", "yearly"] = "monthly"
    granularity: Literal["monthly", "quarterly", "yearly"] = "monthly"
    attribution_method: Literal["shapley", "relative_benchmark"] = "shapley"
    factor_config: dict[str, Any] | None = None

    @field_validator("role_weights")
    @classmethod
    def validate_role_weights(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        if value is None:
            return None
        valid_roles = {
            "行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"
        }
        unknown = sorted(set(value) - valid_roles)
        if unknown:
            raise ValueError(f"role_weights 包含无效角色：{unknown}")
        if any(not math.isfinite(weight) or weight < 0 for weight in value.values()):
            raise ValueError("role_weights 必须是非负有限数")
        return value


class BacktestRunRequest(BaseModel):
    """QuantSkills 回测引擎请求（嵌套 query 格式）。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    timestamp: str | None = None
    query: BacktestQuery = Field(
        default_factory=BacktestQuery,
        description="time_range / industry / target_role / role_weights / benchmark / factor_config 等",
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


class AgentFactorConfigRequest(BaseModel):
    """根据自然语言生成因子配置变更预览，不执行回测。"""

    text: str | None = Field(default=None, max_length=2000)
    current_config: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    quick_preferences: dict[str, Any] | None = None
    mode: str = Field(default="llm", pattern="^(mock|llm)$")

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in value:
            if item.get("role") not in {"user", "assistant"}:
                raise ValueError("messages.role 只能是 user 或 assistant")
            content = item.get("content")
            if not isinstance(content, str) or not content.strip() or len(content) > 2000:
                raise ValueError("messages.content 必须是1到2000字符的文本")
        return value

    @field_validator("quick_preferences")
    @classmethod
    def validate_quick_preferences(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        allowed_keys = {"risk_level", "objectives", "focus_roles"}
        unknown = sorted(set(value) - allowed_keys)
        if unknown:
            raise ValueError(f"quick_preferences 包含不支持的字段：{unknown}")
        risk_level = value.get("risk_level")
        if risk_level is not None and risk_level not in {"稳健", "均衡", "进取"}:
            raise ValueError("risk_level 只能是稳健、均衡或进取")
        allowed_objectives = {"控制回撤", "获取超额", "行业轮动", "趋势交易"}
        objectives = value.get("objectives", [])
        if not isinstance(objectives, list) or len(objectives) > 4:
            raise ValueError("objectives 必须是最多4项的数组")
        if any(item not in allowed_objectives for item in objectives):
            raise ValueError("objectives 包含不支持的目标")
        allowed_roles = {"行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"}
        focus_roles = value.get("focus_roles", [])
        if not isinstance(focus_roles, list) or len(focus_roles) > 5:
            raise ValueError("focus_roles 必须是最多5项的数组")
        if any(item not in allowed_roles for item in focus_roles):
            raise ValueError("focus_roles 包含不支持的角色")
        return value


class AgentCredentialRequest(BaseModel):
    """页面临时配置的模型凭证；序列化与错误展示均不返回明文。"""

    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


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
