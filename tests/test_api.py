"""FastAPI 接口边界与运行保护测试。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import engine.api.main as api_main
from agent_layer.impl.llm import clear_runtime_api_key


app = api_main.app


class TestBacktestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def tearDown(self):
        clear_runtime_api_key()

    def test_health_contract(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_factor_config_meta_contract(self):
        response = self.client.get("/api/agent/factor-config")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["roles"]), 5)
        self.assertEqual(sum(len(role["factors"]) for role in payload["roles"]), 40)
        self.assertEqual(payload["default_config"]["config_id"], "diversified_defensive_v4")
        self.assertIn("available", payload["agent"])
        self.assertIn("provider", payload["agent"])
        self.assertIn("model", payload["agent"])
        self.assertTrue(payload["agent"]["offline_cache"]["available"])
        self.assertGreaterEqual(payload["agent"]["offline_cache"]["response_count"], 1)

    def test_page_can_configure_and_clear_process_memory_api_key(self):
        secret = "test-runtime-secret-never-return"
        with patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": ""},
            clear=False,
        ):
            configured = self.client.put(
                "/api/agent/credentials", json={"api_key": secret}
            )
            self.assertEqual(configured.status_code, 200, configured.text)
            self.assertTrue(configured.json()["agent"]["available"])
            self.assertEqual(
                configured.json()["agent"]["credential_source"], "runtime"
            )
            self.assertNotIn(secret, configured.text)

            status = self.client.get("/api/agent/factor-config")
            self.assertEqual(status.json()["agent"]["credential_source"], "runtime")
            self.assertNotIn(secret, status.text)

            cleared = self.client.delete("/api/agent/credentials")
            self.assertEqual(cleared.status_code, 200, cleared.text)
            self.assertFalse(cleared.json()["agent"]["available"])
            self.assertEqual(cleared.json()["agent"]["credential_source"], "none")

    def test_short_page_api_key_is_rejected_without_echoing_value(self):
        secret = "too-short"
        response = self.client.put(
            "/api/agent/credentials", json={"api_key": secret}
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)

    def test_factor_config_proposal_requires_confirmation_and_validates_input(self):
        response = self.client.post(
            "/api/agent/factor-config",
            json={"text": "我偏稳健，希望加强风控并降低波动", "mode": "mock"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["changes"])
        self.assertTrue(response.json()["requires_confirmation"])
        self.assertIn("audit_id", response.json()["audit"])
        self.assertEqual(
            response.json()["audit"]["config_after"],
            response.json()["config"]["config_id"].removeprefix("client_"),
        )
        factor_changes = {
            item["factor"]: item
            for item in response.json()["changes"]
            if item.get("factor")
        }
        self.assertEqual(factor_changes["risk_down_vol_5d"]["direction"], -1)
        self.assertEqual(
            response.json()["config"]["roles"]["策略分析师"]["module_params"]["target_vol"],
            0.10,
        )

        with patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": ""},
            clear=False,
        ):
            cached = self.client.post(
                "/api/agent/factor-config",
                json={
                    "text": "我计划中长期持有，希望优先控制最大回撤并加强风控。",
                    "mode": "llm",
                    "quick_preferences": {
                        "risk_level": "稳健",
                        "objectives": ["控制回撤"],
                        "focus_roles": ["风控分析师"],
                    },
                },
            )
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json()["source"], "agent_cache")
        self.assertEqual(cached.json()["cache"]["id"], "steady_drawdown_control")
        self.assertTrue(cached.json()["changes"])

        invalid = self.client.post(
            "/api/agent/factor-config",
            json={
                "text": "调整",
                "current_config": {
                    "roles": {"风控分析师": {"factor_weights": {"unknown": 1}}}
                },
            },
        )
        self.assertEqual(invalid.status_code, 422)

        invalid_preferences = self.client.post(
            "/api/agent/factor-config",
            json={
                "text": "调整",
                "mode": "mock",
                "quick_preferences": {"risk_level": "绝对保本"},
            },
        )
        self.assertEqual(invalid_preferences.status_code, 422)

    def test_demo_run_accepts_structured_query(self):
        response = self.client.post(
            "/api/backtest/run",
            json={
                "demo_mode": True,
                "query": {
                    "time_range": {
                        "start_date": "2024-01-01",
                        "end_date": "2024-06-30",
                    },
                    "benchmark": "hs300",
                    "rebalance_freq": "monthly",
                },
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("results", response.json())

    def test_unknown_query_field_is_rejected(self):
        response = self.client.post(
            "/api/backtest/run",
            json={"demo_mode": True, "query": {"benchmrak": "hs300"}},
        )

        self.assertEqual(response.status_code, 422)

    def test_reversed_date_range_is_rejected(self):
        response = self.client.post(
            "/api/backtest/run",
            json={
                "demo_mode": True,
                "query": {
                    "time_range": {
                        "start_date": "2024-07-01",
                        "end_date": "2024-06-30",
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_second_backtest_is_rejected_while_one_is_running(self):
        acquired = api_main._backtest_run_lock.acquire(blocking=False)
        self.assertTrue(acquired, "测试开始时回测锁应为空闲")
        try:
            response = self.client.post(
                "/api/backtest/run",
                json={"demo_mode": True, "query": {}},
            )
        finally:
            api_main._backtest_run_lock.release()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error_code"], "BACKTEST_BUSY")

    def test_public_demo_mode_blocks_history_and_real_run(self):
        with patch.dict("os.environ", {"ALPHASPLIT_PUBLIC_DEMO_ONLY": "1"}, clear=False):
            demo = self.client.get("/api/backtest/demo")
            history = self.client.get("/api/backtest/results")
            run = self.client.post("/api/backtest/run", json={"query": {}})

        self.assertEqual(demo.status_code, 200)
        self.assertEqual(history.status_code, 403)
        self.assertEqual(run.status_code, 403)

    def test_configured_token_protects_backtest_history(self):
        with patch.dict("os.environ", {"ALPHASPLIT_API_TOKEN": "test-secret"}, clear=False):
            denied = self.client.get("/api/backtest/results")
            allowed = self.client.get(
                "/api/backtest/results",
                headers={"X-AlphaSplit-Token": "test-secret"},
            )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
