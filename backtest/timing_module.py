"""
择时模块（策略分析师）
================================================================================
基于趋势确认与波动率目标管理的仓位调整策略。

核心思想（Moreira & Muir, 2017, Journal of Finance）：
    仓位比例 = 目标波动率 / 已实现波动率

原理：
    - 波动率高时减仓，降低组合风险
    - 波动率低时加仓，充分利用市场机会
    - 简单有效，被华泰金工等机构广泛使用

作者: 徐远 | 日期: 2026-08-19
================================================================================
"""

import numpy as np
import pandas as pd
from typing import Optional


class TimingModule:
    """择时模块（策略分析师）"""
    
    def __init__(self, target_vol: float = 0.15, lookback: int = 20,
                 defensive_position_cap: float = 0.50):
        """
        参数:
            target_vol: 目标年化波动率（默认15%）
            lookback: 已实现波动率的回看窗口（默认20个交易日）
        """
        self.target_vol = target_vol
        self.lookback = lookback
        self.defensive_position_cap = defensive_position_cap
    
    def calculate_position_ratio(self, index_data: pd.DataFrame, 
                                  date: pd.Timestamp) -> float:
        """
        计算给定日期的仓位比例
        
        参数:
            index_data: 指数数据，需含 'date' 和 'close' 列
            date: 当前日期
            
        返回:
            仓位比例（0.0 ~ 1.0）
        """
        # 获取截至当前日期的数据
        hist = index_data[index_data['date'] <= date].copy()
        
        if len(hist) < self.lookback:
            return 0.5  # 数据不足时返回半仓
        
        # 计算日收益率
        returns = hist['close'].pct_change().dropna()
        
        if len(returns) < self.lookback:
            return 0.5
        
        # 计算已实现波动率（年化）
        recent_returns = returns.tail(self.lookback)
        realized_vol = recent_returns.std() * np.sqrt(252)
        
        if realized_vol <= 0:
            return 1.0  # 波动率为0时满仓
        
        # 仓位比例 = 目标波动率 / 已实现波动率
        ratio = self.target_vol / realized_vol
        
        # 限制在 0.0 ~ 1.0
        return float(np.clip(ratio, 0.0, 1.0))
    
    def calculate_monthly_position(self, index_returns, year_month: str) -> float:
        """
        计算某月的仓位比例（取月初的信号）
        
        参数:
            index_returns: 指数收益率序列（Series，index为日期）
            year_month: 月份，格式 "2024-01"
            
        返回:
            仓位比例（0.0 ~ 1.0）
        """
        ym = pd.Period(year_month)
        month_start = ym.start_time
        
        # 获取月初之前的数据
        hist_returns = index_returns[index_returns.index < month_start]
        
        if len(hist_returns) < self.lookback:
            return 0.5
        
        # 计算已实现波动率（年化）
        recent_returns = hist_returns.tail(self.lookback)
        realized_vol = recent_returns.std() * np.sqrt(252)
        
        if realized_vol <= 0:
            return 1.0  # 波动率为0时满仓
        
        # 仓位比例 = 目标波动率 / 已实现波动率
        ratio = self.target_vol / realized_vol
        
        # 限制在 0.0 ~ 1.0
        return float(np.clip(ratio, 0.0, 1.0))

    def calculate_regime_aware_position(self, index_returns, year_month: str) -> float:
        """趋势为正时保持满仓，仅在负趋势且高波动时使用波动率目标降仓。"""
        ym = pd.Period(year_month)
        month_start = ym.start_time
        hist_returns = index_returns[index_returns.index < month_start].dropna()

        if len(hist_returns) < self.lookback:
            return 1.0

        recent_returns = hist_returns.tail(self.lookback)
        trailing_return = float((1 + recent_returns).prod() - 1)
        if trailing_return >= 0:
            return 1.0

        realized_vol = recent_returns.std() * np.sqrt(252)
        if not np.isfinite(realized_vol) or realized_vol <= 0:
            return 1.0
        volatility_position = float(np.clip(self.target_vol / realized_vol, 0.0, 1.0))
        return min(float(self.defensive_position_cap), volatility_position)
    
    def get_timing_summary(self, index_data: pd.DataFrame, 
                           months: list) -> dict:
        """
        获取择时信号汇总
        
        参数:
            index_data: 指数数据
            months: 月份列表
            
        返回:
            {month: position_ratio} 字典
        """
        summary = {}
        for month in months:
            ratio = self.calculate_monthly_position(index_data, month)
            summary[month] = {
                'position_ratio': ratio,
                'signal': '满仓' if ratio >= 0.8 else ('半仓' if ratio >= 0.4 else '轻仓')
            }
        return summary


def apply_timing(weights: dict, position_ratio: float) -> dict:
    """
    应用择时信号到权重
    
    参数:
        weights: 原始权重 {stock: weight}
        position_ratio: 仓位比例 (0.0 ~ 1.0)
        
    返回:
        调整后的权重（剩余部分为现金）
    """
    return {stock: weight * position_ratio for stock, weight in weights.items()}
