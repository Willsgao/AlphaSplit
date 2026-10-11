"""可选 LLM 增强（与 engine/agentic 解耦，队员可替换）。"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Optional


RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMCallMetadata:
    provider: str
    model: str
    status: str
    duration_ms: float
    attempts: int
    response_format: str | None
    fallback_used: bool = False
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProviderError(RuntimeError):
    """不包含凭证和完整响应正文的结构化模型调用错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_last_call: ContextVar[LLMCallMetadata | None] = ContextVar(
    "alphasplit_last_llm_call", default=None
)
_runtime_key_lock = threading.RLock()
_runtime_api_key: str | None = None


def reset_llm_call_metadata() -> None:
    _last_call.set(None)


def get_last_llm_call() -> dict[str, Any] | None:
    value = _last_call.get()
    return value.to_dict() if value else None


def configure_runtime_api_key(api_key: str) -> dict[str, Any]:
    """仅在当前服务进程内保存 DeepSeek Key。"""
    key = api_key.strip()
    if len(key) < 10 or len(key) > 512:
        raise ValueError("API Key 长度应为 10 到 512 个字符")
    global _runtime_api_key
    with _runtime_key_lock:
        _runtime_api_key = key
    return llm_status()


def clear_runtime_api_key() -> dict[str, Any]:
    """清除页面配置的 Key；环境变量（如有）不受影响。"""
    global _runtime_api_key
    with _runtime_key_lock:
        _runtime_api_key = None
    return llm_status()


def _active_api_key() -> tuple[str | None, str, str]:
    with _runtime_key_lock:
        runtime_key = _runtime_api_key
    if runtime_key:
        return runtime_key, "deepseek", "runtime"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"], "deepseek", "environment"
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"], "openai_compatible", "environment"
    return None, "none", "none"


def llm_available() -> bool:
    key, _, _ = _active_api_key()
    return bool(key)


def llm_status() -> dict[str, Any]:
    """返回可公开的模型状态，不暴露 Key 或完整服务地址。"""
    key, provider, credential_source = _active_api_key()
    return {
        "available": bool(key),
        "provider": provider,
        "model": os.environ.get("AGENT_LAYER_LLM_MODEL", "deepseek-chat"),
        "credential_source": credential_source,
    }


def call_llm(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    response_format: dict[str, Any] | None = None,
) -> str:
    key, provider, _ = _active_api_key()
    if not key:
        raise LLMProviderError("LLM_NOT_CONFIGURED", "未配置 LLM API Key")

    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("AGENT_LAYER_LLM_MODEL", "deepseek-chat")
    timeout = max(5.0, min(float(os.environ.get("AGENT_LAYER_LLM_TIMEOUT", "60")), 120.0))
    max_retries = max(0, min(int(os.environ.get("AGENT_LAYER_LLM_MAX_RETRIES", "1")), 3))
    backoff = max(0.0, min(float(os.environ.get("AGENT_LAYER_LLM_RETRY_BACKOFF", "0.25")), 2.0))
    current_format = dict(response_format) if response_format else None
    fallback_used = False
    retry_count = 0
    attempts = 0
    started = time.monotonic()
    reset_llm_call_metadata()

    def finish(status: str, error_code: str | None = None) -> None:
        _last_call.set(LLMCallMetadata(
            provider=provider,
            model=model,
            status=status,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            attempts=attempts,
            response_format=(current_format or {}).get("type"),
            fallback_used=fallback_used,
            error_code=error_code,
        ))

    while True:
        attempts += 1
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if current_format:
            body["response_format"] = current_format
        req = urllib.request.Request(
            f"{base.rstrip('/')}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace").lower()
            except Exception:
                detail = ""
            schema_rejected = (
                current_format is not None
                and current_format.get("type") == "json_schema"
                and not fallback_used
                and exc.code == 400
                and ("json_schema" in detail or "response_format" in detail)
            )
            if schema_rejected:
                current_format = {"type": "json_object"}
                fallback_used = True
                continue
            if exc.code in RETRYABLE_HTTP_STATUS and retry_count < max_retries:
                retry_count += 1
                if backoff:
                    time.sleep(backoff * retry_count)
                continue
            code = f"LLM_HTTP_{exc.code}"
            finish("error", code)
            raise LLMProviderError(code, f"模型服务返回 HTTP {exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            if retry_count < max_retries:
                retry_count += 1
                if backoff:
                    time.sleep(backoff * retry_count)
                continue
            finish("error", "LLM_TIMEOUT")
            raise LLMProviderError("LLM_TIMEOUT", "模型服务请求超时") from exc
        except urllib.error.URLError as exc:
            if retry_count < max_retries:
                retry_count += 1
                if backoff:
                    time.sleep(backoff * retry_count)
                continue
            finish("error", "LLM_CONNECTION_ERROR")
            raise LLMProviderError("LLM_CONNECTION_ERROR", "无法连接模型服务") from exc

        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            finish("error", "LLM_INVALID_RESPONSE")
            raise LLMProviderError("LLM_INVALID_RESPONSE", "模型服务返回结构无效") from exc

        finish("success")
        return content


def llm_plan_query(user_text: str, meta: dict[str, Any]) -> Optional[dict[str, Any]]:
    """LLM 输出 JSON query；失败时返回 None 由规则兜底。"""
    industries = (meta.get("industries") or [])[:30]
    prompt = (
        "你是 HS300 多角色回测规划 Agent。根据用户中文需求，输出唯一 JSON 对象，"
        "字段仅可包含：time_range(start_date,end_date)、industry、benchmark、"
        "rebalance_freq、target_role、role_weights。\n"
        f"合法行业示例：{industries}\n"
        f"合法角色：{meta.get('roles', [])}\n"
        f"用户需求：{user_text}\n"
        "只输出 JSON，不要 markdown。"
    )
    try:
        raw = call_llm(
            [
                {"role": "system", "content": "严谨金融工程助手，只输出合法 JSON。"},
                {"role": "user", "content": prompt},
            ]
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception:
        return None
