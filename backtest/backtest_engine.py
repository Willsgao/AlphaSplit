"""
================================================================================
回测引擎
================================================================================
【功能】
    核心回测引擎，支持：
    - 组合权重计算
    - 收益率计算
    - 绩效指标计算

================================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable


class Portfolio:
    """投资组合"""
    
    def __init__(self, name: str):
        self.name = name
        self.weights = {}  # {stock_code: weight}
        self.returns = []  # 每日收益率序列
        self.nav = [1.0]   # 净值序列
        
    def set_weights(self, weights: Dict[str, float]):
        """设置持仓权重"""
        self.weights = weights
        
    def calculate_daily_return(self, stock_returns: Dict[str, float]) -> float:
        """计算组合每日收益率"""
        daily_return = 0.0
        for stock, weight in self.weights.items():
            if stock in stock_returns and not np.isnan(stock_returns[stock]):
                daily_return += weight * stock_returns[stock]
        
        self.returns.append(daily_return)
        self.nav.append(self.nav[-1] * (1 + daily_return))
        
        return daily_return
    
    def get_performance(self) -> Dict:
        """计算绩效指标"""
        if not self.returns:
            return {}
        
        returns = np.array(self.returns)
        nav = np.array(self.nav)
        
        # 年化收益率
        total_return = nav[-1] / nav[0] - 1
        n_years = len(returns) / 252
        annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
        
        # 年化波动率
        annual_vol = np.std(returns) * np.sqrt(252)
        
        # 夏普比率（假设无风险利率2%）
        risk_free_rate = 0.02
        sharpe = (annual_return - risk_free_rate) / annual_vol if annual_vol > 0 else 0
        
        # 最大回撤
        peak = np.maximum.accumulate(nav)
        drawdown = (peak - nav) / peak
        max_drawdown = np.max(drawdown)
        
        # 胜率
        win_rate = np.sum(returns > 0) / len(returns)
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'annual_vol': annual_vol,
            'sharpe': sharpe,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'n_trades': len(returns)
        }


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, data_loader):
        self.data_loader = data_loader
        self.portfolios = {}
        self.results = {}
        
    def run_strategy(self, 
                     strategy_name: str,
                     strategy_func: Callable,
                     start_date: str = '2023-01-01',
                     end_date: str = '2025-12-31',
                     rebalance_freq: str = 'monthly',
                     **kwargs) -> Portfolio:
        """
        运行单个策略
        
        参数:
            strategy_name: 策略名称
            strategy_func: 策略函数，接受data_loader和日期，返回权重字典
            start_date: 开始日期
            end_date: 结束日期
            rebalance_freq: 调仓频率 ('daily', 'weekly', 'monthly')
        """
        print(f"\n运行策略: {strategy_name}")
        print(f"  时间范围: {start_date} ~ {end_date}")
        print(f"  调仓频率: {rebalance_freq}")
        
        # 创建组合
        portfolio = Portfolio(strategy_name)
        
        # 获取数据
        stock_returns = self.data_loader.get_stock_returns_pivot(start_date, end_date)
        
        # 确定调仓日期
        rebalance_dates = self._get_rebalance_dates(stock_returns.index, rebalance_freq)
        print(f"  调仓次数: {len(rebalance_dates)}")
        
        # 运行回测
        current_weights = {}
        rebalance_idx = 0
        
        for i, date in enumerate(stock_returns.index):
            # 检查是否需要调仓
            if rebalance_idx < len(rebalance_dates) and date >= rebalance_dates[rebalance_idx]:
                # 调仓
                current_weights = strategy_func(self.data_loader, date, **kwargs)
                portfolio.set_weights(current_weights)
                rebalance_idx += 1
            
            # 计算当日收益
            if current_weights:
                daily_returns = stock_returns.loc[date].to_dict()
                portfolio.calculate_daily_return(daily_returns)
            else:
                portfolio.returns.append(0.0)
                portfolio.nav.append(portfolio.nav[-1])
        
        # 保存结果
        self.portfolios[strategy_name] = portfolio
        self.results[strategy_name] = portfolio.get_performance()
        
        # 打印绩效
        perf = self.results[strategy_name]
        print(f"\n  绩效指标:")
        print(f"    总收益率: {perf['total_return']:.2%}")
        print(f"    年化收益: {perf['annual_return']:.2%}")
        print(f"    年化波动: {perf['annual_vol']:.2%}")
        print(f"    夏普比率: {perf['sharpe']:.2f}")
        print(f"    最大回撤: {perf['max_drawdown']:.2%}")
        
        return portfolio
    
    def _get_rebalance_dates(self, dates, freq):
        """获取调仓日期"""
        if freq == 'daily':
            return dates.tolist()
        elif freq == 'weekly':
            # 每周第一个交易日
            return dates[dates.to_series().dt.dayofweek == 0].tolist()
        elif freq == 'monthly':
            # 每月第一个交易日
            monthly = dates.to_series().groupby(dates.to_period('M')).first()
            return monthly.tolist()
        else:
            return dates.tolist()
    
    def get_all_results(self) -> pd.DataFrame:
        """获取所有策略的绩效对比"""
        results_df = pd.DataFrame(self.results).T
        results_df.index.name = 'strategy'
        return results_df
    
    def compare_strategies(self):
        """对比所有策略"""
        print("\n" + "=" * 60)
        print("策略绩效对比")
        print("=" * 60)
        
        results_df = self.get_all_results()
        
        # 格式化输出
        display_df = results_df.copy()
        display_df['total_return'] = display_df['total_return'].apply(lambda x: f"{x:.2%}")
        display_df['annual_return'] = display_df['annual_return'].apply(lambda x: f"{x:.2%}")
        display_df['annual_vol'] = display_df['annual_vol'].apply(lambda x: f"{x:.2%}")
        display_df['sharpe'] = display_df['sharpe'].apply(lambda x: f"{x:.2f}")
        display_df['max_drawdown'] = display_df['max_drawdown'].apply(lambda x: f"{x:.2%}")
        display_df['win_rate'] = display_df['win_rate'].apply(lambda x: f"{x:.2%}")
        
        print(display_df.to_string())
        
        return results_df


def main():
    """测试回测引擎"""
    import sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.append(_dir)
    from data_loader import DataLoader
    
    # 加载数据
    loader = DataLoader()
    loader.load_all()
    
    # 创建回测引擎
    engine = BacktestEngine(loader)
    
    # 测试简单策略（等权重）
    def equal_weight_strategy(data_loader, date, n_stocks=10):
        """等权重策略（测试用）"""
        stocks = data_loader.stock_data['stock_code'].unique()[:n_stocks]
        weights = {stock: 1.0 / n_stocks for stock in stocks}
        return weights
    
    # 运行测试
    engine.run_strategy(
        strategy_name='等权重测试',
        strategy_func=equal_weight_strategy,
        start_date='2023-01-01',
        end_date='2023-12-31',
        rebalance_freq='monthly',
        n_stocks=10
    )


if __name__ == '__main__':
    main()
