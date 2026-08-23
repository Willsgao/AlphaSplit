"""回测结果解读 Agent。"""

from __future__ import annotations

from typing import Any

from agent_layer.contracts import AgentMode, AgentReport, BacktestPlan
from agent_layer.impl.llm import call_llm, llm_available


class BacktestInterpreter:
    def interpret(
        self,
        backtest: dict[str, Any],
        plan: BacktestPlan | None = None,
        *,
        mode: AgentMode = "mock",
    ) -> AgentReport:
        if backtest.get("status") != "success":
            msg = backtest.get("error_message") or "回测未成功"
            return AgentReport(
                headline="回测未完成",
                body=msg,
                bullets=[],
                mode=mode,
            )

        results = backtest.get("results") or {}
        ov = results.get("overview") or {}
        breakdown = sorted(
            results.get("role_breakdown") or [],
            key=lambda r: (r.get("weight") or 0),
            reverse=True,
        )
        top = breakdown[0] if breakdown else None
        bottom = breakdown[-1] if breakdown else None

        excess = float(ov.get("excess_return") or 0)
        excess_pct = excess * 100
        beat = excess > 0

        headline = (
            f"区间超额 {excess_pct:+.2f}%（{'跑赢' if beat else '未跑赢'}基准）"
            if ov.get("excess_return") is not None
            else "回测完成"
        )

        bullets: list[str] = []
        if top:
            bullets.append(
                f"夏普利贡献最高：{top['role']}（新池建议权重 {(top.get('weight', 0) * 100):.1f}%）"
            )
        if bottom and (bottom.get("shapley_raw") or 0) < 0:
            bullets.append(
                f"需复盘：{bottom['role']} 呈负向拖累（夏普利 {(bottom.get('shapley_raw', 0) * 100):.2f}%）"
            )
        rec = (results.get("recommendation") or {}).get("summary")
        if rec:
            bullets.append(rec)

        dual_pool_note = (
            "分配落地采用 6:4 双轨：60% 沿用机构现行方案，40% 按本回测夏普利新池建议合成；"
            "请在「人工确认」页核对后落账，非自动发薪。"
        )

        body = self._mock_body(breakdown, ov, plan)
        focus_role = top["role"] if top else None

        if mode == "llm" and llm_available():
            llm_body = self._llm_body(backtest, plan)
            if llm_body:
                body = llm_body
                mode = "llm"

        return AgentReport(
            headline=headline,
            body=body,
            bullets=bullets[:5],
            focus_role=focus_role,
            dual_pool_note=dual_pool_note,
            mode=mode,
        )

    @staticmethod
    def _mock_body(
        breakdown: list[dict],
        ov: dict,
        plan: BacktestPlan | None,
    ) -> str:
        lines = ["【Agent 解读】基于 HS300 真实回测与夏普利反事实归因："]
        if plan:
            lines.append(f"规划摘要：{plan.summary}。")
        total = float(ov.get("total_return") or 0) * 100
        sharpe = float(ov.get("sharpe_ratio") or 0)
        lines.append(f"组合累计收益约 {total:.2f}%，夏普 {sharpe:.2f}。")
        if breakdown:
            rank = " > ".join(r["role"] for r in breakdown[:3])
            lines.append(f"新池 40% 建议权重排序：{rank}。")
        lines.append(
            "以上为贡献计量证据；制度偏好与现行分配请在人工确认环节与 6:4 合成方案一并审议。"
        )
        return "\n".join(lines)

    @staticmethod
    def _llm_body(backtest: dict[str, Any], plan: BacktestPlan | None) -> str | None:
        try:
            results = backtest.get("results") or {}
            prompt = (
                "你是资管绩效考核解读 Agent。根据下列回测 JSON 摘要，用中文写 120~200 字结论，"
                "说明各角色夏普利贡献与考核建议，强调非自动发薪。\n"
                f"规划：{plan.summary if plan else '—'}\n"
                f"overview：{results.get('overview')}\n"
                f"role_breakdown：{results.get('role_breakdown')}\n"
            )
            return call_llm(
                [
                    {"role": "system", "content": "严谨、可解释、避免过度因果承诺。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            return None
