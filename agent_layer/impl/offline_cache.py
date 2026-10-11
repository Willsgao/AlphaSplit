"""Validated access to bundled Agent responses used for offline demonstrations."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "factor_agent_responses.json"


@lru_cache(maxsize=1)
def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {"schema_version": 0, "responses": []}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 0, "responses": []}
    if payload.get("schema_version") != 1 or not isinstance(payload.get("responses"), list):
        return {"schema_version": 0, "responses": []}
    return payload


def offline_cache_status() -> dict[str, Any]:
    payload = _load_cache()
    responses = payload.get("responses") or []
    return {
        "available": bool(responses),
        "schema_version": payload.get("schema_version", 0),
        "response_count": len(responses),
        "generated_at": payload.get("generated_at"),
        "kind": "bundled_reviewed_responses",
    }


def find_cached_factor_response(
    quick_preferences: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the highest-priority response whose declared preferences match."""
    preferences = quick_preferences or {}
    if not preferences:
        return None
    risk_level = preferences.get("risk_level")
    objectives = set(preferences.get("objectives") or [])
    focus_roles = set(preferences.get("focus_roles") or [])
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    for entry in _load_cache().get("responses") or []:
        match = entry.get("match") or {}
        expected_risk = match.get("risk_level")
        expected_objectives = set(match.get("objectives") or [])
        expected_roles = set(match.get("focus_roles") or [])
        if expected_risk and expected_risk != risk_level:
            continue
        if not expected_objectives.issubset(objectives):
            continue
        if not expected_roles.issubset(focus_roles):
            continue
        specificity = bool(expected_risk) + len(expected_objectives) + len(expected_roles)
        candidates.append((int(entry.get("priority") or 0), specificity, entry))

    if not candidates:
        return None
    _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
    return copy.deepcopy(selected)
