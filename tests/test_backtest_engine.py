"""回测引擎集成测试。"""
from __future__ import annotations

import unittest

from engine.integrations.quantskills_backtest import (
    cache_key_from_query,
    data_available,
    get_demo_result,
    get_meta,
    normalize_request,
)


class TestQuantSkillsBacktest(unittest.TestCase):
    def test_data_available(self):
        self.assertTrue(data_available(), "data/processed 应随仓库提供")

    def test_meta_roles(self):
        meta = get_meta()
        self.assertIn("行业分析师", meta["roles"])
        self.assertEqual(meta["default_benchmark"], "hs300")
        self.assertIn("demo", meta)

    def test_demo_bundle_available(self):
        demo = get_demo_result()
        self.assertIsNotNone(demo, "路演演示包应随仓库提供")
        self.assertEqual(demo.get("_source"), "demo")
        self.assertIn("results", demo)
        self.assertIn("demo_replay", demo)

    def test_cache_key_stable(self):
        q = {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
        }
        k1 = cache_key_from_query(q)
        k2 = cache_key_from_query(q)
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 16)

    def test_normalize_nested_request(self):
        raw = {
            "request_id": "t1",
            "query": {"time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"}},
        }
        out = normalize_request(raw)
        self.assertEqual(out["request_id"], "t1")
        self.assertIn("query", out)

    def test_normalize_flat_request(self):
        raw = {"start_date": "2024-01-01", "end_date": "2024-06-30", "benchmark": "hs300"}
        out = normalize_request(raw)
        self.assertEqual(out["query"]["benchmark"], "hs300")


if __name__ == "__main__":
    unittest.main()
