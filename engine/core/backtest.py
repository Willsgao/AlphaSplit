"""
合成回测与三因素归因（策略 Alpha / 行业·政策 / 偶然·宏观）。

说明：使用可控合成数据做机制演示，不是真实历史行情回测。
归因结果为对照实验下的贡献估计，带不确定性，供分配锚点参考。
"""
from __future__ import annotations

import random
from typing import Any


PERIODS = [
    {"id": "bull_2019", "label": "2019 顺风", "regime": "bull", "market_mu": 0.012, "shock": 0.0},
    {"id": "shock_2020", "label": "2020 冲击", "regime": "shock", "market_mu": -0.008, "shock": 0.035},
    {"id": "bear_2022", "label": "2022 逆风", "regime": "bear", "market_mu": -0.006, "shock": 0.01},
    {"id": "recover_2023", "label": "2023 修复", "regime": "recover", "market_mu": 0.007, "shock": 0.005},
]

CATEGORIES = [
    {"id": "growth", "label": "成长/科技", "industry_mu": 0.010, "policy_boost": 0.006},
    {"id": "value", "label": "价值/周期", "industry_mu": 0.004, "policy_boost": 0.001},
    {"id": "defensive", "label": "防御/消费", "industry_mu": 0.003, "policy_boost": 0.002},
]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def simulate_cell(
    period: dict,
    category: dict,
    *,
    true_alpha: float = 0.004,
    beta_m: float = 0.55,
    beta_i: float = 0.70,
    months: int = 12,
    seed: int = 0,
) -> dict[str, Any]:
    """
    单单元格：生成月度收益并做粗归因。
    strategy ≈ βm·市场 + βi·行业 + α + ε
    """
    rng = random.Random(seed + hash((period["id"], category["id"])) % 10_000)

    strat, mkt, ind = [], [], []
    for _ in range(months):
        m = rng.gauss(period["market_mu"], 0.025 + period["shock"])
        i = rng.gauss(
            category["industry_mu"] + category["policy_boost"] * (1.2 if period["regime"] == "bull" else 0.6),
            0.022,
        )
        # 冲击期放大偶然噪声
        eps = rng.gauss(0.0, 0.012 + period["shock"])
        s = beta_m * m + beta_i * i + true_alpha + eps
        mkt.append(m)
        ind.append(i)
        strat.append(s)

    # 联合回归：strategy = α + βm·market + βi·industry + ε
    def _ols_2(y: list[float], x1: list[float], x2: list[float]) -> tuple[float, float, float, list[float]]:
        n = float(len(y))
        s1 = sum(x1)
        s2 = sum(x2)
        sy = sum(y)
        s11 = sum(a * a for a in x1)
        s22 = sum(a * a for a in x2)
        s12 = sum(a * b for a, b in zip(x1, x2))
        s1y = sum(a * b for a, b in zip(x1, y))
        s2y = sum(a * b for a, b in zip(x2, y))
        # 正规方程 XT X β = XT y，β=[a,b1,b2]
        # 用消元解 3x3
        A = [
            [n, s1, s2, sy],
            [s1, s11, s12, s1y],
            [s2, s12, s22, s2y],
        ]
        for col in range(3):
            piv = A[col][col] or 1e-12
            for j in range(col, 4):
                A[col][j] /= piv
            for row in range(3):
                if row == col:
                    continue
                factor = A[row][col]
                for j in range(col, 4):
                    A[row][j] -= factor * A[col][j]
        a, b1, b2 = A[0][3], A[1][3], A[2][3]
        resid = [yi - (a + b1 * x1i + b2 * x2i) for yi, x1i, x2i in zip(y, x1, x2)]
        return a, b1, b2, resid

    alpha_hat, b_m, b_i, resid = _ols_2(strat, mkt, ind)
    industry_contrib = sum(b_i * ii for ii in ind) / len(ind)
    market_contrib = sum(b_m * mm for mm in mkt) / len(mkt)

    # R2 粗估
    sst = sum((y - sum(strat) / len(strat)) ** 2 for y in strat) or 1e-9
    sse = sum(e * e for e in resid)
    r2 = _clip(1 - sse / sst, 0.0, 1.0)

    return {
        "period_id": period["id"],
        "period_label": period["label"],
        "regime": period["regime"],
        "category_id": category["id"],
        "category_label": category["label"],
        "ann_strategy": round((sum(strat) / len(strat)) * 12, 4),
        "ann_market": round((sum(mkt) / len(mkt)) * 12, 4),
        "ann_industry": round((sum(ind) / len(ind)) * 12, 4),
        "alpha_hat": round(alpha_hat * 12, 4),
        "beta_market": round(b_m, 3),
        "beta_industry": round(b_i, 3),
        "industry_contrib_ann": round(industry_contrib * 12, 4),
        "market_contrib_ann": round(market_contrib * 12, 4),
        "r2": round(r2, 3),
        "noise_share": round(_clip(1 - r2, 0, 1), 3),
    }


def run_backtest_matrix(
    plan: dict[str, Any],
    *,
    seed: int = 42,
    true_alpha: float = 0.006,
) -> dict[str, Any]:
    period_ids = {p["id"] for p in plan.get("periods", [])} or {p["id"] for p in PERIODS}
    cat_ids = {c["id"] for c in plan.get("categories", [])} or {c["id"] for c in CATEGORIES}
    periods = [p for p in PERIODS if p["id"] in period_ids]
    cats = [c for c in CATEGORIES if c["id"] in cat_ids]

    cells = []
    for i, p in enumerate(periods):
        for j, c in enumerate(cats):
            cells.append(
                simulate_cell(
                    p, c, true_alpha=true_alpha, seed=seed + i * 17 + j * 3
                )
            )

    alphas = [c["alpha_hat"] for c in cells]
    inds = [c["industry_contrib_ann"] for c in cells]
    noises = [c["noise_share"] for c in cells]

    mean_alpha = sum(alphas) / len(alphas)
    std_alpha = (sum((a - mean_alpha) ** 2 for a in alphas) / len(alphas)) ** 0.5
    mean_ind = sum(inds) / len(inds)
    mean_noise = sum(noises) / len(noises)
    mean_abs_alpha = sum(abs(a) for a in alphas) / len(alphas)
    mean_abs_ind = sum(abs(a) for a in inds) / len(inds)

    # 稳定性：alpha 跨期跨品类越稳，策略因素越高；波动大则偶然更高
    stability = _clip(1.0 - std_alpha / (mean_abs_alpha + 0.01), 0.05, 0.95)

    # 用绝对贡献 + 稳定性，避免残差略负时策略权重被清零
    raw_strategy = (0.55 * max(mean_alpha, 0.0) + 0.45 * mean_abs_alpha) * (0.35 + 0.65 * stability) + 0.008
    raw_industry = mean_abs_ind * 1.15 + 0.006
    raw_luck = mean_noise * (0.35 + 0.65 * (1 - stability)) * 0.04 + 0.004

    # 冲击期单独加权偶然
    shock_cells = [c for c in cells if c["regime"] == "shock"]
    if shock_cells:
        shock_noise = sum(c["noise_share"] for c in shock_cells) / len(shock_cells)
        raw_luck += 0.01 * shock_noise

    s = raw_strategy + raw_industry + raw_luck + 1e-9
    weights = {
        "strategy_alpha": round(raw_strategy / s, 4),
        "industry_policy": round(raw_industry / s, 4),
        "luck_macro": round(raw_luck / s, 4),
    }
    # 归一修正浮点
    z = sum(weights.values())
    weights = {k: round(v / z, 4) for k, v in weights.items()}

    # 分时段 / 分品类摘要
    by_period: dict[str, list] = {}
    by_category: dict[str, list] = {}
    for c in cells:
        by_period.setdefault(c["period_label"], []).append(c["alpha_hat"])
        by_category.setdefault(c["category_label"], []).append(c["alpha_hat"])

    return {
        "cells": cells,
        "weights": weights,
        "diagnostics": {
            "mean_alpha_ann": round(mean_alpha, 4),
            "std_alpha_ann": round(std_alpha, 4),
            "stability": round(stability, 4),
            "mean_industry_contrib_ann": round(mean_ind, 4),
            "mean_noise_share": round(mean_noise, 4),
            "n_cells": len(cells),
        },
        "alpha_by_period": {
            k: round(sum(v) / len(v), 4) for k, v in by_period.items()
        },
        "alpha_by_category": {
            k: round(sum(v) / len(v), 4) for k, v in by_category.items()
        },
        "disclaimer": (
            "合成对照回测下的贡献估计，用于区分策略/行业政策/偶然宏观；"
            "非精确因果识别，也非真实历史业绩承诺。"
        ),
    }


def map_weights_to_impact_overrides(
    contributors: list[dict],
    weights: dict[str, float],
) -> dict[str, float]:
    """
    将三因素权重映射为各方 Impact 调整：
    - 策略 Alpha ↑ → 知识资产方（reuse_count 最大）Impact ↑
    - 行业/政策 ↑ → 业务执行方 Impact ↑（按原 Impact 相对比例）
    - 偶然/宏观 ↑ → 略微压缩差异（更保守）
    """
    if not contributors:
        return {}
    owner = max(contributors, key=lambda c: (c.get("reuse_count", 1), c.get("hours", 0)))
    others = [c for c in contributors if c["name"] != owner["name"]]
    base_other = sum(float(c.get("impact", 0.5)) for c in others) or 1.0

    ws = float(weights.get("strategy_alpha", 0.34))
    wi = float(weights.get("industry_policy", 0.33))
    wl = float(weights.get("luck_macro", 0.33))

    # 目标中枢
    owner_impact = _clip(0.42 + 0.40 * ws - 0.12 * wl, 0.30, 0.88)
    exec_mass = _clip(0.38 + 0.42 * wi - 0.10 * wl, 0.28, 0.85)

    overrides = {owner["name"]: round(owner_impact, 4)}
    for c in others:
        rel = float(c.get("impact", 0.5)) / base_other
        overrides[c["name"]] = round(
            _clip(exec_mass * rel * max(len(others), 1), 0.28, 0.90), 4
        )
    return overrides
