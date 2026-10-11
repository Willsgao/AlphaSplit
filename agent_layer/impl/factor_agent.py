"""DeepSeek 因子配置 Agent：自然语言 -> 受限配置补丁 -> 后端校验。"""

from __future__ import annotations

import copy
import json
import math
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from agent_layer.impl.llm import (
    LLMProviderError,
    call_llm,
    get_last_llm_call,
    llm_available,
    llm_status,
    reset_llm_call_metadata,
)
from agent_layer.impl.offline_cache import find_cached_factor_response
from backtest.factor_config import (
    FACTOR_DESCRIPTIONS,
    FACTOR_DIRECTIONS,
    FACTOR_LABELS,
    FACTOR_WEIGHT_MAX,
    PARAM_BOUNDS,
    ROLE_FACTOR_KEYS,
    config_fingerprint,
    normalize_factor_config,
    propose_factor_config,
)


class FactorAgentResponseError(ValueError):
    """模型返回内容不符合受限契约。"""


def _safe_failure_reason(exc: Exception) -> str:
    if isinstance(exc, LLMProviderError):
        return f"{exc.code}: {str(exc)}"
    if isinstance(exc, (FactorAgentResponseError, json.JSONDecodeError)):
        return f"{type(exc).__name__}: {str(exc)[:240]}"
    return type(exc).__name__


def _attach_audit(
    proposal: dict[str, Any],
    current: dict[str, Any],
    *,
    requested_mode: str,
    llm_call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    changes = proposal.get("changes") or []
    clarification_needed = bool(proposal.get("clarification_needed"))
    source = str(proposal.get("source") or "unknown")
    if source == "deepseek":
        interpretation_status = "success"
    elif source == "agent_cache":
        interpretation_status = "cached"
    elif source == "rule_fallback":
        interpretation_status = "fallback"
    else:
        interpretation_status = "rule"
    requires_confirmation = bool(changes) and not clarification_needed
    proposal["requires_confirmation"] = requires_confirmation
    proposal["audit"] = {
        "audit_id": f"fa_{secrets.token_hex(6)}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_mode": requested_mode,
        "source": source,
        "model": proposal.get("model"),
        "input_summary": {
            "message_count": None,
            "raw_prompt_stored": False,
        },
        "config_before": config_fingerprint(current),
        "config_after": config_fingerprint(proposal.get("config") or current),
        "change_count": len(changes),
        "requires_confirmation": requires_confirmation,
        "llm_call": llm_call,
        "stages": [
            {"stage": "INPUT_NORMALIZED", "status": "passed"},
            {"stage": "INTENT_INTERPRETED", "status": interpretation_status},
            {"stage": "CONSTRAINT_VALIDATED", "status": "passed"},
            {
                "stage": "HUMAN_CONFIRMATION",
                "status": "required" if requires_confirmation else "not_applicable",
            },
        ],
    }
    return proposal


def _json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise FactorAgentResponseError("模型必须返回 JSON 对象")
    return parsed


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FactorAgentResponseError(f"{label} 必须是数字") from exc
    if not math.isfinite(number):
        raise FactorAgentResponseError(f"{label} 必须是有限数")
    return number


def _safe_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in (messages or [])[-10:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content[:2000]})
    return out


def _factor_catalog() -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "factors": [
                {
                    "key": key,
                    "label": FACTOR_LABELS[key],
                    "direction": FACTOR_DIRECTIONS[key],
                    "meaning": FACTOR_DESCRIPTIONS[key],
                    "max_weight": FACTOR_WEIGHT_MAX,
                }
                for key in keys
            ],
            "module_param_bounds": PARAM_BOUNDS.get(role, {}),
        }
        for role, keys in ROLE_FACTOR_KEYS.items()
    ]


def _system_prompt() -> str:
    return (
        "你是资管场景的投资意图转换Agent。你的职责不是承诺收益，也不是直接执行交易，"
        "而是把用户对风险、行业、期限和角色的定性偏好转换成少量、可解释的配置修改建议。"
        "只能使用给定角色、因子和模块参数。direction=-1表示原始值越低越符合角色目标，"
        "提高该因子权重代表更重视低值信号。不要根据回测结果反复寻优，不要生成代码。"
        "信息不足时应提出一个简短澄清问题。只输出合法JSON对象。"
    )


def _user_prompt(
    text: str,
    current: dict[str, Any],
    quick_preferences: dict[str, Any] | None,
) -> str:
    contract = {
        "summary": "一句话客户画像或建议摘要",
        "assistant_message": "面向用户的简短回复",
        "preferences": {"risk_level": "稳健/均衡/进取", "objectives": [], "focus_roles": []},
        "clarification_needed": False,
        "clarification_question": None,
        "factor_changes": [
            {"role": "风控分析师", "factor": "risk_drawdown_5d", "new_weight": 0.18, "reason": "原因"}
        ],
        "module_changes": [
            {"role": "策略分析师", "parameter": "target_vol", "new_value": 0.10, "reason": "原因"}
        ],
    }
    return (
        f"用户本轮输入：{text}\n"
        f"快捷偏好：{json.dumps(quick_preferences or {}, ensure_ascii=False)}\n"
        f"当前配置：{json.dumps(current, ensure_ascii=False, separators=(',', ':'))}\n"
        f"合法目录：{json.dumps(_factor_catalog(), ensure_ascii=False, separators=(',', ':'))}\n"
        f"输出契约示例：{json.dumps(contract, ensure_ascii=False)}\n"
        "规则：factor_changes最多12项；new_weight必须在0到0.35之间；"
        "module_changes只能使用目录中的参数和范围；未修改项不要输出；"
        "如需澄清则clarification_needed=true且修改数组应为空。"
    )


def _apply_model_proposal(parsed: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "summary", "assistant_message", "preferences", "clarification_needed",
        "clarification_question", "factor_changes", "module_changes",
    }
    unknown = sorted(set(parsed) - allowed)
    if unknown:
        raise FactorAgentResponseError(f"模型返回了不支持的字段：{unknown}")

    clarification_needed = bool(parsed.get("clarification_needed", False))
    factor_changes = parsed.get("factor_changes") or []
    module_changes = parsed.get("module_changes") or []
    if not isinstance(factor_changes, list) or not isinstance(module_changes, list):
        raise FactorAgentResponseError("模型变更项必须是数组")
    if len(factor_changes) > 12 or len(module_changes) > 6:
        raise FactorAgentResponseError("模型一次返回的变更项过多")
    if clarification_needed and (factor_changes or module_changes):
        raise FactorAgentResponseError("需要澄清时不能同时修改配置")

    proposed = copy.deepcopy(current)
    changes: list[dict[str, Any]] = []
    for idx, item in enumerate(factor_changes):
        if not isinstance(item, dict):
            raise FactorAgentResponseError(f"factor_changes[{idx}] 必须是对象")
        role = str(item.get("role") or "")
        factor = str(item.get("factor") or "")
        if role not in ROLE_FACTOR_KEYS or factor not in ROLE_FACTOR_KEYS[role]:
            raise FactorAgentResponseError(f"非法角色或因子：{role}.{factor}")
        new_weight = _number(item.get("new_weight"), f"{role}.{factor}.new_weight")
        if not 0 <= new_weight <= FACTOR_WEIGHT_MAX:
            raise FactorAgentResponseError(
                f"{role}.{factor}.new_weight 必须在 0 到 {FACTOR_WEIGHT_MAX} 之间"
            )
        old_weight = current["roles"][role]["factor_weights"][factor]
        proposed["roles"][role]["factor_weights"][factor] = new_weight
        changes.append({
            "role": role,
            "factor": factor,
            "label": FACTOR_LABELS[factor],
            "old_weight": old_weight,
            "new_weight": new_weight,
            "direction": FACTOR_DIRECTIONS[factor],
            "reason": str(item.get("reason") or "Agent根据用户偏好调整")[:300],
        })

    for idx, item in enumerate(module_changes):
        if not isinstance(item, dict):
            raise FactorAgentResponseError(f"module_changes[{idx}] 必须是对象")
        role = str(item.get("role") or "")
        parameter = str(item.get("parameter") or "")
        if parameter not in PARAM_BOUNDS.get(role, {}):
            raise FactorAgentResponseError(f"非法模块参数：{role}.{parameter}")
        new_value = _number(item.get("new_value"), f"{role}.{parameter}.new_value")
        low, high = PARAM_BOUNDS[role][parameter]
        if not low <= new_value <= high:
            raise FactorAgentResponseError(f"{role}.{parameter} 必须在 {low} 到 {high} 之间")
        old_value = current["roles"][role]["module_params"][parameter]
        proposed["roles"][role]["module_params"][parameter] = new_value
        changes.append({
            "role": role,
            "parameter": parameter,
            "old_value": old_value,
            "new_value": int(new_value) if parameter == "lookback" else new_value,
            "reason": str(item.get("reason") or "Agent根据用户偏好调整")[:300],
        })

    normalized = normalize_factor_config(proposed)
    for change in changes:
        role = change["role"]
        if "factor" in change:
            factor = change["factor"]
            change["new_weight"] = normalized["roles"][role]["factor_weights"][factor]
            if change["new_weight"] > FACTOR_WEIGHT_MAX + 1e-12:
                raise FactorAgentResponseError(f"归一化后 {role}.{factor} 超过单因子上限")
        else:
            parameter = change["parameter"]
            change["new_value"] = normalized["roles"][role]["module_params"][parameter]

    if changes:
        normalized["config_id"] = f"client_{config_fingerprint(normalized)}"
    question = str(parsed.get("clarification_question") or "").strip()[:500] or None
    if not changes and not clarification_needed:
        clarification_needed = True
        question = question or "你更希望控制风险、增强趋势，还是重点调整某个投资角色？"

    preferences = parsed.get("preferences") or {}
    if not isinstance(preferences, dict):
        raise FactorAgentResponseError("preferences 必须是对象")
    return {
        "config": normalized,
        "base_config": current,
        "changes": changes,
        "summary": str(parsed.get("summary") or "已生成客户投资方案建议")[:500],
        "assistant_message": str(parsed.get("assistant_message") or "请审查以下配置建议。")[:800],
        "preferences": preferences,
        "clarification_needed": clarification_needed,
        "clarification_question": question,
    }


def propose_with_factor_agent(
    *,
    text: str | None,
    current_config: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None = None,
    quick_preferences: dict[str, Any] | None = None,
    mode: str = "llm",
) -> dict[str, Any]:
    """生成建议但不执行回测；LLM失败时明确回退规则模式。"""
    current = normalize_factor_config(current_config)
    user_text = (text or "").strip()
    status = llm_status()
    reset_llm_call_metadata()

    def cached_proposal() -> dict[str, Any] | None:
        entry = find_cached_factor_response(quick_preferences)
        if not entry:
            return None
        proposal = _apply_model_proposal(entry["response"], current)
        proposal.update({
            "mode": "offline",
            "source": "agent_cache",
            "model": None,
            "fallback_reason": None,
            "cache": {
                "id": entry["id"],
                "kind": "bundled_reviewed_response",
                "live_llm_used": False,
            },
        })
        result = _attach_audit(proposal, current, requested_mode=mode)
        result["audit"]["input_summary"]["message_count"] = len(messages or []) + 1
        result["audit"]["cache"] = result["cache"]
        return result

    if mode != "llm":
        proposal = propose_factor_config(user_text, current)
        proposal.update({"mode": "mock", "source": "rule", "model": None, "fallback_reason": None})
        result = _attach_audit(proposal, current, requested_mode=mode)
        result["audit"]["input_summary"]["message_count"] = len(messages or []) + 1
        return result

    if not llm_available():
        cached = cached_proposal()
        if cached:
            return cached
        proposal = propose_factor_config(user_text, current)
        proposal.update({
            "mode": "mock",
            "source": "rule_fallback",
            "model": status["model"],
            "fallback_reason": "未配置 DEEPSEEK_API_KEY",
        })
        result = _attach_audit(proposal, current, requested_mode=mode)
        result["audit"]["input_summary"]["message_count"] = len(messages or []) + 1
        return result

    history = _safe_messages(messages)
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt()}]
    llm_messages.extend(history)
    llm_messages.append({"role": "user", "content": _user_prompt(user_text, current, quick_preferences)})
    try:
        raw = call_llm(
            llm_messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        proposal = _apply_model_proposal(_json_object(raw), current)
        proposal.update({
            "mode": "llm",
            "source": "deepseek",
            "model": status["model"],
            "fallback_reason": None,
        })
        result = _attach_audit(
            proposal, current, requested_mode=mode, llm_call=get_last_llm_call()
        )
        result["audit"]["input_summary"]["message_count"] = len(history) + 1
        return result
    except Exception as exc:
        llm_call = get_last_llm_call()
        cached = cached_proposal()
        if cached:
            cached["audit"]["llm_call"] = llm_call
            cached["audit"]["live_failure"] = _safe_failure_reason(exc)
            return cached
        proposal = propose_factor_config(user_text, current)
        proposal.update({
            "mode": "mock",
            "source": "rule_fallback",
            "model": status["model"],
            "fallback_reason": _safe_failure_reason(exc),
        })
        result = _attach_audit(
            proposal, current, requested_mode=mode, llm_call=llm_call
        )
        result["audit"]["input_summary"]["message_count"] = len(history) + 1
        return result
