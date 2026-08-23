"""
QuantSkills 通用因子引擎
========================
基于 QuantSkills 标准化因子库的统一实现。
所有因子通过 (base, transform, params) 组合定义，覆盖：
  - directional-alpha (296个): 动量、反转、趋势、突破类
  - risk-pattern-alpha (288个): RSI、波动率、随机指标类
  - volume-stat-alpha (216个): 量能、分布、量价类

参考: https://github.com/quantskills

作者: 徐远 | 日期: 2026-08
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

# ============================================================
# 1. 通用辅助函数（直接来自 QuantSkills factor.py）
# ============================================================

def _minp(window: int, floor: int = 5) -> int:
    return min(window, max(2, min(floor, window // 2 if window > 2 else 2)))

def _zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=_minp(window)).mean()
    std = series.rolling(window, min_periods=_minp(window)).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=_minp(span, 3)).mean()

def _atr(data: pd.DataFrame, window: int) -> pd.Series:
    high, low, close = data["high"], data["low"], data["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=_minp(window)).mean()

def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=_minp(window)).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=_minp(window)).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    """
    滚动线性回归斜率（向量化优化，替代慢速 .rolling().apply()）
    斜率 = Σ(x·y) / Σ(x²)，其中 x 为中心化下标，y 为窗口内中心化值
    """
    window = max(3, int(window))
    s = series.to_numpy(dtype=float)
    n = len(s)
    out = np.full(n, np.nan)
    if n >= window:
        x = np.arange(window, dtype=float)
        x = x - x.mean()
        denom = float(np.sum(x * x))
        from numpy.lib.stride_tricks import sliding_window_view
        windows = sliding_window_view(s, window)            # (n-w+1, w)
        # y = values - values.mean()；sum(x·y)=sum(x·windows)（y去均值后 x 项抵消）
        slopes = (windows * x[None, :]).sum(axis=1) / denom
        out[window - 1:] = slopes
    return pd.Series(out, index=series.index)


def _ts_rank(series: pd.Series, window: int) -> pd.Series:
    """
    时间序列排名百分比（向量化优化，替代慢速 .rolling().apply()）
    末位排名 = 窗口内 <= 末位 的个数 / 窗口长度
    """
    window = int(window)
    minp = _minp(window)
    s = series.to_numpy(dtype=float)
    n = len(s)
    out = np.full(n, np.nan)
    if n >= minp:
        from numpy.lib.stride_tricks import sliding_window_view
        windows = sliding_window_view(s, window)            # (n-w+1, w)
        last = windows[:, -1:]                              # 每个窗口的末位值
        # 向量化：统计每个窗口内 <= 末位 的数量（含NaN处理，NaN比较为False）
        rank = (windows <= last).sum(axis=1) / window
        # 只有末位非NaN时才有效（末位是NaN则排名无意义）
        valid = ~np.isnan(last[:, 0])
        rank = np.where(valid, rank, np.nan)
        out[window - 1:] = rank
    return pd.Series(out, index=series.index)

# ============================================================
# 2. 基础信号函数（33种 base）
# ============================================================

def _base(data: pd.DataFrame, base: str, params: dict) -> pd.Series:
    close = data["close"].astype(float)
    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)
    ret = close.pct_change()
    w = int(params.get("window", 20))
    fast = int(params.get("fast", max(3, w // 3)))
    slow = int(params.get("slow", w))

    BASE_MAP = {
        "return":           lambda: close.pct_change(w),
        "skip_return":      lambda: close.shift(int(params.get("skip", 5))).pct_change(w),
        "reversal":         lambda: -close.pct_change(w),
        "sma_gap":          lambda: close / close.rolling(w, min_periods=_minp(w)).mean() - 1,
        "ema_gap":          lambda: close / _ema(close, w) - 1,
        "dual_ema_gap":     lambda: (_ema(close, fast) - _ema(close, slow)) / close.replace(0, np.nan),
        "sma_slope":        lambda: _rolling_slope(close.rolling(w, min_periods=_minp(w)).mean(), min(30, max(5, w // 2))) / close.replace(0, np.nan),
        "range_position":   lambda: (close - low.rolling(w, min_periods=_minp(w)).min()) / (high.rolling(w, min_periods=_minp(w)).max() - low.rolling(w, min_periods=_minp(w)).min()).replace(0, np.nan) - 0.5,
        "breakout":         lambda: close / high.shift(1).rolling(w, min_periods=_minp(w)).max().replace(0, np.nan) - 1,
        "breakdown":        lambda: -(close / low.shift(1).rolling(w, min_periods=_minp(w)).min().replace(0, np.nan) - 1),
        "rsi":              lambda: _rsi(close, w) / 100 - 0.5,
        "rsi_reversal":     lambda: 0.5 - _rsi(close, w) / 100,
        "stoch":            lambda: (close - low.rolling(w, min_periods=_minp(w)).min()) / (high.rolling(w, min_periods=_minp(w)).max() - low.rolling(w, min_periods=_minp(w)).min()).replace(0, np.nan) - 0.5,
        "atr_ratio":        lambda: _atr(data, w) / close.replace(0, np.nan),
        "range_ratio":      lambda: ((high - low) / close.replace(0, np.nan)).rolling(w, min_periods=_minp(w)).mean(),
        "realized_vol":     lambda: ret.rolling(w, min_periods=_minp(w)).std(ddof=0),
        "downside_vol":     lambda: ret.where(ret < 0, 0).rolling(w, min_periods=_minp(w)).std(ddof=0),
        "trend_strength":   lambda: close.pct_change(w) / ret.rolling(w, min_periods=_minp(w)).std(ddof=0).replace(0, np.nan),
        "efficiency":       lambda: (close - close.shift(w)).abs() / close.diff().abs().rolling(w, min_periods=_minp(w)).sum().replace(0, np.nan),
        "volume_ratio":     lambda: volume / volume.rolling(w, min_periods=_minp(w)).mean() - 1,
        "volume_z":         lambda: _zscore(volume, w),
        "dollar_volume":    lambda: (close * volume) / (close * volume).rolling(w, min_periods=_minp(w)).mean() - 1,
        "price_volume_corr":lambda: ret.rolling(w, min_periods=_minp(w)).corr(volume.pct_change()),
        "obv_slope":        lambda: _rolling_slope((np.sign(close.diff()).fillna(0) * volume).cumsum(), min(w, 60)) / volume.rolling(w, min_periods=_minp(w)).mean().replace(0, np.nan),
        "gap_sum":          lambda: (open_ / close.shift(1) - 1).rolling(w, min_periods=_minp(w)).sum(),
        "intraday":         lambda: (close / open_.replace(0, np.nan) - 1).rolling(w, min_periods=_minp(w)).mean(),
        "upper_wick":       lambda: ((high - pd.concat([open_, close], axis=1).max(axis=1)) / (high - low).replace(0, np.nan)).rolling(w, min_periods=_minp(w)).mean(),
        "lower_wick":       lambda: ((pd.concat([open_, close], axis=1).min(axis=1) - low) / (high - low).replace(0, np.nan)).rolling(w, min_periods=_minp(w)).mean(),
        "drawdown":         lambda: close / close.rolling(w, min_periods=_minp(w)).max().replace(0, np.nan) - 1,
        "ts_rank_close":    lambda: _ts_rank(close, w) - 0.5,
        "ts_rank_volume":   lambda: _ts_rank(volume, w) - 0.5,
        "ret_skew":         lambda: ret.rolling(w, min_periods=_minp(w, 10)).skew(),
        "ret_kurt":         lambda: ret.rolling(w, min_periods=_minp(w, 10)).kurt(),
    }

    if base not in BASE_MAP:
        raise ValueError(f"Unknown base: {base}")
    return BASE_MAP[base]()

# ============================================================
# 3. 变换函数（10种 transform）
# ============================================================

def _transform(signal: pd.Series, data: pd.DataFrame, transform: str, params: dict) -> pd.Series:
    w = int(params.get("window", 20))
    norm = int(params.get("norm", max(20, w)))
    ret = data["close"].pct_change()
    volume = data["volume"].astype(float)

    TRANSFORM_MAP = {
        "raw":             lambda: signal,
        "neg":             lambda: -signal,
        "z":               lambda: _zscore(signal, norm),
        "delta":           lambda: signal - signal.shift(int(params.get("lag", max(1, w // 4)))),
        "smooth":          lambda: _ema(signal, int(params.get("smooth", max(3, w // 3)))),
        "rank":            lambda: _ts_rank(signal, norm) - 0.5,
        "vol_scaled":      lambda: signal / ret.rolling(norm, min_periods=_minp(norm)).std(ddof=0).replace(0, np.nan),
        "stability":       lambda: signal / signal.rolling(norm, min_periods=_minp(norm)).std(ddof=0).replace(0, np.nan),
        "confirm_volume":  lambda: signal * (volume / volume.rolling(norm, min_periods=_minp(norm)).mean()),
        "compress":        lambda: np.tanh(signal),
    }

    if transform not in TRANSFORM_MAP:
        raise ValueError(f"Unknown transform: {transform}")
    return TRANSFORM_MAP[transform]()

# ============================================================
# 4. 统一因子计算接口
# ============================================================

def compute_factor(df: pd.DataFrame, base: str, transform: str = "z",
                   params: dict = None, factor_col: str = None) -> pd.DataFrame:
    """
    统一因子计算。与 QuantSkills 的 compute_factor 完全兼容。

    参数:
        df: DataFrame，需含 open/high/low/close/volume
        base: 基础信号类型（33种）
        transform: 变换类型（10种）
        params: 参数字典
        factor_col: 输出列名
    返回:
        添加了因子列的 DataFrame
    """
    if params is None:
        params = {"window": 5, "norm": 20, "lag": 1, "smooth": 3, "skip": 5, "fast": 3, "slow": 5}
    if factor_col is None:
        factor_col = f"factor_{base}_{transform}"

    data = df.copy()
    data.columns = [str(c).lower() for c in data.columns]

    required = ("open", "high", "low", "close", "volume")
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    if "symbol" not in data.columns:
        data["symbol"] = "asset"
    if "date" not in data.columns:
        data["date"] = pd.RangeIndex(len(data))

    data = data.sort_values(["symbol", "date"]).reset_index(drop=True)

    values = []
    for _, group in data.groupby("symbol", sort=False):
        raw = _base(group, base, params)
        transformed = _transform(raw, group, transform, params)
        values.append(transformed)

    data[factor_col] = pd.concat(values).sort_index()
    return data


def compute_multi_factor(df: pd.DataFrame, factor_defs: List[dict],
                         factor_cols: List[str] = None) -> pd.DataFrame:
    """
    批量计算多个因子。

    参数:
        df: DataFrame
        factor_defs: [{"base": "return", "transform": "z", "params": {...}}, ...]
        factor_cols: 输出列名列表
    返回:
        添加了所有因子列的 DataFrame
    """
    result = df.copy()
    for i, fdef in enumerate(factor_defs):
        col = factor_cols[i] if factor_cols and i < len(factor_cols) else f"factor_{fdef['base']}_{fdef['transform']}_{i}"
        result = compute_factor(result, base=fdef["base"], transform=fdef["transform"],
                                params=fdef.get("params"), factor_col=col)
    return result


# ============================================================
# 5. 角色-因子映射（基于三类因子库）
# ============================================================

# 标准参数
P5 = {"window": 5, "norm": 20, "lag": 1, "smooth": 3, "skip": 5, "fast": 3, "slow": 5}
P7 = {"window": 7, "norm": 20, "lag": 1, "smooth": 3, "skip": 5, "fast": 3, "slow": 7}
P10 = {"window": 10, "norm": 20, "lag": 2, "smooth": 5, "skip": 5, "fast": 3, "slow": 10}
P20 = {"window": 20, "norm": 20, "lag": 5, "smooth": 5, "skip": 5, "fast": 7, "slow": 20}

ROLE_FACTORS = {
    # ──────────────────────────────────────────────────────
    # 行业分析师（趋势+动量 → 识别行业轮动方向）
    # 来源: directional-alpha (动量/趋势类)
    # 来源: risk-pattern-alpha (趋势强度类)
    # ──────────────────────────────────────────────────────
    "行业分析师": [
        {"base": "return",          "transform": "z",   "params": P5,  "col": "ind_momentum_5d"},      # R001: 5日动量
        {"base": "return",          "transform": "z",   "params": P10, "col": "ind_momentum_10d"},     # R002: 10日动量
        {"base": "sma_gap",         "transform": "z",   "params": P5,  "col": "ind_sma_gap_5d"},      # R004: 均线偏离
        {"base": "sma_slope",       "transform": "z",   "params": P5,  "col": "ind_sma_slope_5d"},    # R007: 均线斜率
        {"base": "trend_strength",  "transform": "z",   "params": P5,  "col": "ind_trend_5d"},        # R018: 风险调整趋势
        {"base": "efficiency",      "transform": "z",   "params": P5,  "col": "ind_efficiency_5d"},   # R019: 趋势效率
        {"base": "breakout",        "transform": "z",   "params": P5,  "col": "ind_breakout_5d"},     # R009: 上轨突破
        {"base": "range_position",  "transform": "z",   "params": P5,  "col": "ind_range_pos_5d"},    # R008: 区间位置
    ],

    # ──────────────────────────────────────────────────────
    # 个股分析师（价值+反转+质量 → 精选个股）
    # 来源: directional-alpha (反转/突破类)
    # 来源: risk-pattern-alpha (RSI/随机指标类)
    # ──────────────────────────────────────────────────────
    "个股分析师": [
        {"base": "reversal",        "transform": "z",   "params": P5,  "col": "stk_reversal_5d"},     # R003: 5日反转
        {"base": "reversal",        "transform": "z",   "params": P10, "col": "stk_reversal_10d"},    # 10日反转
        {"base": "rsi",             "transform": "z",   "params": P5,  "col": "stk_rsi_5d"},          # R011: RSI强度
        {"base": "rsi_reversal",    "transform": "z",   "params": P5,  "col": "stk_rsi_rev_5d"},      # R012: RSI反转
        {"base": "stoch",           "transform": "z",   "params": P5,  "col": "stk_stoch_5d"},        # R013: 随机指标
        {"base": "drawdown",        "transform": "z",   "params": P5,  "col": "stk_drawdown_5d"},     # R029: 回撤
        {"base": "lower_wick",      "transform": "z",   "params": P5,  "col": "stk_lower_wick_5d"},   # R028: 下影线支撑
        {"base": "breakdown",       "transform": "z",   "params": P5,  "col": "stk_breakdown_5d"},    # R010: 下轨突破
    ],

    # ──────────────────────────────────────────────────────
    # 策略分析师（择时+波段 → 制定大类策略）
    # 来源: directional-alpha (跳空/日内/效率类)
    # 来源: risk-pattern-alpha (波动率类)
    # 来源: volume-stat-alpha (量能类)
    # ──────────────────────────────────────────────────────
    "策略分析师": [
        {"base": "skip_return",     "transform": "z",   "params": P10, "col": "str_skip_ret_10d"},    # R002: 跳过期间动量
        {"base": "gap_sum",         "transform": "z",   "params": P5,  "col": "str_gap_sum_5d"},      # R025: 跳空溢价
        {"base": "intraday",        "transform": "z",   "params": P5,  "col": "str_intraday_5d"},     # R026: 日内收益
        {"base": "realized_vol",    "transform": "z",   "params": P5,  "col": "str_rvol_5d"},         # R016: 已实现波动
        {"base": "atr_ratio",       "transform": "z",   "params": P5,  "col": "str_atr_5d"},          # R014: ATR占比
        {"base": "range_ratio",     "transform": "z",   "params": P5,  "col": "str_range_5d"},        # R015: 区间比
        {"base": "ret_skew",        "transform": "z",   "params": P5,  "col": "str_skew_5d"},         # R032: 收益偏度
        {"base": "ret_kurt",        "transform": "z",   "params": P5,  "col": "str_kurt_5d"},         # R033: 收益峰度
    ],

    # ──────────────────────────────────────────────────────
    # 量化分析师（量价+微观结构 → 提供交易信号）
    # 来源: volume-stat-alpha (量能统计类)
    # 来源: risk-pattern-alpha (波动形态类)
    # ──────────────────────────────────────────────────────
    "量化分析师": [
        {"base": "volume_ratio",      "transform": "z",   "params": P5,  "col": "quant_vol_ratio_5d"},   # R020: 量能扩张
        {"base": "volume_z",          "transform": "z",   "params": P5,  "col": "quant_vol_z_5d"},       # R021: 成交量Z分数
        {"base": "dollar_volume",     "transform": "z",   "params": P5,  "col": "quant_dollar_5d"},      # R022: 成交额活跃度
        {"base": "price_volume_corr", "transform": "z",   "params": P5,  "col": "quant_pv_corr_5d"},     # R023: 量价相关
        {"base": "obv_slope",         "transform": "z",   "params": P5,  "col": "quant_obv_5d"},         # R024: OBV斜率
        {"base": "ts_rank_close",     "transform": "z",   "params": P5,  "col": "quant_ts_close_5d"},    # R030: 收益时序排名
        {"base": "ts_rank_volume",    "transform": "z",   "params": P5,  "col": "quant_ts_vol_5d"},      # R031: 量能时序排名
        {"base": "downside_vol",      "transform": "z",   "params": P5,  "col": "quant_down_vol_5d"},    # R017: 下行波动
    ],

    # ──────────────────────────────────────────────────────
    # 风控分析师（风险+回撤 → 控制组合风险）
    # 来源: risk-pattern-alpha (波动率/ATR/回撤类)
    # 来源: volume-stat-alpha (偏度/峰度类)
    # ──────────────────────────────────────────────────────
    "风控分析师": [
        {"base": "realized_vol",    "transform": "z",   "params": P5,  "col": "risk_rvol_5d"},         # R016: 已实现波动
        {"base": "realized_vol",    "transform": "z",   "params": P10, "col": "risk_rvol_10d"},        # 10日波动
        {"base": "downside_vol",    "transform": "z",   "params": P5,  "col": "risk_down_vol_5d"},     # R017: 下行波动
        {"base": "atr_ratio",       "transform": "z",   "params": P5,  "col": "risk_atr_5d"},          # R014: ATR占比
        {"base": "range_ratio",     "transform": "z",   "params": P5,  "col": "risk_range_5d"},        # R015: 区间比
        {"base": "drawdown",        "transform": "z",   "params": P5,  "col": "risk_drawdown_5d"},     # R029: 最大回撤
        {"base": "ret_skew",        "transform": "z",   "params": P5,  "col": "risk_skew_5d"},         # R032: 偏度（左尾风险）
        {"base": "ret_kurt",        "transform": "z",   "params": P5,  "col": "risk_kurt_5d"},         # R033: 峰度（极端风险）
    ],
}

# 角色因子数量
ROLE_FACTOR_COUNTS = {role: len(factors) for role, factors in ROLE_FACTORS.items()}
print(f"[因子引擎] 已定义 {len(ROLE_FACTORS)} 个角色, 共 {sum(ROLE_FACTOR_COUNTS.values())} 个因子")
for role, cnt in ROLE_FACTOR_COUNTS.items():
    print(f"  {role}: {cnt} 个因子")


# ============================================================
# 6. 财务因子支持（新增）
# ============================================================

def compute_financial_factors(fin_df: pd.DataFrame, stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算财务因子（价值因子 + 质量因子）
    
    参数:
        fin_df: 财务数据 DataFrame[date, symbol, pe_ttm, pb, roe]
        stock_df: 股票数据 DataFrame[date, symbol, close, ...]
    
    返回:
        添加了财务因子的 DataFrame
    """
    # 确保日期格式一致
    fin_df = fin_df.copy()
    stock_df = stock_df.copy()
    
    fin_df['date'] = pd.to_datetime(fin_df['date'])
    stock_df['date'] = pd.to_datetime(stock_df['date'])
    
    # 合并财务数据到股票数据（使用symbol列）
    merged = stock_df.merge(fin_df, on=['date', 'symbol'], how='left')
    
    # 计算价值因子
    # PE倒数：PE越低，因子值越高（价值投资）
    merged['value_pe'] = 1 / merged['pe_ttm'].clip(lower=5, upper=100)
    
    # PB倒数：PB越低，因子值越高（价值投资）
    merged['value_pb'] = 1 / merged['pb'].clip(lower=0.3, upper=10)
    
    # 计算质量因子
    # ROE：ROE越高，因子值越高（质量投资）
    merged['quality_roe'] = merged['roe'] / 100
    
    return merged


def zscore_financial_factors(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """
    对财务因子进行Z-score标准化（按日期截面）
    
    参数:
        df: 包含财务因子的 DataFrame
        columns: 需要标准化的列名列表
    
    返回:
        添加了标准化因子的 DataFrame
    """
    df = df.copy()
    
    for col in columns:
        # 按日期计算截面均值和标准差
        mean = df.groupby('date')[col].transform('mean')
        std = df.groupby('date')[col].transform('std')
        
        # Z-score标准化
        df[f'factor_{col}'] = (df[col] - mean) / std.replace(0, np.nan)
    
    return df
