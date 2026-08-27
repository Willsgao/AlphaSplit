"""agent_layer 单元测试。"""
from __future__ import annotations

import unittest

from agent_layer.impl.nl_parser import parse_natural_language
from agent_layer.impl.planner import BacktestPlanner
from agent_layer.registry import create_runtime


class TestAgentPlanner(unittest.TestCase):
    def test_preset_demo(self):
        planner = BacktestPlanner()
        plan = planner.plan(preset_id="demo_roadshow_2024h2_2025h1")
        self.assertEqual(plan.query["time_range"]["start_date"], "2024-07-01")
        self.assertEqual(plan.source, "preset")

    def test_nl_semiconductor(self):
        q = parse_natural_language("2024上半年半导体板块回测")
        self.assertEqual(q["time_range"]["end_date"], "2024-06-30")
        self.assertEqual(q["industry"], "半导体")

    def test_nl_role_weight(self):
        q = parse_natural_language("全市场，偏重行业分析师")
        self.assertIn("行业分析师", q.get("role_weights", {}))


class TestAgentRuntime(unittest.TestCase):
    def test_plan_only_pipeline(self):
        rt = create_runtime(meta={"industries": ["半导体"]})
        result = rt.run_pipeline(preset_id="demo_roadshow_2024h2_2025h1")
        self.assertEqual(result.status, "planned")
        self.assertIsNotNone(result.plan)

    def test_interpret_demo_json(self):
        import json
        from pathlib import Path

        demo_path = Path(__file__).resolve().parents[1] / "engine" / "web" / "demo" / "backtest_demo.json"
        if not demo_path.exists():
            self.skipTest("demo json missing")
        data = json.loads(demo_path.read_text(encoding="utf-8"))
        rt = create_runtime()
        plan = rt.plan_backtest(preset_id="demo_roadshow_2024h2_2025h1")
        report = rt.interpret_backtest(data, plan)
        self.assertIn("夏普利", report.body)
        self.assertTrue(report.dual_pool_note)

    def test_interpreter_describes_zero_excess_as_flat(self):
        rt = create_runtime()
        report = rt.interpret_backtest({
            "status": "success",
            "results": {
                "overview": {"total_return": 0.0, "excess_return": 0.0},
                "role_breakdown": [],
            },
        })
        self.assertIn("基本持平", report.headline)


if __name__ == "__main__":
    unittest.main()
