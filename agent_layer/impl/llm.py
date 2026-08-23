"""可选 LLM 增强（与 engine/agentic 解耦，队员可替换）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional


def llm_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def call_llm(messages: list[dict], *, temperature: float = 0.3) -> str:
    import urllib.request

    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 LLM API Key")

    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    payload = json.dumps(
        {
            "model": os.environ.get("AGENT_LAYER_LLM_MODEL", "deepseek-chat"),
            "messages": messages,
            "temperature": temperature,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


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
