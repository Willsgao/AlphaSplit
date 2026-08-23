"""
================================================================================
归因分析模块（修复版）
================================================================================
"""

import pandas as pd
import numpy as np
from itertools import combinations
from math import factorial
from typing import Dict, List, Tuple


class AttributionAnalyzer:
    """归因分析器"""
    
    def __init__(self, backtest_engine):
        self.engine = backtest_engine
        self.contributions = {}
        self.shapley_values = {}
        
    def create_combined_portfolio(self):
        """
        创建组合策略（等权组合所有单策略）
        """
        print("\n创建组合策略...")
        
        strategies = list(self.engine.portfolios.keys())
        
        if not strategies:
            print("错误: 没有可用的策略")
            return
        
        # 获取所有策略的净值序列
        nav_dict = {}
        for name, portfolio in self.engine.portfolios.items():
            nav_dict[name] = portfolio.nav
        
        # 确定最短长度
        min_len = min(len(v) for v in nav_dict.values())
        
        # 等权组合
        combined_nav = []
        for i in range(min_len):
            avg_nav = np.mean([nav_dict[name][i] for name in strategies])
            combined_nav.append(avg_nav)
        
        # 创建组合组合对象
        from backtest_engine import Portfolio
        combined = Portfolio('组合策略')
        combined.nav = combined_nav
        
        # 计算收益率
        for i in range(1, len(combined_nav)):
            ret = combined_nav[i] / combined_nav[i-1] - 1
            combined.returns.append(ret)
        
        # 计算绩效
        self.engine.portfolios['组合策略'] = combined
        self.engine.results['组合策略'] = combined.get_performance()
        
        perf = self.engine.results['组合策略']
        print(f"组合策略绩效:")
        print(f"  总收益率: {perf['total_return']:.2%}")
        print(f"  年化收益: {perf['annual_return']:.2%}")
        print(f"  夏普比率: {perf['sharpe']:.2f}")
        
        return combined
    
    def control_variable_attribution(self):
        """
        控制变量法计算各角色贡献
        """
        print("\n" + "=" * 60)
        print("控制变量法归因分析")
        print("=" * 60)
        
        # 确保有组合策略
        if '组合策略' not in self.engine.portfolios:
            self.create_combined_portfolio()
        
        strategies = [s for s in self.engine.portfolios.keys() if s != '组合策略']
        
        # 获取基准收益
        baseline_perf = self.engine.results['组合策略']
        baseline_return = baseline_perf['total_return']
        
        print(f"\n基准策略: 组合策略")
        print(f"基准总收益: {baseline_return:.2%}")
        
        # 计算各策略贡献
        contributions = {}
        
        for strategy in strategies:
            strategy_perf = self.engine.results[strategy]
            strategy_return = strategy_perf['total_return']
            
            # 边际贡献 = 策略收益 - 平均贡献
            avg_contribution = baseline_return / len(strategies)
            contribution = strategy_return - avg_contribution
            
            contributions[strategy] = {
                'strategy_return': strategy_return,
                'contribution': contribution,
                'contribution_pct': contribution / abs(baseline_return) if baseline_return != 0 else 0
            }
            
            print(f"\n{strategy}:")
            print(f"  策略收益: {strategy_return:.2%}")
            print(f"  边际贡献: {contribution:.2%}")
        
        self.contributions = contributions
        return contributions
    
    def shapley_attribution(self, strategies=None, n_samples=1000,
                            coalition_value_fn=None, full_coalition_return=None):
        """
        Shapley值计算各策略/角色的贡献（Sprint 0-4 修复版）

        修复说明（v7.0 大纲 4.4）：
        ============== 旧版致命错误 ==============
        旧版 coalition_value(coalition) = np.mean(strategy_returns[coalition])
        这是"各策略独立收益的算术平均"，根本不是 Shapley 要求的
        "联盟 S 内角色真实合作回测的收益"，导致：
          - v(S) 语义错误（没有真实合作回测）
          - 公理化"有效性"被破坏（Σφᵢ ≠ 组合真实收益）
          - 归因结果毫无意义

        ============== 修复版 ==============
        - coalition_value_fn：由调用方提供"对任意角色组合 S 跑真实回测"
          的收益函数 v(S)。这是 v(S) 的正确来源。
        - 若未提供 coalition_value_fn，则拒绝计算（不再静默用均值），
          明确报错，避免生产环境继续用错误算法。

        参数:
            strategies: 角色/策略名称列表
            n_samples: 当角色数 > 5 时 Monte Carlo 采样次数
            coalition_value_fn: Callable[[Tuple[str,...]], float]，给定角色组合返回真实回测收益
            full_coalition_return: 全集 v(N) 的真实总收益，用于公理化验证；缺省时用 coalition_value_fn(strategies)

        返回:
            dict {角色名: Shapley值}
        """
        print("\n" + "=" * 60)
        print("Shapley值归因分析（修复版）")
        print("=" * 60)

        if strategies is None:
            strategies = [s for s in self.engine.portfolios.keys() if s != '组合策略']

        n_strategies = len(strategies)
        print(f"\n策略数量: {n_strategies}")

        # ---- 核心：特征函数 v(S) ----
        # 正确性要求：v(S) 必须来自"对组合 S 做真实回测"，而不是各策略独立收益的均值。
        # 若调用方未提供 coalition_value_fn，则无法保证正确性，明确拒绝而非静默用错误算法。
        if coalition_value_fn is None:
            raise ValueError(
                "[Sprint 0-4] 必须提供 coalition_value_fn（对任意角色组合 S 跑真实回测的收益函数）。\n"
                "旧版用 np.mean(各策略独立收益) 作为 v(S) 是错误实现，已废弃。\n"
                "请接入 Sprint 1 的'角色决策函数组合回测'（v7.0 大纲 §2/§3）。"
            )

        # 缓存所有子集的 v(S)，避免重复回测（2^5=32 次）
        v_cache = {}

        def coalition_value(coalition):
            if not coalition:
                return 0.0
            key = tuple(sorted(coalition))
            if key not in v_cache:
                v_cache[key] = coalition_value_fn(key)
            return v_cache[key]

        # 计算Shapley值
        shapley_values = {s: 0.0 for s in strategies}

        if n_strategies <= 5:
            # 精确计算（遍历 2^n 子集）
            print("使用精确算法（遍历所有子集）...")
            for strategy in strategies:
                phi = 0.0
                other_strategies = [s for s in strategies if s != strategy]
                for k in range(len(other_strategies) + 1):
                    for coalition in combinations(other_strategies, k):
                        coalition_with = tuple(sorted(coalition + (strategy,)))
                        coalition_without = tuple(sorted(coalition))
                        marginal = coalition_value(coalition_with) - coalition_value(coalition_without)
                        n = n_strategies
                        s = len(coalition)
                        weight = (factorial(s) * factorial(n - s - 1)) / factorial(n)
                        phi += weight * marginal
                shapley_values[strategy] = phi
        else:
            # Monte Carlo采样（角色数 > 5，精确遍历不可行）
            print(f"使用Monte Carlo采样 (n_samples={n_samples})...")
            for _ in range(n_samples):
                perm = list(np.random.permutation(strategies))
                for i, strategy in enumerate(perm):
                    predecessors = perm[:i]
                    v_with = coalition_value(predecessors + [strategy])
                    v_without = coalition_value(predecessors)
                    marginal = v_with - v_without
                    shapley_values[strategy] += marginal / n_samples

        # ---- 公理化验证：有效性（Σφᵢ == v(N)）----
        total_shapley = sum(shapley_values.values())
        full_ret = full_coalition_return if full_coalition_return is not None \
            else coalition_value(tuple(strategies))
        check_pass = full_ret is not None and abs(total_shapley - full_ret) < 1e-6

        print("\nShapley值结果:")
        print("-" * 50)
        for strategy, value in sorted(shapley_values.items(), key=lambda x: x[1], reverse=True):
            pct = value / total_shapley * 100 if abs(total_shapley) > 1e-12 else 0
            print(f"{strategy}:")
            print(f"  Shapley值: {value:.4f}")
            print(f"  贡献占比: {pct:.1f}%")

        # 公理化校验结果（不再强制归一化，保留带符号贡献）
        print("-" * 50)
        if full_ret is not None:
            print(f"公理化校验: Σφᵢ = {total_shapley:.4f}, v(N) = {full_ret:.4f}, "
                  f"{'✅ 通过(差<1e-6)' if check_pass else '❌ 不通过'}")
        self.shapley_values = shapley_values
        self.shapley_check = {
            'sum': total_shapley,
            'full_ret': full_ret,
            'pass': check_pass
        }
        return shapley_values
    
    def generate_attribution_report(self):
        """生成归因报告"""
        print("\n" + "=" * 60)
        print("归因报告")
        print("=" * 60)
        
        # 1. 策略绩效汇总
        print("\n【1. 策略绩效汇总】")
        print("-" * 50)
        
        results_df = self.engine.get_all_results()
        display_cols = ['total_return', 'annual_return', 'sharpe', 'max_drawdown']
        
        if len(results_df) > 0:
            print(results_df[display_cols].to_string())
        
        # 2. 控制变量法归因
        if self.contributions:
            print("\n\n【2. 控制变量法归因】")
            print("-" * 50)
            
            contrib_df = pd.DataFrame(self.contributions).T
            print(contrib_df[['strategy_return', 'contribution']].to_string())
        
        # 3. Shapley值归因
        if self.shapley_values:
            print("\n\n【3. Shapley值归因】")
            print("-" * 50)
            
            total = sum(self.shapley_values.values())
            for strategy, value in sorted(self.shapley_values.items(), key=lambda x: x[1], reverse=True):
                pct = value / total * 100 if total != 0 else 0
                print(f"  {strategy}: {value:.4f} ({pct:.1f}%)")
        
        return {
            'performance': results_df,
            'control_variable': self.contributions,
            'shapley': self.shapley_values
        }


def calculate_attribution(backtest_engine, method='both',
                          coalition_value_fn=None, full_coalition_return=None):
    """
    计算归因

    参数:
        backtest_engine: 回测引擎
        method: 'control_variable' | 'shapley' | 'both'
        coalition_value_fn: (Sprint 0-4) 提供"对任意角色组合 S 跑真实回测收益"的函数。
            这是 Shapley 正确计算 v(S) 的前提。若 method 含 'shapley' 且未提供，
            将抛出异常（而不是用错误的均值近似）。
        full_coalition_return: 全集 v(N) 的真实总收益，用于公理化验证。
    """
    analyzer = AttributionAnalyzer(backtest_engine)
    
    if method in ['control_variable', 'both']:
        analyzer.control_variable_attribution()
    
    if method in ['shapley', 'both']:
        analyzer.shapley_attribution(
            coalition_value_fn=coalition_value_fn,
            full_coalition_return=full_coalition_return,
        )
    
    return analyzer
