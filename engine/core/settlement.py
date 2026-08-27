"""
方案确认规则：公式锚点 + 带宽协商 + 人工确认。

- formula_share：可审计锚点
- band：每人允许偏离锚点的幅度（默认 ±5 个百分点，即 0.05）
- proposed_share：协商意向夹入带宽后归一化，作为系统建议案
- final_share：人工确认（可在带宽内微调；越界需显式 override）
"""
from __future__ import annotations

from typing import Any


def _normalize(shares: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in shares.values())
    if total <= 0:
        n = len(shares) or 1
        return {k: 1.0 / n for k in shares}
    return {k: max(0.0, float(v)) / total for k, v in shares.items()}


def build_bands(
    formula_shares: dict[str, float],
    band: float = 0.05,
) -> dict[str, dict[str, float]]:
    out = {}
    for name, anchor in formula_shares.items():
        a = float(anchor)
        out[name] = {
            "anchor": round(a, 4),
            "low": round(max(0.05, a - band), 4),
            "high": round(min(0.85, a + band), 4),
            "band": band,
        }
    return out


def clamp_to_bands(
    shares: dict[str, float],
    bands: dict[str, dict[str, float]],
    *,
    iterations: int = 6,
) -> dict[str, float]:
    """夹入带宽后归一化；多轮迭代减轻归一化导致的越界。"""
    x = {k: float(v) for k, v in shares.items()}
    for _ in range(iterations):
        for name, s in list(x.items()):
            b = bands.get(name, {})
            low = b.get("low", 0.05)
            high = b.get("high", 0.85)
            x[name] = min(high, max(low, s))
        x = _normalize(x)
    return x


def propose_from_negotiation(
    negotiated: dict[str, float],
    formula_shares: dict[str, float],
    *,
    band: float = 0.05,
    blend: float = 0.45,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """
    建议案 = 协商意向与锚点混合后，夹入带宽并归一化。
    blend: 协商权重；其余为锚点权重。
    """
    bands = build_bands(formula_shares, band)
    mixed = {}
    for name, anchor in formula_shares.items():
        neg = float(negotiated.get(name, anchor))
        mixed[name] = blend * neg + (1.0 - blend) * anchor
    proposed = clamp_to_bands(mixed, bands)
    return {k: round(v, 4) for k, v in proposed.items()}, bands


def amounts_from_shares(
    shares: dict[str, float],
    distributable: float,
) -> dict[str, float]:
    return {
        name: round(float(s) * distributable, 2)
        for name, s in shares.items()
    }


def build_settlement_rows(
    *,
    formula_shares: dict[str, float],
    negotiated: dict[str, float],
    proposed: dict[str, float],
    bands: dict[str, dict[str, float]],
    distributable: float,
    final_shares: dict[str, float] | None = None,
    status: str = "pending_human_confirm",
) -> dict[str, Any]:
    final = final_shares or proposed
    final = {k: round(v, 4) for k, v in _normalize(final).items()}
    amts = amounts_from_shares(final, distributable)
    rows = {}
    for name in formula_shares:
        b = bands[name]
        fs = final[name]
        in_band = b["low"] - 1e-9 <= fs <= b["high"] + 1e-9
        rows[name] = {
            "negotiated_share": round(float(negotiated.get(name, 0)), 4),
            "formula_share": round(float(formula_shares[name]), 4),
            "band_low": b["low"],
            "band_high": b["high"],
            "proposed_share": round(float(proposed.get(name, fs)), 4),
            "final_share": fs,
            "in_band": in_band,
            "amount": amts[name],
        }
    return {
        "status": status,
        "band": next(iter(bands.values()))["band"] if bands else 0.05,
        "rows": rows,
        # 兼容旧前端字段名
        "settlement": rows,
    }


def apply_human_confirm(
    human_shares: dict[str, float],
    *,
    formula_shares: dict[str, float],
    negotiated: dict[str, float],
    proposed: dict[str, float],
    distributable: float,
    band: float = 0.05,
    allow_outside_band: bool = False,
) -> dict[str, Any]:
    """
    人工确认分配方案。默认要求归一化后落在带宽内；
    allow_outside_band=True 时允许越界（需在 UI 明示合规定责）。
    """
    bands = build_bands(formula_shares, band)
    normalized = _normalize(human_shares)

    if not allow_outside_band:
        # 越界则夹回
        normalized = clamp_to_bands(normalized, bands)
        status = "confirmed"
        overridden = False
    else:
        # 允许越界，但仍归一化
        status = "confirmed_override"
        overridden = any(
            not (bands[n]["low"] - 1e-9 <= normalized.get(n, 0) <= bands[n]["high"] + 1e-9)
            for n in formula_shares
        )
        if not overridden:
            status = "confirmed"

    payload = build_settlement_rows(
        formula_shares=formula_shares,
        negotiated=negotiated,
        proposed=proposed,
        bands=bands,
        distributable=distributable,
        final_shares=normalized,
        status=status,
    )
    payload["overridden"] = status == "confirmed_override"
    payload["distributable"] = distributable
    return payload
