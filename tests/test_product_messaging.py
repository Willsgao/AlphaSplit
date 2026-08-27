"""对外产品口径回归测试。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_layer.impl.interpreter import BacktestInterpreter
from engine.agentic.role_negotiation import run_role_negotiation


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_COPY_FILES = [
    ROOT / "README.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "双轨分配机制.md",
    ROOT / "engine" / "web" / "index.html",
    ROOT / "engine" / "web" / "app.js",
    ROOT / "agent_layer" / "impl" / "interpreter.py",
    ROOT / "engine" / "agentic" / "role_negotiation.py",
    ROOT / "engine" / "agentic" / "negotiation.py",
    ROOT / "engine" / "agentic" / "agents.py",
    ROOT / "engine" / "agentic" / "evolution.py",
    ROOT / "engine" / "core" / "calculator.py",
    ROOT / "engine" / "core" / "settlement.py",
    ROOT / "backtest" / "web_app.py",
    ROOT / "backtest" / "templates" / "index.html",
    ROOT / "data" / "scenarios" / "hs300_five_roles.json",
    ROOT / "data" / "scenarios" / "quant_fund.json",
    ROOT / "data" / "scenarios" / "credit_model.json",
]


class TestProductMessaging(unittest.TestCase):
    def test_backtest_evidence_charts_are_hidden_until_rendered(self):
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn(
            'id="backtestEvidenceCharts" class="charts-grid sens-grid evidence-charts hidden"',
            index,
        )
        self.assertIn('$("#backtestEvidenceCharts")?.classList.add("hidden")', app)
        self.assertIn('$("#backtestEvidenceCharts")?.classList.remove("hidden")', app)

    def test_web_appendix_only_explains_current_five_role_workflow(self):
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="panel-technical"', index)
        self.assertIn("五角色与40因子", index)
        self.assertIn("32个角色联盟", index)
        self.assertNotIn("李量化", index + app)
        self.assertNotIn("张经理", index + app)
        self.assertNotIn("陈经理", index + app)
        self.assertNotIn('id="panel-attribution"', index)
        self.assertNotIn('id="panel-sensitivity"', index)
        self.assertNotIn('id="panel-compare"', index)
        self.assertNotIn('id="panel-evolution"', index)
        self.assertNotIn('id="panel-formula"', index)

    def test_roadshow_defaults_are_preselected(self):
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('value="demo_roadshow_2024h2_2025h1" selected', index)
        self.assertIn('id="btUseCache" checked', index)
        self.assertIn('id="btStart" value="2024-07-01"', index)
        self.assertIn('id="btEnd" value="2025-06-30"', index)
        self.assertIn('risk_level: "稳健"', app)
        self.assertIn('objectives: ["控制回撤"]', app)
        self.assertIn('focus_roles: ["风控分析师"]', app)
        self.assertIn("我计划中长期持有，风险偏好稳健", index)

    def test_frontend_metrics_have_traceable_explanation_drawer(self):
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="metricExplainOverlay"', index)
        self.assertIn('id="metricExplainBody"', index)
        for key in ("excess_return", "sharpe_ratio", "max_drawdown", "top_role"):
            self.assertIn(f'data-explain-key="{key}"', index)

        self.assertIn("function buildOverviewExplanation", app)
        self.assertIn("function buildRoleExplanation", app)
        self.assertIn("function buildFactorExplanation", app)
        self.assertIn("function buildDualPoolExplanation", app)
        self.assertIn("function buildComparisonExplanation", app)
        self.assertIn("function buildSettlementExplanation", app)
        self.assertIn("超额收益 = 组合累计收益 - 沪深300累计收益", app)
        self.assertIn("年化收益 - 2%", app)
        self.assertIn("v(S)=R(S)-R(沪深300)", app)
        self.assertIn("60% × 制度轨现行份额 + 40% × 证据轨建议份额", app)
        self.assertIn("configured_max_role_weight", app)
        self.assertIn("effective_max_role_weight", app)
        self.assertIn("正贡献角色不足", app)
        self.assertIn("state.agentEvidence = cloneJson", app)

    def test_demo_and_live_backtests_render_strategy_comparison(self):
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        demo = json.loads(
            (ROOT / "engine" / "web" / "demo" / "backtest_demo.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("if (data.comparison)", app)
        self.assertIn("async function attachLatestDemoComparison", app)
        self.assertIn("data = await attachLatestDemoComparison(data)", app)
        self.assertIn('cache: "no-store"', app)
        self.assertIn("renderPlanComparison(state.backtestComparison)", app)
        self.assertIn("function renderPlanComparisonChart", app)
        self.assertIn("function buildComparisonCurveData", app)
        self.assertIn("buildComparisonCurveData(state.backtestComparison)", app)
        self.assertIn("renderPlanComparisonChart(comparison);\n    updateNavLiveChart();", app)
        self.assertIn('id="planComparisonChart"', app)
        self.assertIn('data: ["新策略", "原始默认策略", "HS300"]', app)
        self.assertIn("三方案累计收益对比", index)
        self.assertIn("if (state.factorDefaultConfig)", app)
        self.assertNotIn(
            "if (state.factorConfigAudit && state.factorDefaultConfig)", app
        )
        self.assertIn("comparison", demo)
        comparison = demo["comparison"]
        self.assertEqual(comparison["source"], "precomputed_verified_pair")
        self.assertTrue(comparison["same_scope"])
        self.assertIn("customer", comparison)
        self.assertIn("default", comparison)
        self.assertIn("benchmark", comparison)
        self.assertTrue(comparison["customer_time_series"])
        self.assertTrue(comparison["default_time_series"])
        self.assertEqual(
            [row["period"] for row in comparison["customer_time_series"]],
            [row["period"] for row in comparison["default_time_series"]],
        )
        self.assertNotEqual(
            comparison["customer"]["total_return"],
            comparison["default"]["total_return"],
        )

    def test_first_time_user_has_one_guided_four_step_flow(self):
        index = (ROOT / "engine" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "engine" / "web" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "engine" / "web" / "style.css").read_text(encoding="utf-8")

        self.assertIn('id="selfGuide"', index)
        self.assertIn("第一次使用，从这里开始", index)
        for label in ("描述投资需求", "确认Agent方案", "回测并理解结果", "形成应用建议"):
            self.assertIn(label, index)
        self.assertIn('id="btnGuidePrimary"', index)
        self.assertIn('id="btnGuidedDemo"', index)
        self.assertIn('id="btnGuidedBacktest"', index)
        self.assertIn('id="btnStartGuidedNegotiate"', app)
        self.assertIn("让五个投资角色基于这套证据展开协商", app)
        self.assertIn("采用当前输入作为协商基准", app)
        self.assertIn("纯新方案比例", app)
        self.assertIn("仅40%证据轨内部", app)
        self.assertIn("最终合成方案人工确认（占总资源池）", app)
        self.assertIn("已经包含60%原有方案和40%纯新方案", app)
        self.assertIn("function setNextActionCue", app)
        self.assertIn('history.scrollRestoration = "manual"', app)
        self.assertIn("function revealCurrentNextAction", app)
        self.assertIn('window.addEventListener("pageshow"', app)
        self.assertGreaterEqual(app.count('setNextActionCue("#btnGuidedDemo")'), 2)
        self.assertIn(".btn.is-next-action:not(:disabled)", style)
        self.assertIn('data-label="纯新方案 · 证据轨内部"', app)
        self.assertIn(".share-row > span:first-child", style)
        self.assertIn('id="agentPanel" class="agent-panel advanced-only"', index)
        self.assertIn("function setGuidedStage", app)
        self.assertIn('setGuidedStage("confirm")', app)
        self.assertIn('setGuidedStage("backtest")', app)
        self.assertIn('setGuidedStage("apply")', app)
        self.assertIn('setGuidedStage("complete")', app)
        self.assertIn(".advanced-only { display: none !important; }", style)

    def test_public_copy_uses_broad_allocation_language(self):
        narrow_terms = ("薪资", "发薪", "工资", "薪酬", "奖金", "落账")
        violations: list[str] = []
        for path in PUBLIC_COPY_FILES:
            text = path.read_text(encoding="utf-8")
            for term in narrow_terms:
                if term in text:
                    violations.append(f"{path.relative_to(ROOT)}: {term}")

        self.assertEqual(
            violations,
            [],
            "对外口径应强调广义价值分配，不应包含狭义报酬术语：\n"
            + "\n".join(violations),
        )

    def test_generated_copy_uses_broad_allocation_language(self):
        backtest = json.loads(
            (ROOT / "engine" / "web" / "demo" / "backtest_demo.json").read_text(
                encoding="utf-8"
            )
        )
        negotiation = run_role_negotiation(backtest)
        report = BacktestInterpreter().interpret(backtest)
        generated = json.dumps(negotiation, ensure_ascii=False) + "\n" + json.dumps(
            report.to_dict(), ensure_ascii=False
        )

        narrow_terms = ("薪资", "发薪", "工资", "薪酬", "奖金", "落账")
        found = [term for term in narrow_terms if term in generated]
        self.assertEqual(found, [], f"运行态生成文案仍含狭义报酬术语：{found}")


if __name__ == "__main__":
    unittest.main()
