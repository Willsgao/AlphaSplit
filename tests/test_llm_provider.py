"""DeepSeek/OpenAI兼容调用层的可靠性与安全测试。"""
from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from agent_layer.impl.llm import (
    LLMProviderError,
    call_llm,
    clear_runtime_api_key,
    configure_runtime_api_key,
    get_last_llm_call,
    llm_status,
)


def _success(content: str = '{"ok":true}') -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


def _http_error(code: int, body: bytes = b"error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid", code, "error", hdrs=None, fp=io.BytesIO(body)
    )


class TestLLMProvider(unittest.TestCase):
    def tearDown(self):
        clear_runtime_api_key()

    def _env(self, **overrides):
        values = {
            "DEEPSEEK_API_KEY": "test-secret-never-return",
            "DEEPSEEK_BASE_URL": "https://example.invalid",
            "AGENT_LAYER_LLM_MODEL": "deepseek-chat",
            "AGENT_LAYER_LLM_MAX_RETRIES": "1",
            "AGENT_LAYER_LLM_RETRY_BACKOFF": "0",
        }
        values.update(overrides)
        return patch.dict(os.environ, values, clear=True)

    def test_retryable_http_error_retries_and_records_metadata(self):
        with self._env(), patch(
            "urllib.request.urlopen",
            side_effect=[_http_error(429), FakeResponse(_success())],
        ) as mocked:
            result = call_llm([{"role": "user", "content": "test"}])

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(mocked.call_count, 2)
        metadata = get_last_llm_call()
        self.assertEqual(metadata["status"], "success")
        self.assertEqual(metadata["attempts"], 2)

    def test_runtime_key_takes_precedence_and_can_be_cleared(self):
        with self._env(DEEPSEEK_API_KEY="environment-secret"):
            configured = configure_runtime_api_key("runtime-secret-value")
            self.assertTrue(configured["available"])
            self.assertEqual(configured["provider"], "deepseek")
            self.assertEqual(configured["credential_source"], "runtime")
            self.assertNotIn("runtime-secret-value", json.dumps(configured))

            cleared = clear_runtime_api_key()
            self.assertEqual(cleared["credential_source"], "environment")
            self.assertNotIn("environment-secret", json.dumps(cleared))

    def test_no_key_status_is_public_and_secret_free(self):
        with patch.dict(os.environ, {}, clear=True):
            clear_runtime_api_key()
            status = llm_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["credential_source"], "none")

    def test_json_schema_rejection_falls_back_to_json_object(self):
        error = _http_error(400, b"response_format json_schema unsupported")
        schema = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": {"type": "object"}},
        }
        with self._env(AGENT_LAYER_LLM_MAX_RETRIES="0"), patch(
            "urllib.request.urlopen",
            side_effect=[error, FakeResponse(_success())],
        ) as mocked:
            call_llm([{"role": "user", "content": "test"}], response_format=schema)

        second_request = mocked.call_args_list[1].args[0]
        second_body = json.loads(second_request.data.decode("utf-8"))
        self.assertEqual(second_body["response_format"], {"type": "json_object"})
        metadata = get_last_llm_call()
        self.assertTrue(metadata["fallback_used"])
        self.assertEqual(metadata["response_format"], "json_object")

    def test_timeout_is_structured_after_bounded_retry(self):
        with self._env(), patch(
            "urllib.request.urlopen", side_effect=[TimeoutError(), TimeoutError()]
        ) as mocked:
            with self.assertRaises(LLMProviderError) as caught:
                call_llm([{"role": "user", "content": "test"}])

        self.assertEqual(caught.exception.code, "LLM_TIMEOUT")
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(get_last_llm_call()["error_code"], "LLM_TIMEOUT")

    def test_http_error_does_not_expose_key_or_response_body(self):
        body = b"credential test-secret-never-return is invalid"
        with self._env(), patch(
            "urllib.request.urlopen", side_effect=_http_error(401, body)
        ):
            with self.assertRaises(LLMProviderError) as caught:
                call_llm([{"role": "user", "content": "test"}])

        message = str(caught.exception)
        self.assertNotIn("test-secret-never-return", message)
        self.assertNotIn("credential", message)
        self.assertEqual(caught.exception.code, "LLM_HTTP_401")

    def test_invalid_service_payload_is_rejected(self):
        with self._env(), patch(
            "urllib.request.urlopen", return_value=FakeResponse(b"not-json")
        ):
            with self.assertRaises(LLMProviderError) as caught:
                call_llm([{"role": "user", "content": "test"}])
        self.assertEqual(caught.exception.code, "LLM_INVALID_RESPONSE")


if __name__ == "__main__":
    unittest.main()
