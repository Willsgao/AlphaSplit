"""回测结果解读 Agent。"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_layer.contracts import AgentMode, AgentReport, BacktestPlan
from agent_layer.impl.evidence import build_backtest_evidence
from agent_layer.impl.llm import (
    call_llm,
    get_last_llm_call,
    llm_available,
    reset_llm_call_metadata,
)


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

        evidence = build_backtest_evidence(backtest)
        ov = evidence["overview"]
        roles = evidence["roles"]
        breakdown = sorted(
            [item for item in roles if item.get("weight") is not None],
            key=lambda r: r["weight"],
            reverse=True,
        )
        shapley_roles = sorted(
            [item for item in roles if item.get("shapley_raw") is not None],
            key=lambda r: r["shapley_raw"],
        )
        top = breakdown[0] if breakdown else None
        bottom = shapley_roles[0] if shapley_roles else None

        excess = float(ov.get("excess_return") or 0)
        excess_pct = excess * 100
        if ov.get("excess_return") is None:
            headline = "回测完成"
        elif excess > 0.00005:
            headline = f"区间超额 {excess_pct:+.2f}%（跑赢基准）"
        elif excess < -0.00005:
            headline = f"区间超额 {excess_pct:+.2f}%（跑输基准）"
        else:
            headline = f"区间超额 {excess_pct:+.2f}%（与基准基本持平）"

        bullets: list[str] = []
        if top:
            bullets.append(
                f"新池建议权重最高：{top['role']}（{(top['weight'] * 100):.1f}%）"
            )
        if bottom and (bottom.get("shapley_raw") or 0) < 0:
            bullets.append(
                f"需复盘：{bottom['role']} 呈负向拖累（夏普利 {(bottom.get('shapley_raw', 0) * 100):.2f}%）"
            )
        if evidence["warnings"]:
            bullets.append(
                f"可信边界检查发现 {len(evidence['warnings'])} 项异常字段，已从 Agent 证据中排除。"
            )
        dual_pool_note = (
            "分配落地采用 6:4 双轨：60% 沿用机构现行方案，40% 按本回测夏普利新池建议合成；"
            "可用于预算、研究资源、项目机会、数据/算力额度和激励权益等广义分配，须在「人工确认」页核对后应用。"
        )

        body = self._mock_body(breakdown, ov, plan)
        focus_role = top["role"] if top else None
        effective_mode = "mock"
        llm_audit: dict[str, Any] = {
            "requested_mode": mode,
            "used": False,
            "fallback_used": mode == "llm",
        }

        if mode == "llm" and llm_available():
            llm_body, call_metadata = self._llm_body(evidence, plan)
            llm_audit["call"] = call_metadata
            if llm_body:
                body = llm_body
                effective_mode = "llm"
                llm_audit.update({"used": True, "fallback_used": False})
        elif mode == "llm":
            llm_audit["reason"] = "LLM_NOT_CONFIGURED"

        return AgentReport(
            headline=headline,
            body=body,
            bullets=bullets[:5],
            focus_role=focus_role,
            dual_pool_note=dual_pool_note,
            mode=effective_mode,
            trust={
                "status": evidence["status"],
                "warnings": evidence["warnings"],
                "excluded_fields": evidence["excluded_fields"],
            },
            evidence=evidence["items"],
            llm_audit=llm_audit,
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
        metrics: list[str] = []
        if ov.get("total_return") is not None:
            metrics.append(f"组合累计收益约 {float(ov['total_return']) * 100:.2f}%")
        if ov.get("sharpe_ratio") is not None:
            metrics.append(f"夏普 {float(ov['sharpe_ratio']):.2f}")
        if metrics:
            lines.append("，".join(metrics) + "。")
        else:
            lines.append("关键绩效指标未通过证据校验，本次不作数值解读。")
        if breakdown:
            rank = " > ".join(r["role"] for r in breakdown[:3])
            lines.append(f"新池 40% 建议权重排序：{rank}。")
        lines.append(
            "以上为贡献计量证据；制度偏好与现行分配请在人工确认环节与 6:4 合成方案一并审议。"
        )
        return "\n".join(lines)

    @staticmethod
    def _llm_body(
        evidence: dict[str, Any], plan: BacktestPlan | None
    ) -> tuple[str | None, dict[str, Any] | None]:
        reset_llm_call_metadata()
        try:
            prompt = (
                "你是资管回测解读 Agent。只能使用下列已校验证据，用中文写120到200字结论。"
                "涉及数字时在句末标注对应证据ID，例如[E001]；不得补充证据中不存在的数字，"
                "不得承诺未来收益。说明各角色Shapley贡献与广义价值分配建议，并强调方案须经人工确认。\n"
                f"规划：{plan.summary if plan else '—'}\n"
                f"证据：{json.dumps(evidence['items'], ensure_ascii=False, separators=(',', ':'))}\n"
                f"校验警告：{json.dumps(evidence['warnings'], ensure_ascii=False, separators=(',', ':'))}\n"
            )
            content = call_llm(
                [
                    {"role": "system", "content": "严谨、可解释、避免过度因果承诺。"},
                    {"role": "user", "content": prompt},
                ]
            )
            return BacktestInterpreter._validate_llm_body(content, evidence), get_last_llm_call()
        except Exception:
            return None, get_last_llm_call()

    @staticmethod
    def _validate_llm_body(content: str, evidence: dict[str, Any]) -> str:
        text = (content or "").strip()
        if not text or len(text) > 1200:
            raise ValueError("LLM_ANALYSIS_LENGTH_INVALID")
        allowed_ids = {item["id"] for item in evidence.get("items") or []}
        cited_ids = set(re.findall(r"E\d{3}", text))
        if not cited_ids.issubset(allowed_ids):
            raise ValueError("LLM_ANALYSIS_UNKNOWN_EVIDENCE")
        if re.search(r"\d", text) and not cited_ids:
            raise ValueError("LLM_ANALYSIS_EVIDENCE_REQUIRED")
        if any(term in text for term in ("保证收益", "稳赚", "无风险收益", "必然跑赢")):
            raise ValueError("LLM_ANALYSIS_PROMISE_REJECTED")
        return text
