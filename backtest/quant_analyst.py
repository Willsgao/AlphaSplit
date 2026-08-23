"""
量化分析师模块（优化版）
================================================================================
优化策略：
1. 使用预定义的专业因子权重组合（而非随机扰动）
2. 增加策略数量（8套）
3. 使用平均排名选股（而非被选中次数）
4. 引入动量/价值/质量多维度因子

作者: 徐远 | 日期: 2026-08-19
================================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from quant_engine import compute_factor, ROLE_FACTORS


# 预定义的专业因子权重组合（8套）
QUANT_STRATEGIES = [
    # 策略1: 量能主导（关注成交量变化）
    {"quant_vol_ratio_5d": 0.25, "quant_vol_z_5d": 0.25, "quant_dollar_5d": 0.20, 
     "quant_pv_corr_5d": 0.10, "quant_obv_5d": 0.10, "quant_ts_close_5d": 0.05, 
     "quant_ts_vol_5d": 0.03, "quant_down_vol_5d": 0.02},
    
    # 策略2: 价格动量主导
    {"quant_vol_ratio_5d": 0.10, "quant_vol_z_5d": 0.10, "quant_dollar_5d": 0.10, 
     "quant_pv_corr_5d": 0.15, "quant_obv_5d": 0.15, "quant_ts_close_5d": 0.25, 
     "quant_ts_vol_5d": 0.10, "quant_down_vol_5d": 0.05},
    
    # 策略3: 风险规避（关注下行波动）
    {"quant_vol_ratio_5d": 0.10, "quant_vol_z_5d": 0.10, "quant_dollar_5d": 0.10, 
     "quant_pv_corr_5d": 0.10, "quant_obv_5d": 0.10, "quant_ts_close_5d": 0.10, 
     "quant_ts_vol_5d": 0.10, "quant_down_vol_5d": 0.30},
    
    # 策略4: 量价配合（关注量价关系）
    {"quant_vol_ratio_5d": 0.15, "quant_vol_z_5d": 0.15, "quant_dollar_5d": 0.15, 
     "quant_pv_corr_5d": 0.25, "quant_obv_5d": 0.15, "quant_ts_close_5d": 0.05, 
     "quant_ts_vol_5d": 0.05, "quant_down_vol_5d": 0.05},
    
    # 策略5: 时序排名主导
    {"quant_vol_ratio_5d": 0.05, "quant_vol_z_5d": 0.05, "quant_dollar_5d": 0.05, 
     "quant_pv_corr_5d": 0.10, "quant_obv_5d": 0.10, "quant_ts_close_5d": 0.30, 
     "quant_ts_vol_5d": 0.25, "quant_down_vol_5d": 0.10},
    
    # 策略6: 均衡策略（等权）
    {"quant_vol_ratio_5d": 0.125, "quant_vol_z_5d": 0.125, "quant_dollar_5d": 0.125, 
     "quant_pv_corr_5d": 0.125, "quant_obv_5d": 0.125, "quant_ts_close_5d": 0.125, 
     "quant_ts_vol_5d": 0.125, "quant_down_vol_5d": 0.125},
    
    # 策略7: OBV主导（关注资金流向）
    {"quant_vol_ratio_5d": 0.10, "quant_vol_z_5d": 0.10, "quant_dollar_5d": 0.10, 
     "quant_pv_corr_5d": 0.15, "quant_obv_5d": 0.30, "quant_ts_close_5d": 0.10, 
     "quant_ts_vol_5d": 0.10, "quant_down_vol_5d": 0.05},
    
    # 策略8: 成交额活跃度主导
    {"quant_vol_ratio_5d": 0.15, "quant_vol_z_5d": 0.15, "quant_dollar_5d": 0.30, 
     "quant_pv_corr_5d": 0.10, "quant_obv_5d": 0.10, "quant_ts_close_5d": 0.10, 
     "quant_ts_vol_5d": 0.05, "quant_down_vol_5d": 0.05},
]


class QuantAnalyst:
    """量化分析师（优化版）"""
    
    def __init__(self, n_strategies: int = 8):
        """
        参数:
            n_strategies: 使用的策略数量（默认8套）
        """
        self.n_strategies = min(n_strategies, len(QUANT_STRATEGIES))
    
    def optimize_selection(self, df_daily: pd.DataFrame, 
                           stocks: List[str],
                           role: str,
                           top_n: int = 10) -> Tuple[List[str], Dict[str, float]]:
        """
        优化选股：使用多策略平均排名
        
        参数:
            df_daily: 日线数据
            stocks: 候选股票列表
            role: 角色名称
            top_n: 选股数量
            
        返回:
            (选中的股票列表, 平均得分字典)
        """
        if role not in ROLE_FACTORS:
            return stocks[:top_n], {}
        
        factor_defs = ROLE_FACTORS[role]
        
        # 计算所有因子
        all_factor_dfs = []
        for fdef in factor_defs:
            col_name = fdef["col"]
            factor_results = []
            
            for sym in stocks:
                stock_df = df_daily[df_daily["symbol"] == sym].copy()
                if len(stock_df) < 30:
                    continue
                try:
                    result = compute_factor(
                        stock_df, 
                        base=fdef["base"], 
                        transform=fdef["transform"],
                        params=fdef.get("params", {"window": 5, "norm": 20}),
                        factor_col=col_name
                    )
                    factor_results.append(result[["date", "symbol", col_name]])
                except:
                    pass
            
            if factor_results:
                all_factor_dfs.append(pd.concat(factor_results, ignore_index=True))
        
        if not all_factor_dfs:
            return stocks[:top_n], {}
        
        # 合并所有因子
        merged = all_factor_dfs[0]
        for fd in all_factor_dfs[1:]:
            merged = merged.merge(fd, on=["date", "symbol"], how="outer")
        
        factor_cols = [c for c in merged.columns if c not in ("date", "symbol")]
        
        # 获取最新日期的数据
        latest_date = merged["date"].max()
        latest = merged[merged["date"] == latest_date].copy()
        
        if len(latest) == 0:
            return stocks[:top_n], {}
        
        # 多策略平均排名
        strategy_ranks = []
        
        for i in range(self.n_strategies):
            weights = QUANT_STRATEGIES[i]
            
            # 计算加权综合得分
            score_col = f"score_{i}"
            latest[score_col] = 0.0
            for col in factor_cols:
                if col in weights:
                    # 用排名代替原始值（更稳健）
                    rank_col = f"rank_{col}"
                    latest[rank_col] = latest[col].rank(pct=True)
                    latest[score_col] += latest[rank_col] * weights[col]
            
            # 计算排名（越高越好）
            latest[f"rank_{i}"] = latest[score_col].rank(ascending=False)
            strategy_ranks.append(f"rank_{i}")
        
        # 计算平均排名
        latest["avg_rank"] = latest[strategy_ranks].mean(axis=1)
        
        # 按平均排名排序（越小越好）
        latest_sorted = latest.sort_values("avg_rank")
        
        # 选出TOP N
        actual_top_n = min(top_n, len(latest_sorted))
        selected = latest_sorted.head(actual_top_n)
        
        # 构建得分字典（用平均排名的倒数作为得分）
        avg_scores = {}
        for _, row in selected.iterrows():
            avg_scores[row["symbol"]] = 1.0 / (row["avg_rank"] + 1)
        
        print(f"  [量化分析师] 多策略平均排名选股: {len(selected)} 只")
        print(f"    使用 {self.n_strategies} 套策略, 平均排名范围: {latest_sorted['avg_rank'].min():.1f} - {latest_sorted['avg_rank'].max():.1f}")
        
        return selected["symbol"].tolist(), avg_scores


def run_multi_strategy_backtest(df_daily: pd.DataFrame,
                                 stocks: List[str],
                                 role: str,
                                 top_n: int = 10,
                                 n_strategies: int = 8) -> pd.Series:
    """
    运行多策略回测并返回平均收益
    
    参数:
        df_daily: 日线数据
        stocks: 候选股票
        role: 角色
        top_n: 选股数量
        n_strategies: 策略数量
        
    返回:
        月度平均收益序列
    """
    analyst = QuantAnalyst(n_strategies=n_strategies)
    
    # 计算日收益率
    df_daily = df_daily.copy()
    df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
    
    monthly_returns = []
    months = sorted(df_daily["date"].dt.to_period("M").unique())
    
    for ym in months:
        month_data = df_daily[df_daily["date"].dt.to_period("M") == ym]
        
        if len(month_data) == 0:
            monthly_returns.append(0.0)
            continue
        
        # 获取月初的选股结果
        month_start = ym.start_time
        selection, _ = analyst.optimize_selection(
            df_daily[df_daily["date"] < month_start],
            stocks, role, top_n
        )
        
        if not selection:
            monthly_returns.append(0.0)
            continue
        
        # 计算选中股票的等权收益
        selected_data = month_data[month_data["symbol"].isin(selection)]
        daily_rets = selected_data.groupby("date")["return"].mean()
        month_ret = (1 + daily_rets).prod() - 1
        monthly_returns.append(month_ret)
    
    return pd.Series(monthly_returns, index=months)
