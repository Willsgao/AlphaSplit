"""
行业分析师模块（多因子版）
================================================================================
基于行业多因子模型选出表现最好的TOP N行业。

核心因子（用户指定）：
1. ind_mom_20   - 行业20日收益（短期趋势）
2. ind_mom_60   - 行业60日收益剔除近5日（中期景气）
3. ind_rs       - 行业相对强度（行业轮动核心信号）
4. ind_breadth  - 行业内收盘价>MA20个股占比（趋势确认/宽度）
5. ind_turnover - 行业成交额20日Z-score（资金关注度）
6. ind_roe_chg  - 行业内ROE同比改善个股占比（基本面景气代理）

扩展因子：
7. ind_vol_20       - 行业20日波动率（风险因子）
8. ind_max_ret_20   - 行业20日最大单日收益（尾部风险/关注度）
9. ind_ret_vol_ratio- 收益/波动比（风险调整动量）
10. ind_dispersion  - 行业内个股收益离散度（选股机会）
11. ind_52w_high    - 行业内接近52周高点个股占比（动量确认）
12. ind_reversal_5  - 行业5日反转信号（短期均值回归）

作者: 徐远 | 日期: 2026-08-21
================================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


class IndustryAnalyst:
    """行业分析师（多因子版）"""
    
    # 因子权重配置
    FACTOR_WEIGHTS = {
        # 核心因子（用户指定）
        'ind_mom_20': 0.10,        # 短期动量
        'ind_mom_60': 0.10,        # 中期景气
        'ind_rs': 0.20,            # 相对强度（最重要）
        'ind_breadth': 0.15,       # 趋势确认
        'ind_turnover': 0.10,      # 资金关注
        'ind_roe_chg': 0.10,       # 基本面景气
        # 扩展因子
        'ind_vol_20': -0.05,       # 低波动优先（负权重）
        'ind_ret_vol_ratio': 0.10, # 风险调整收益
        'ind_dispersion': 0.05,    # 选股机会
        'ind_52w_high': 0.05,      # 动量确认
    }
    
    def __init__(self, top_n: int = 3, lookback: int = 60):
        """
        参数:
            top_n: 选择的行业数量（默认3个）
            lookback: 因子计算的最大回看窗口（默认60个交易日）
        """
        self.top_n = top_n
        self.lookback = lookback
    
    def compute_industry_factors(self, df_daily: pd.DataFrame,
                                  industry_mapping: Dict[str, str],
                                  hs300_index: pd.DataFrame,
                                  date: pd.Timestamp) -> Dict[str, Dict[str, float]]:
        """
        计算所有行业的因子值
        
        参数:
            df_daily: 日线数据（含 symbol, date, close, volume, amount, turnover）
            industry_mapping: 股票到行业的映射
            hs300_index: 沪深300指数数据（含 date, close）
            date: 当前日期
            
        返回:
            {行业名: {因子名: 因子值}} 字典
        """
        # 获取截至当前日期的历史数据
        hist = df_daily[df_daily['date'] <= date].copy()
        
        if len(hist) < self.lookback:
            return {}
        
        # 确保symbol为字符串格式（与行业映射一致）
        hist['symbol'] = hist['symbol'].astype(str)
        
        # 计算个股收益率
        hist['return'] = hist.groupby('symbol')['close'].pct_change()
        
        # 计算个股MA20
        hist['ma20'] = hist.groupby('symbol')['close'].transform(
            lambda x: x.rolling(20, min_periods=10).mean()
        )
        
        # 计算个股52周高点
        hist['high_52w'] = hist.groupby('symbol')['close'].transform(
            lambda x: x.rolling(252, min_periods=60).max()
        )
        
        # 获取HS300指数收益（用于相对强度）
        hs300_hist = hs300_index[hs300_index['date'] <= date].copy()
        if len(hs300_hist) >= 20:
            hs300_ret_20 = float(
                hs300_hist['close'].iloc[-1] / hs300_hist['close'].iloc[-20] - 1
            )
        else:
            hs300_ret_20 = 0.0
        
        # 按行业聚合计算因子
        industries = set(industry_mapping.values())
        industry_factors = {}
        
        for industry in industries:
            stocks = [s for s, ind in industry_mapping.items() if ind == industry]
            ind_data = hist[hist['symbol'].isin(stocks)].copy()
            
            if len(ind_data) < 10:
                continue
            
            # 获取最近N天的数据
            max_date = ind_data['date'].max()
            recent_20 = ind_data[ind_data['date'] >= max_date - pd.Timedelta(days=30)]
            recent_60 = ind_data[ind_data['date'] >= max_date - pd.Timedelta(days=75)]
            recent_5 = ind_data[ind_data['date'] >= max_date - pd.Timedelta(days=7)]
            
            # ===== 核心因子计算 =====
            
            # 1. ind_mom_20: 行业20日收益
            stock_ret_20 = recent_20.groupby('symbol')['return'].apply(
                lambda x: (1 + x).prod() - 1
            )
            ind_mom_20 = stock_ret_20.mean() if len(stock_ret_20) > 0 else 0
            
            # 2. ind_mom_60: 行业60日收益剔除近5日
            stock_ret_60 = recent_60.groupby('symbol')['return'].apply(
                lambda x: (1 + x).prod() - 1
            )
            stock_ret_5 = recent_5.groupby('symbol')['return'].apply(
                lambda x: (1 + x).prod() - 1
            )
            # 剔除近5日 = 60日收益 - 5日收益（近似）
            ind_mom_60 = 0
            if len(stock_ret_60) > 0 and len(stock_ret_5) > 0:
                common = stock_ret_60.index.intersection(stock_ret_5.index)
                if len(common) > 0:
                    ind_mom_60 = (stock_ret_60[common] - stock_ret_5[common]).mean()
            
            # 3. ind_rs: 相对强度（行业20日收益 - HS300同期收益）
            ind_rs = ind_mom_20 - hs300_ret_20
            
            # 4. ind_breadth: 行业内收盘价>MA20的个股占比
            latest_data = ind_data[ind_data['date'] == max_date]
            if len(latest_data) > 0 and 'ma20' in latest_data.columns:
                above_ma20 = (latest_data['close'] > latest_data['ma20']).mean()
            else:
                above_ma20 = 0.5  # 默认值
            
            # 5. ind_turnover: 行业成交额20日Z-score
            if 'amount' in recent_20.columns:
                daily_amount = recent_20.groupby('date')['amount'].sum()
                if len(daily_amount) >= 10:
                    mean_amount = daily_amount.mean()
                    std_amount = daily_amount.std()
                    # 用最近5日均值计算Z-score
                    recent_5_amount = daily_amount.tail(5).mean()
                    ind_turnover = (recent_5_amount - mean_amount) / std_amount if std_amount > 0 else 0
                else:
                    ind_turnover = 0
            else:
                ind_turnover = 0
            
            # 6. ind_roe_chg: 行业内ROE同比改善个股占比（简化版：用近3月ROE变化）
            # 注：这里用ROE的季度变化作为代理
            ind_roe_chg = 0.5  # 默认值，需要财务数据支持
            
            # ===== 扩展因子计算 =====
            
            # 7. ind_vol_20: 行业20日波动率
            daily_vol = recent_20.groupby('date')['return'].mean()
            ind_vol_20 = daily_vol.std() * np.sqrt(252) if len(daily_vol) >= 10 else 0.3
            
            # 8. ind_max_ret_20: 行业20日最大单日收益
            daily_ret = recent_20.groupby('date')['return'].mean()
            ind_max_ret_20 = daily_ret.max() if len(daily_ret) > 0 else 0
            
            # 9. ind_ret_vol_ratio: 收益/波动比（风险调整动量）
            ind_ret_vol_ratio = ind_mom_20 / ind_vol_20 if ind_vol_20 > 0 else 0
            
            # 10. ind_dispersion: 行业内个股收益离散度
            ind_dispersion = stock_ret_20.std() if len(stock_ret_20) > 2 else 0
            
            # 11. ind_52w_high: 行业内接近52周高点个股占比
            if len(latest_data) > 0 and 'high_52w' in latest_data.columns:
                near_high = (latest_data['close'] / latest_data['high_52w'] > 0.9).mean()
            else:
                near_high = 0.3
            
            # 12. ind_reversal_5: 行业5日反转信号（负值表示超卖，可能反弹）
            ind_reversal_5 = -stock_ret_5.mean() if len(stock_ret_5) > 0 else 0
            
            industry_factors[industry] = {
                # 核心因子
                'ind_mom_20': ind_mom_20,
                'ind_mom_60': ind_mom_60,
                'ind_rs': ind_rs,
                'ind_breadth': above_ma20,
                'ind_turnover': ind_turnover,
                'ind_roe_chg': ind_roe_chg,
                # 扩展因子
                'ind_vol_20': ind_vol_20,
                'ind_max_ret_20': ind_max_ret_20,
                'ind_ret_vol_ratio': ind_ret_vol_ratio,
                'ind_dispersion': ind_dispersion,
                'ind_52w_high': near_high,
                'ind_reversal_5': ind_reversal_5,
                # 原始统计
                'raw_momentum': ind_mom_20,
                'raw_breadth': above_ma20,
                'raw_volatility': ind_vol_20,
                'stocks_count': len(stocks),
            }
        
        return industry_factors
    
    def normalize_factors(self, industry_factors: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
        """
        对因子进行截面标准化（Z-score）
        
        参数:
            industry_factors: 原始因子值
            
        返回:
            标准化后的因子值
        """
        if not industry_factors:
            return industry_factors
        
        # 获取所有因子名称
        sample_ind = list(industry_factors.keys())[0]
        factor_names = [k for k in industry_factors[sample_ind].keys() 
                       if k.startswith('ind_')]
        
        # 对每个因子进行Z-score标准化
        normalized = {ind: {} for ind in industry_factors}
        
        for factor in factor_names:
            values = {ind: industry_factors[ind].get(factor, 0) 
                     for ind in industry_factors}
            
            mean_val = np.mean(list(values.values()))
            std_val = np.std(list(values.values()))
            
            for ind in industry_factors:
                if std_val > 0:
                    normalized[ind][factor] = (values[ind] - mean_val) / std_val
                else:
                    normalized[ind][factor] = 0
        
        # 保留非因子字段
        for ind in industry_factors:
            for k, v in industry_factors[ind].items():
                if not k.startswith('ind_'):
                    normalized[ind][k] = v
        
        return normalized
    
    def compute_composite_score(self, normalized_factors: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """
        计算综合评分
        
        参数:
            normalized_factors: 标准化后的因子值
            
        返回:
            {行业名: 综合评分}
        """
        scores = {}
        
        for industry, factors in normalized_factors.items():
            score = 0
            for factor_name, weight in self.FACTOR_WEIGHTS.items():
                factor_val = factors.get(factor_name, 0)
                score += weight * factor_val
            
            scores[industry] = score
        
        return scores
    
    def select_industries(self, df_daily: pd.DataFrame,
                          industry_mapping: Dict[str, str],
                          hs300_index: pd.DataFrame,
                          date: pd.Timestamp,
                          verbose: bool = True) -> List[str]:
        """
        选择表现最好的行业（多因子模型）
        
        参数:
            df_daily: 日线数据
            industry_mapping: 股票到行业的映射
            hs300_index: 沪深300指数数据
            date: 当前日期
            verbose: 是否打印行业详情（Shapley遍历时传False减少输出）
            
        返回:
            选中的行业列表
        """
        # 缓存：同一 date 的行业选择结果确定，避免 Shapley 32 子集重复计算
        cache_key = str(date)
        if getattr(self, "_select_cache", None) is None:
            self._select_cache = {}
        if cache_key in self._select_cache:
            if verbose:
                print(f"  [行业分析师] 选中行业(缓存): {self._select_cache[cache_key]}")
            return self._select_cache[cache_key]

        # 1. 计算行业因子
        industry_factors = self.compute_industry_factors(
            df_daily, industry_mapping, hs300_index, date
        )
        
        if not industry_factors:
            # 数据不足，返回所有行业
            result = list(set(industry_mapping.values()))
            self._select_cache[cache_key] = result
            return result
        
        # 2. 因子标准化
        normalized = self.normalize_factors(industry_factors)
        
        # 3. 计算综合评分
        scores = self.compute_composite_score(normalized)
        
        # 4. 按评分排序，选出TOP N
        sorted_industries = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [ind for ind, _ in sorted_industries[:self.top_n]]
        
        # 5. 打印结果
        if verbose:
            print(f"  [行业分析师] 选中行业: {selected}")
            for ind in selected:
                factors = industry_factors[ind]
                score = scores[ind]
                print(f"    {ind}: 综合评分={score:.3f}")
                print(f"      核心因子: 动量20={factors['ind_mom_20']:.2%}, "
                      f"相对强度={factors['ind_rs']:.2%}, "
                      f"广度={factors['ind_breadth']:.1%}")
                print(f"      扩展因子: 波动率={factors['ind_vol_20']:.2%}, "
                      f"换手Z={factors['ind_turnover']:.2f}, "
                      f"离散度={factors['ind_dispersion']:.3f}")
        
        self._select_cache[cache_key] = selected
        return selected
    
    def get_factor_details(self, df_daily: pd.DataFrame,
                           industry_mapping: Dict[str, str],
                           hs300_index: pd.DataFrame,
                           date: pd.Timestamp) -> Dict[str, Dict]:
        """
        获取所有行业的因子详情（用于报告展示）
        
        参数:
            df_daily: 日线数据
            industry_mapping: 股票到行业的映射
            hs300_index: 沪深300指数数据
            date: 当前日期
            
        返回:
            {行业名: {因子详情}} 字典
        """
        industry_factors = self.compute_industry_factors(
            df_daily, industry_mapping, hs300_index, date
        )
        
        if not industry_factors:
            return {}
        
        normalized = self.normalize_factors(industry_factors)
        scores = self.compute_composite_score(normalized)
        
        details = {}
        for industry in industry_factors:
            details[industry] = {
                'raw_factors': industry_factors[industry],
                'normalized_factors': normalized[industry],
                'composite_score': scores[industry],
            }
        
        return details
    
    def filter_stocks_by_industry(self, df_daily: pd.DataFrame,
                                   industry_mapping: Dict[str, str],
                                   selected_industries: List[str]) -> pd.DataFrame:
        """
        按选中的行业过滤股票
        """
        selected_stocks = [
            s for s, ind in industry_mapping.items()
            if ind in selected_industries
        ]
        
        filtered = df_daily[df_daily['symbol'].isin(selected_stocks)]
        return filtered


def get_industry_mapping(loader) -> Dict[str, str]:
    """从DataLoader获取行业映射"""
    mapping = {}
    if loader.df_industry is not None:
        for _, row in loader.df_industry.iterrows():
            mapping[str(row['stock_code'])] = row['industry']
    return mapping


def get_hs300_index(loader) -> pd.DataFrame:
    """从DataLoader获取沪深300指数数据"""
    if loader.df_index is not None:
        return loader.df_index
    return pd.DataFrame()
