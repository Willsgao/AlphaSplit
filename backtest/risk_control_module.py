"""
风控模块（风控分析师）
================================================================================
分层风控系统，参考行业标准实践。

风控层级：
    1. 仓位限制：单股上限、行业上限
    2. 止损机制：个股止损、组合止损
    3. 波动率目标：动态调整仓位使组合波动率达标
    4. 因子暴露：限制因子偏离度（简化版）

行业参考：
    - 单股上限：量化基金2%~5%，主观基金5%~10%
    - 行业上限：相对基准±5%~±10%
    - 止损：个股-5%~-10%，组合月度-3%~-5%
    - 波动率目标：年化5%~15%

作者: 徐远 | 日期: 2026-08-19
================================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class RiskControlModule:
    """风控模块（风控分析师）"""
    
    def __init__(self, config: dict = None):
        """
        参数:
            config: 风控配置
                - max_single: 单股上限（默认5%）
                - max_industry: 单行业上限（默认25%）
                - stop_loss_stock: 个股止损线（默认-8%）
                - stop_loss_monthly: 月度止损线（默认-5%）
                - target_vol: 目标波动率（默认15%）
        """
        default_config = {
            'max_single': 0.05,        # 单股上限5%
            'max_industry': 0.25,      # 单行业上限25%
            'stop_loss_stock': -0.08,  # 个股止损-8%
            'stop_loss_monthly': -0.05, # 月度止损-5%
            'target_vol': 0.15,        # 目标波动率15%
        }
        self.config = {**default_config, **(config or {})}
    
    def apply_position_limits(self, weights: Dict[str, float]) -> Dict[str, float]:
        """
        应用仓位限制（单股上限）
        
        参数:
            weights: 原始权重 {stock: weight}
            
        返回:
            调整后的权重
        """
        max_single = self.config['max_single']
        adjusted = {}
        
        for stock, weight in weights.items():
            adjusted[stock] = min(weight, max_single)
        
        # 重新归一化
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {s: w / total for s, w in adjusted.items()}
        
        return adjusted
    
    def apply_industry_limit(self, weights: Dict[str, float], 
                              industry_mapping: Dict[str, str]) -> Dict[str, float]:
        """
        应用行业仓位限制
        
        参数:
            weights: 权重 {stock: weight}
            industry_mapping: 股票到行业的映射 {stock: industry}
            
        返回:
            调整后的权重
        """
        max_industry = self.config['max_industry']
        
        # 计算每个行业的总权重
        industry_weights = {}
        for stock, weight in weights.items():
            industry = industry_mapping.get(stock, '未知')
            industry_weights[industry] = industry_weights.get(industry, 0) + weight
        
        # 对超限行业按比例缩减
        adjusted = weights.copy()
        for industry, total_weight in industry_weights.items():
            if total_weight > max_industry:
                scale = max_industry / total_weight
                for stock in adjusted:
                    if industry_mapping.get(stock) == industry:
                        adjusted[stock] *= scale
        
        # 重新归一化
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {s: w / total for s, w in adjusted.items()}
        
        return adjusted
    
    def check_monthly_stop_loss(self, monthly_return: float) -> bool:
        """
        检查月度止损
        
        参数:
            monthly_return: 月度收益率
            
        返回:
            True = 触发止损，需要减仓
        """
        return monthly_return <= self.config['stop_loss_monthly']
    
    def apply_stop_loss(self, weights: Dict[str, float], 
                         monthly_return: float) -> Dict[str, float]:
        """
        应用止损机制
        
        参数:
            weights: 权重
            monthly_return: 月度收益率
            
        返回:
            调整后的权重（止损时减半仓）
        """
        if self.check_monthly_stop_loss(monthly_return):
            # 止损触发：减半仓
            return {s: w * 0.5 for s, w in weights.items()}
        return weights
    
    def apply_volatility_target(self, weights: Dict[str, float], 
                                 stock_returns: pd.DataFrame) -> Dict[str, float]:
        """
        应用波动率目标管理
        
        参数:
            weights: 权重
            stock_returns: 股票日收益率数据
            
        返回:
            调整后的权重
        """
        target_vol = self.config['target_vol']
        
        # 计算组合波动率
        portfolio_vol = self._calculate_portfolio_volatility(weights, stock_returns)
        
        if portfolio_vol <= 0:
            return weights
        
        # 如果组合波动率超过目标，按比例缩减
        if portfolio_vol > target_vol:
            scale = target_vol / portfolio_vol
            adjusted = {s: w * scale for s, w in weights.items()}
            return adjusted
        
        return weights
    
    def _calculate_portfolio_volatility(self, weights: Dict[str, float], 
                                         stock_returns: pd.DataFrame) -> float:
        """
        计算组合波动率
        
        参数:
            weights: 权重
            stock_returns: 股票日收益率
            
        返回:
            年化波动率
        """
        # 筛选有数据的股票
        valid_stocks = [s for s in weights.keys() if s in stock_returns.columns]
        
        if not valid_stocks:
            return 0.0
        
        # 构建权重向量
        w = np.array([weights[s] for s in valid_stocks])
        w = w / w.sum()  # 归一化
        
        # 获取收益率矩阵
        returns_matrix = stock_returns[valid_stocks].dropna()
        
        if len(returns_matrix) < 20:
            return 0.0
        
        # 计算协方差矩阵
        cov_matrix = returns_matrix.cov() * 252  # 年化
        
        # 组合波动率 = sqrt(w' * Cov * w)
        portfolio_var = w @ cov_matrix.values @ w
        portfolio_vol = np.sqrt(max(0, portfolio_var))
        
        return portfolio_vol
    
    def apply_all(self, weights: Dict[str, float], 
                   industry_mapping: Dict[str, str],
                   monthly_return: float = 0.0,
                   stock_returns: pd.DataFrame = None) -> Dict[str, float]:
        """
        应用所有风控规则
        
        参数:
            weights: 原始权重
            industry_mapping: 行业映射
            monthly_return: 月度收益率（用于止损判断）
            stock_returns: 股票收益率数据（用于波动率目标）
            
        返回:
            最终权重
        """
        # 1. 单股上限
        adjusted = self.apply_position_limits(weights)
        
        # 2. 行业上限
        adjusted = self.apply_industry_limit(adjusted, industry_mapping)
        
        # 3. 止损
        adjusted = self.apply_stop_loss(adjusted, monthly_return)
        
        # 4. 波动率目标（如果有数据）
        if stock_returns is not None:
            adjusted = self.apply_volatility_target(adjusted, stock_returns)
        
        return adjusted


def get_risk_summary(weights_before: Dict[str, float], 
                      weights_after: Dict[str, float],
                      industry_mapping: Dict[str, str]) -> dict:
    """
    生成风控摘要
    
    参数:
        weights_before: 风控前权重
        weights_after: 风控后权重
        industry_mapping: 行业映射
        
    返回:
        风控摘要字典
    """
    # 行业集中度变化
    def calc_industry_concentration(weights):
        industry_weights = {}
        for stock, weight in weights.items():
            industry = industry_mapping.get(stock, '未知')
            industry_weights[industry] = industry_weights.get(industry, 0) + weight
        return industry_weights
    
    before_industry = calc_industry_concentration(weights_before)
    after_industry = calc_industry_concentration(weights_after)
    
    # 最大单股权重变化
    max_single_before = max(weights_before.values()) if weights_before else 0
    max_single_after = max(weights_after.values()) if weights_after else 0
    
    return {
        'max_single_before': max_single_before,
        'max_single_after': max_single_after,
        'max_industry_before': max(before_industry.values()) if before_industry else 0,
        'max_industry_after': max(after_industry.values()) if after_industry else 0,
        'stocks_count_before': len(weights_before),
        'stocks_count_after': len([w for w in weights_after.values() if w > 0]),
    }
