"""回测规划 Agent（规则 / 预设 / 可选 LLM）。"""

from __future__ import annotations

from typing import Any

from agent_layer.contracts import AgentMode, BacktestPlan, PlanStep
from agent_layer.impl.llm import llm_plan_query
from agent_layer.impl.nl_parser import parse_natural_language
from agent_layer.impl.presets import PRESETS


class BacktestPlanner:
    def __init__(self, meta: dict[str, Any] | None = None):
        self.meta = meta or {}

    def list_presets(self) -> list[dict[str, str]]:
        return [{"id": k, "label": v["label"]} for k, v in PRESETS.items()]

    def plan(
        self,
        *,
        text: str | None = None,
        preset_id: str | None = None,
        query_override: dict[str, Any] | None = None,
        mode: AgentMode = "mock",
    ) -> BacktestPlan:
        industries = self.meta.get("industries") or []

        if preset_id and preset_id in PRESETS:
            preset = PRESETS[preset_id]
            query = dict(preset["query"])
            if query_override:
                query.update(query_override)
            return BacktestPlan(
                query=query,
                summary=preset["summary"],
                reasoning=f"采用内置预设「{preset['label']}」，参数稳定可复现。",
                steps=self._default_steps(),
                preset_id=preset_id,
                source="preset",
            )

        query: dict[str, Any]
        source = "rule"
        reasoning_parts: list[str] = []

        if mode == "llm" and text:
            llm_query = llm_plan_query(text, self.meta)
            if llm_query:
                query = llm_query
                source = "llm"
                reasoning_parts.append("LLM 解析用户需求并生成 query JSON。")
            else:
                query = parse_natural_language(text, valid_industries=industries)
                reasoning_parts.append("LLM 不可用或解析失败，已回退规则引擎。")
        else:
            query = parse_natural_language(text or "", valid_industries=industries)
            reasoning_parts.append("规则引擎解析关键词（日期/行业/角色偏好）。")

        if query_override:
            query.update(query_override)
            reasoning_parts.append("已合并 API 传入的 query 覆盖项。")

        tr = query.get("time_range") or {}
        summary_bits = [
            f"{tr.get('start_date', '?')}~{tr.get('end_date', '?')}",
            query.get("industry") or "全行业",
            query.get("rebalance_freq") or "monthly",
        ]
        if query.get("target_role"):
            summary_bits.append(f"聚焦{query['target_role']}")
        if query.get("role_weights"):
            summary_bits.append("含制度调节系数")

        return BacktestPlan(
            query=query,
            summary="，".join(str(x) for x in summary_bits),
            reasoning="".join(reasoning_parts)
            + " 计量仍由 query_engine 执行，Agent 不直接计算夏普利值。",
            steps=self._default_steps(),
            source=source,
        )

    @staticmethod
    def _default_steps() -> list[PlanStep]:
        return [
            PlanStep("parse", "解析任务", "将业务问题映射为可执行 query（日期/行业/角色）"),
            PlanStep("factors", "五角色因子选股", "各行业/个股/策略/量化/风控因子套壳代理"),
            PlanStep("pipeline", "组合回测", "月度调仓模拟组合收益"),
            PlanStep("shapley", "夏普利反事实", "31 子集联盟边际贡献"),
            PlanStep("report", "解读与建议", "生成业务可读报告，供 6:4 人工确认"),
        ]
