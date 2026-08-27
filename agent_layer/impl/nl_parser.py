"""规则型自然语言 → 回测意图（Mock 规划，无需 LLM）。"""

from __future__ import annotations

import re
from typing import Any

from agent_layer.impl.presets import PRESETS


def _extract_dates(text: str) -> dict[str, str]:
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        y, mo, d = m.groups()
        start = f"{y}-{int(mo):02d}-{int(d):02d}"
        return {"start_date": start, "end_date": start}
    if "上半年" in text or "H1" in text.upper():
        y = re.search(r"(20\d{2})", text)
        year = y.group(1) if y else "2024"
        return {"start_date": f"{year}-01-01", "end_date": f"{year}-06-30"}
    if "下半年" in text or "H2" in text.upper():
        y = re.search(r"(20\d{2})", text)
        year = y.group(1) if y else "2024"
        return {"start_date": f"{year}-07-01", "end_date": f"{year}-12-31"}
    return {"start_date": "2024-01-01", "end_date": "2024-06-30"}


def _extract_industry(text: str, valid_industries: list[str] | None) -> str | None:
    if not valid_industries:
        for key in ("半导体", "银行", "食品饮料", "计算机", "医药", "汽车", "电力"):
            if key in text:
                return key
        return None
    for ind in sorted(valid_industries, key=len, reverse=True):
        if ind in text or ind.replace("Ⅱ", "") in text:
            return ind
    return None


def _extract_role_weights(text: str) -> dict[str, float] | None:
    weights: dict[str, float] = {}
    mapping = {
        "行业": "行业分析师",
        "个股": "个股分析师",
        "策略": "策略分析师",
        "量化": "量化分析师",
        "风控": "风控分析师",
    }
    for key, role in mapping.items():
        if f"偏重{key}" in text or f"重视{key}" in text or f"{key}岗" in text:
            weights[role] = 2.0
    return weights or None


def parse_natural_language(
    text: str,
    *,
    valid_industries: list[str] | None = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return dict(PRESETS["demo_roadshow_2024h2_2025h1"]["query"])

    tr = _extract_dates(text)
    industry = _extract_industry(text, valid_industries)
    role_weights = _extract_role_weights(text)

    query: dict[str, Any] = {
        "time_range": tr,
        "benchmark": "hs300",
        "rebalance_freq": "monthly",
        "granularity": "monthly",
    }
    if industry:
        query["industry"] = industry
    if role_weights:
        query["role_weights"] = role_weights

    if "季度" in text:
        query["rebalance_freq"] = "quarterly"
        query["granularity"] = "quarterly"

    focus = None
    for role in ("行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"):
        if role.replace("分析师", "") in text or role in text:
            focus = role
            break
    if focus and "聚焦" in text:
        query["target_role"] = focus

    return query
