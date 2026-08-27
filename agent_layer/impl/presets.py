"""内置规划预设（Mock / 路演）。"""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "demo_roadshow_2024h2_2025h1": {
        "label": "路演默认 · 2024下半年至2025上半年 HS300",
        "query": {
            "time_range": {"start_date": "2024-07-01", "end_date": "2025-06-30"},
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
            "granularity": "monthly",
        },
        "summary": "2024-07-01~2025-06-30，HS300 全市场，月度调仓",
    },
    "industry_semiconductor": {
        "label": "行业下钻 · 半导体",
        "query": {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "industry": "半导体",
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
        },
        "summary": "2024上半年半导体板块，检验行业配置贡献",
    },
    "focus_industry_role": {
        "label": "制度偏好 · 偏重行业岗",
        "query": {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
            "role_weights": {"行业分析师": 2.0},
        },
        "summary": "全市场回测，证据池内行业分析师制度调节系数 ×2",
    },
}
