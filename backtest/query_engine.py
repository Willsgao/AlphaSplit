"""
回测引擎 JSON 接口层（v4规范）
================================
接收Agent发来的v4查询JSON，执行回测，返回标准结果。

输入: v4 JSON (7个字段)
输出: 结果JSON (overview + role_breakdown + time_series)
中间数据: 保存到 results/{request_id}/ 目录

作者: 徐远 | 日期: 2026-08-19
"""
from __future__ import annotations
import os, sys, json, warnings
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Any

warnings.filterwarnings("ignore")
np.random.seed(42)

# ============================================================
# 路径配置（Sprint 0: 自适应本地/服务器，支持 FINBACK_BASE_DIR 环境变量覆盖）
# ============================================================
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getenv("FINBACK_BASE_DIR"):
    BASE_DIR = os.environ["FINBACK_BASE_DIR"]
elif os.path.isdir(os.path.join(_BACKTEST_DIR, "..", "data")):
    BASE_DIR = os.path.normpath(os.path.join(_BACKTEST_DIR, ".."))
else:
    BASE_DIR = "/home/ubuntu/FinTech"
DATA_DIR = f"{BASE_DIR}/data/processed"
RESULTS_DIR = f"{BASE_DIR}/backtest/results"

sys.path.insert(0, _BACKTEST_DIR)
from quant_engine import compute_factor, ROLE_FACTORS, compute_financial_factors, zscore_financial_factors
from timing_module import TimingModule, apply_timing
from risk_control_module import RiskControlModule, get_risk_summary
from industry_analyst import IndustryAnalyst, get_industry_mapping
from quant_analyst import QuantAnalyst


# ============================================================
# v4 查询解析器
# ============================================================
class QueryParser:
    """解析v4 JSON查询，填充默认值"""
    
    VALID_ROLES = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]
    VALID_BENCHMARKS = {"hs300": "沪深300", "csi500": "中证500", "shanghai": "上证指数"}
    VALID_FREQS = ["monthly", "quarterly", "yearly"]
    
    @staticmethod
    def parse(query_json: dict) -> dict:
        """解析查询JSON，返回标准化的查询参数"""
        q = query_json.get("query", {})
        
        # 1. time_range
        time_range = q.get("time_range", {})
        start_date = time_range.get("start_date") if time_range else None
        end_date = time_range.get("end_date") if time_range else None
        
        # 2. target_role
        target_role = q.get("target_role")
        if target_role and target_role not in QueryParser.VALID_ROLES:
            raise BacktestError("ROLE_NOT_FOUND", f"无效角色: {target_role}，可选: {QueryParser.VALID_ROLES}")
        
        # 3. industry
        industry = q.get("industry")
        
        # 4. role_weights（Sprint 1：占比语义，未给角色自动补等权，保证总和=1）
        role_weights = q.get("role_weights")
        if role_weights:
            # 验证角色名
            for role in role_weights:
                if role not in QueryParser.VALID_ROLES:
                    raise BacktestError("ROLE_NOT_FOUND", f"无效角色: {role}")
            # 语义：role_weights 为"相对调节系数"（Sprint 1 方案A）
            #   - 传入的角色：使用给定系数（如 {个股:3.0} 表示个股调节系数为3倍）
            #   - 未传入的角色：系数默认 1.0（等权，无HR偏好）
            #   - 不做归一化/补等权，最终归一化在 _assemble_results 的"份额×系数→归一化"中完成
            role_weights = {k: float(v) for k, v in role_weights.items()}
        
        # 5. benchmark
        benchmark = q.get("benchmark", "hs300")
        if benchmark not in QueryParser.VALID_BENCHMARKS:
            raise BacktestError("INVALID_PARAM", f"无效基准: {benchmark}，可选: {list(QueryParser.VALID_BENCHMARKS.keys())}")
        
        # 6. rebalance_freq
        rebalance_freq = q.get("rebalance_freq", "monthly")
        if rebalance_freq not in QueryParser.VALID_FREQS:
            raise BacktestError("INVALID_PARAM", f"无效调仓频率: {rebalance_freq}，可选: {QueryParser.VALID_FREQS}")
        
        # 7. granularity
        granularity = q.get("granularity", "monthly")
        if granularity not in QueryParser.VALID_FREQS:
            raise BacktestError("INVALID_PARAM", f"无效粒度: {granularity}，可选: {QueryParser.VALID_FREQS}")
        
        return {
            "start_date": start_date,
            "end_date": end_date,
            "target_role": target_role,
            "industry": industry,
            "role_weights": role_weights,
            "benchmark": benchmark,
            "rebalance_freq": rebalance_freq,
            "granularity": granularity,
        }


# ============================================================
# 数据加载器
# ============================================================
class DataLoader:
    """加载并过滤回测所需数据"""
    
    def __init__(self):
        self.df_daily = None
        self.df_index = None
        self.df_industry = None
        self.df_financial = None
        self._loaded = False
    
    def load(self):
        """加载所有数据"""
        if self._loaded:
            return
        
        print("[DataLoader] 加载数据...")
        
        # 日K线（Sprint 0-2: 优先前复权数据 hs300_daily_qfq.csv）
        daily_file = f"{DATA_DIR}/hs300_daily_qfq.csv"
        if not os.path.exists(daily_file):
            daily_file = f"{DATA_DIR}/hs300_daily_cleaned.csv"
            print("  ⚠ 未找到复权数据，回退到未复权 hs300_daily_cleaned.csv")
        self.df_daily = pd.read_csv(daily_file, encoding="utf-8-sig")
        self.df_daily["date"] = pd.to_datetime(self.df_daily["date"])
        self.df_daily = self.df_daily.rename(columns={"stock_code": "symbol"})
        self.df_daily = self.df_daily.sort_values(["symbol", "date"]).reset_index(drop=True)
        
        # 补齐列
        if "open" not in self.df_daily.columns and "close" in self.df_daily.columns:
            self.df_daily["open"] = self.df_daily["close"]
        if "high" not in self.df_daily.columns:
            self.df_daily["high"] = self.df_daily["close"]
        if "low" not in self.df_daily.columns:
            self.df_daily["low"] = self.df_daily["close"]
        
        # 指数
        self.df_index = pd.read_csv(f"{DATA_DIR}/hs300_index_daily.csv", encoding="utf-8-sig")
        self.df_index["date"] = pd.to_datetime(self.df_index["date"])
        self.df_index = self.df_index.sort_values("date").reset_index(drop=True)
        
        # 行业映射
        self.df_industry = pd.read_csv(f"{DATA_DIR}/stock_industry_mapping.csv", encoding="utf-8-sig")
        
        # 财务数据（Sprint 0-3: 优先清洗后数据 financial_monthly_clean.csv）
        fin_file = f"{DATA_DIR}/financial_monthly_clean.csv"
        if not os.path.exists(fin_file):
            fin_file = f"{DATA_DIR}/financial_monthly.csv"
            print("  ⚠ 未找到清洗后财务数据，回退到原始文件")
        self.df_financial = pd.read_csv(fin_file, encoding="utf-8-sig")
        self.df_financial["date"] = pd.to_datetime(self.df_financial["date"])
        self.df_financial = self.df_financial.rename(columns={"stock_code": "symbol"})
        
        # 股票代码 → 中文简称（用于前端展示）
        self.symbol_names: dict[str, str] = {}
        if "stock_name" in self.df_industry.columns:
            code_col = "stock_code" if "stock_code" in self.df_industry.columns else "symbol"
            for _, row in self.df_industry.iterrows():
                code = str(row[code_col]).split(".")[0].zfill(6)
                name = str(row.get("stock_name", "")).strip()
                if name:
                    self.symbol_names[code] = name
        if "stock_name" in self.df_daily.columns:
            for sym, name in (
                self.df_daily[["symbol", "stock_name"]]
                .dropna()
                .drop_duplicates("symbol")
                .values
            ):
                code = str(sym).split(".")[0].zfill(6)
                if code not in self.symbol_names and str(name).strip():
                    self.symbol_names[code] = str(name).strip()
        
        self._loaded = True
        print(f"[DataLoader] 完成: {len(self.df_daily):,} 条日线, {len(self.df_industry)} 只股票")
    
    def stock_label(self, symbol: str) -> str:
        """返回「中文名（代码）」便于前端展示。"""
        code = str(symbol).split(".")[0].zfill(6)
        name = self.symbol_names.get(code, "")
        return f"{name}（{code}）" if name else code
    
    def filter_by_date(self, start_date: Optional[str], end_date: Optional[str]):
        """按日期过滤"""
        self.load()
        df = self.df_daily.copy()
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        return df
    
    def filter_by_industry(self, df: pd.DataFrame, industry: Optional[str]) -> pd.DataFrame:
        """按行业过滤股票"""
        if not industry:
            return df
        self.load()
        stocks_in_industry = self.df_industry[
            self.df_industry["industry"].str.strip() == industry
        ]["stock_code"].tolist()
        # 统一类型比较（都转为字符串）
        stocks_str = [str(s) for s in stocks_in_industry]
        df = df.copy()
        df["symbol"] = df["symbol"].astype(str)
        return df[df["symbol"].isin(stocks_str)]
    
    def get_index_returns(self, start_date: Optional[str], end_date: Optional[str]) -> pd.Series:
        """获取指数收益率序列"""
        self.load()
        df = self.df_index.copy()
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        df["index_return"] = df["close"].pct_change()
        return df.set_index("date")["index_return"]


# ============================================================
# 中间数据记录器
# ============================================================
class IntermediateRecorder:
    """记录回测过程中的中间数据"""
    
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.output_dir = f"{RESULTS_DIR}/{request_id}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 中间数据容器
        self.factor_scores = []      # 因子得分
        self.selections = []         # 选股记录
        self.rebalance_events = []   # 调仓事件
        self.daily_returns = []      # 每日收益
        self.monthly_stats = []      # 月度统计
    
    def record_factor_score(self, role: str, date: str, symbol: str, 
                            factors: dict, composite_score: float):
        """记录因子得分"""
        self.factor_scores.append({
            "role": role, "date": date, "symbol": symbol,
            "factors": factors, "composite_score": composite_score
        })
    
    def record_selection(self, role: str, period: str, stocks: list, 
                         scores: dict = None):
        """记录选股结果"""
        self.selections.append({
            "role": role, "period": period,
            "stocks": stocks, "scores": scores or {}
        })
    
    def record_rebalance(self, role: str, date: str, action: str,
                         old_stocks: list = None, new_stocks: list = None,
                         turnover: float = 0):
        """记录调仓事件"""
        self.rebalance_events.append({
            "role": role, "date": date, "action": action,
            "old_stocks": old_stocks or [], "new_stocks": new_stocks or [],
            "turnover": turnover
        })
    
    def record_daily_return(self, role: str, date: str, 
                            portfolio_return: float, benchmark_return: float):
        """记录每日收益"""
        self.daily_returns.append({
            "role": role, "date": date,
            "portfolio_return": portfolio_return,
            "benchmark_return": benchmark_return
        })
    
    def record_monthly_stat(self, role: str, period: str,
                            return_val: float, benchmark: float,
                            excess: float, stocks_count: int):
        """记录月度统计"""
        self.monthly_stats.append({
            "role": role, "period": period,
            "return": return_val, "benchmark": benchmark,
            "excess": excess, "stocks_count": stocks_count
        })
    
    def save_all(self):
        """保存所有中间数据"""
        # 因子得分（采样保存，避免文件过大）
        if self.factor_scores:
            # 只保存每月最后一天的得分
            df = pd.DataFrame(self.factor_scores)
            df["date"] = pd.to_datetime(df["date"])
            df["ym"] = df["date"].dt.to_period("M")
            sampled = df.groupby(["role", "ym"]).apply(
                lambda g: g[g["date"] == g["date"].max()]
            ).reset_index(drop=True)
            sampled.drop(columns=["ym"], inplace=True, errors="ignore")
            sampled.to_csv(f"{self.output_dir}/factor_scores.csv", 
                          index=False, encoding="utf-8-sig")
            print(f"  [保存] factor_scores.csv ({len(sampled)} 条)")
        
        # 选股记录
        if self.selections:
            records = []
            for s in self.selections:
                for stock in s["stocks"]:
                    records.append({
                        "role": s["role"], "period": s["period"],
                        "stock": stock, 
                        "score": s["scores"].get(stock, None)
                    })
            pd.DataFrame(records).to_csv(
                f"{self.output_dir}/selections.csv",
                index=False, encoding="utf-8-sig"
            )
            print(f"  [保存] selections.csv ({len(records)} 条)")
        
        # 调仓事件
        if self.rebalance_events:
            pd.DataFrame(self.rebalance_events).to_csv(
                f"{self.output_dir}/rebalance_events.csv",
                index=False, encoding="utf-8-sig"
            )
            print(f"  [保存] rebalance_events.csv ({len(self.rebalance_events)} 条)")
        
        # 每日收益
        if self.daily_returns:
            pd.DataFrame(self.daily_returns).to_csv(
                f"{self.output_dir}/daily_returns.csv",
                index=False, encoding="utf-8-sig"
            )
            print(f"  [保存] daily_returns.csv ({len(self.daily_returns)} 条)")
        
        # 月度统计
        if self.monthly_stats:
            pd.DataFrame(self.monthly_stats).to_csv(
                f"{self.output_dir}/monthly_stats.csv",
                index=False, encoding="utf-8-sig"
            )
            print(f"  [保存] monthly_stats.csv ({len(self.monthly_stats)} 条)")
        
        # 保存查询参数
        print(f"  [保存] 中间数据目录: {self.output_dir}/")


# 角色中文简称（Shapley 联盟轴标签）
ROLE_SHORT_NAMES = {
    "行业分析师": "行业",
    "个股分析师": "个股",
    "策略分析师": "策略",
    "量化分析师": "量化",
    "风控分析师": "风控",
}


def coalition_label(roles: list[str]) -> str:
    if not roles:
        return "空联盟"
    return "+".join(ROLE_SHORT_NAMES.get(r, r) for r in roles)


# ============================================================
# 回测执行器
# ============================================================
class BacktestExecutor:
    
    # 回测参数
    TOP_N = 10
    COMMISSION_RATE = 0.001
    SLIPPAGE_RATE = 0.001
    RISK_FREE_RATE = 0.02
    
    DYNAMIC_ROLES = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]
    
    def __init__(self, data_loader: DataLoader, recorder: IntermediateRecorder, progress=None):
        self.loader = data_loader
        self.recorder = recorder
        if progress is None:
            from progress_reporter import ProgressReporter
            progress = ProgressReporter()
        self.progress = progress
        # Sprint 1: 模块实例提升到 executor 级，跨 Shapley 子集共享缓存（性能优化）
        from timing_module import TimingModule
        from risk_control_module import RiskControlModule
        from industry_analyst import IndustryAnalyst
        from quant_analyst import QuantAnalyst
        self.timing = TimingModule(target_vol=0.15, lookback=20)
        self.risk_control = RiskControlModule({
            'max_single': 0.05,
            'max_industry': 0.25,
            'stop_loss_monthly': -0.05,
        })
        self.industry_analyst = IndustryAnalyst(top_n=3, lookback=20)
        self.quant_analyst = QuantAnalyst(n_strategies=4)

    def _get_valid_industries(self) -> list:
        """获取有效行业列表（来自 stock_industry_mapping.csv），供 industry 校验"""
        valid = getattr(self, "_valid_industries_cache", None)
        if valid is not None:
            return valid
        try:
            inds = sorted(self.loader.df_industry["industry"].str.strip().unique().tolist())
        except Exception:
            inds = []
        self._valid_industries_cache = inds
        return inds

    def execute(self, params: dict) -> dict:
        """执行回测，返回结果（Pipeline + Leave-One-Out归因）"""
        self.loader.load()

        # 0. 校验行业名有效性（Sprint 1：防止 Agent 传入不存在的行业导致静默空池）
        industry_input = params.get("industry")
        if industry_input:
            valid_industries = self._get_valid_industries()
            matched = [ind for ind in valid_industries if ind.strip() == industry_input.strip()]
            if not matched:
                # 尝试模糊匹配（支持 Agent 传入近似名）
                close = [ind for ind in valid_industries if industry_input.strip() in ind or ind in industry_input.strip()]
                hint = f"，近似: {close[:5]}" if close else ""
                raise BacktestError(
                    "INDUSTRY_NOT_FOUND",
                    f"无效行业「{industry_input}」，请在以下行业中选择（共{len(valid_industries)}个）：\n"
                    f"{valid_industries}{hint}"
                )

        # 1. 过滤数据
        df_daily = self.loader.filter_by_date(params["start_date"], params["end_date"])
        df_daily = self.loader.filter_by_industry(df_daily, params["industry"])
        
        if len(df_daily) == 0:
            df_by_date = self.loader.filter_by_date(params["start_date"], params["end_date"])
            if len(df_by_date) == 0:
                raise BacktestError("NO_DATA", f"日期范围 {params['start_date']} ~ {params['end_date']} 内无数据，数据范围为 2022-06-06 ~ 2025-12-31")
            else:
                raise BacktestError("NO_DATA", f"行业「{params['industry']}」在该日期范围内无数据")
        
        dates = sorted(df_daily["date"].unique())
        stocks = sorted(df_daily["symbol"].unique())
        
        if len(stocks) < self.TOP_N:
            print(f"[警告] 行业「{params.get('industry', '全行业')}」只有 {len(stocks)} 只股票，不足 {self.TOP_N} 只，将使用全部股票")
        
        print(f"[Backtest] {len(stocks)} 只股票, {len(dates)} 个交易日")
        self.progress.stage(
            2, 7, "filter",
            f"数据过滤完成：{len(stocks)} 只股票，{len(dates)} 个交易日",
            12,
            {"stocks": len(stocks), "trading_days": len(dates)},
        )
        self.progress.data_snapshot(len(stocks), len(dates))
        
        # 2. 确定要计算的角色
        # Sprint 1 修复：始终计算全集 5 角色，保证 Shapley 归因需要完整的选股结果。
        # target_role 仅用于展示聚焦（query_summary / 前端高亮），不影响归因计算。
        roles_to_calc = self.DYNAMIC_ROLES
        
        # 3. 计算因子并选股（各角色独立计算）
        self.progress.stage(3, 7, "factors", "开始计算五类角色因子并选股…", 18)
        role_selections = self._compute_factors_and_select(df_daily, stocks, roles_to_calc, params)
        
        # 4. 获取基准收益（沪深300）
        index_returns = self.loader.get_index_returns(params["start_date"], params["end_date"])
        
        # 5. Pipeline回测：整合各角色决策
        self.progress.stage(4, 7, "pipeline", "Pipeline 全角色组合回测…", 48)
        pipeline_results = self._run_pipeline_backtest(
            df_daily, dates, role_selections, index_returns, params
        )
        
        # 6. 归因（Sprint 1：默认使用 Shapley 归因；可用 params["attribution_method"] 切换）
        attribution_method = params.get("attribution_method", "shapley")
        if attribution_method == "shapley":
            self.progress.stage(5, 7, "shapley", "Shapley 归因：遍历角色子集回测…", 52)
            attribution = self._compute_shapley_attribution(
                df_daily, dates, role_selections, index_returns, params, pipeline_results
            )
        else:
            # 兼容旧版：相对基准归因（仅在显式指定时使用）
            attribution = self._compute_relative_benchmark_attribution(
                df_daily, dates, role_selections, index_returns, params, pipeline_results
            )
        
        pipeline_ret = pipeline_results.get("total_return", 0)
        self.progress.log(f"Pipeline 组合累计收益：{pipeline_ret:.2%}")
        monthly_series = pipeline_results.get("monthly_returns")
        monthly_payload = []
        if monthly_series is not None and len(monthly_series) > 0:
            cum = 1.0
            for idx, ret in monthly_series.items():
                cum *= 1 + float(ret)
                monthly_payload.append(
                    {
                        "month": str(idx),
                        "return": float(ret),
                        "cumulative": cum - 1.0,
                    }
                )
        self.progress.pipeline_result(float(pipeline_ret), monthly_payload)
        
        # 7. 计算绩效指标
        full_returns = pipeline_results["monthly_returns"]
        performance = self._compute_single_performance(full_returns, index_returns)
        
        # 8. 生成时间序列
        time_series = self._generate_time_series(
            {"组合": full_returns}, index_returns, params["granularity"]
        )
        
        # 9. 组装结果
        results = self._assemble_results(performance, attribution, time_series, params)
        
        return results
    
    def _compute_factors_and_select(self, df_daily, stocks, roles, params):
        """计算因子并选股"""
        print("[Backtest] 计算因子...")
        role_selections = {}
        role_list = [r for r in roles if r in ROLE_FACTORS]
        
        for role_idx, role in enumerate(role_list):
            self.progress.stage(
                3, 7, "factors",
                f"计算 {role} 因子选股（{role_idx + 1}/{len(role_list)}）…",
                18 + role_idx * 5,
                {"role": role, "role_index": role_idx + 1, "role_total": len(role_list)},
            )
            
            factor_defs = ROLE_FACTORS[role]
            factor_dfs = []
            
            # Sprint 1 性能优化：预分组一次，避免对每只股票反复全表过滤（O(股票数×全表)→O(全表)）
            # 说明：进程池并行实测在 flask 环境下收益不稳定且可能更慢，故采用串行 + 预分组 + 因子向量化
            stock_groups = {sym: g.copy() for sym, g in df_daily.groupby("symbol")}
            
            for fdef in factor_defs:
                col_name = fdef["col"]
                all_factors = []
                
                for sym, stock_df in stock_groups.items():
                    if len(stock_df) < 30:
                        continue
                    try:
                        result = compute_factor(
                            stock_df, base=fdef["base"], transform=fdef["transform"],
                            params=fdef.get("params", {"window": 5, "norm": 20}),
                            factor_col=col_name
                        )
                        all_factors.append(result[["date", "symbol", col_name]])
                    except:
                        pass
                
                if all_factors:
                    factor_dfs.append(pd.concat(all_factors, ignore_index=True))
            
            if not factor_dfs:
                continue
            
            # 合并因子
            merged = factor_dfs[0]
            for fd in factor_dfs[1:]:
                merged = merged.merge(fd, on=["date", "symbol"], how="outer")
            
            factor_cols = [c for c in merged.columns if c not in ("date", "symbol")]
            merged["composite_score"] = merged[factor_cols].mean(axis=1)
            merged["year_month"] = merged["date"].dt.to_period("M")
            
            # 选股（修复前视偏差 v7.0：当月末选股 → 下一个月持有）
            # 语义：selections["ym"] 存的是 "ym-1 月末依据因子选出的股票"，供 ym 月持有
            # 这样避免了"用当月信息选股、当月月初建仓"的前视偏差
            sorted_months = sorted(merged["year_month"].unique())
            selections = {}
            for idx, ym in enumerate(sorted_months):
                group = merged[merged["year_month"] == ym]
                month_end = group[group["date"] == group["date"].max()]
                # 动态调整选股数量
                actual_top_n = min(self.TOP_N, len(month_end))
                if actual_top_n < 1:
                    continue
                top = month_end.nlargest(actual_top_n, "composite_score")
                top_stocks = top["symbol"].tolist()
                top_scores = dict(zip(top["symbol"], top["composite_score"]))
                
                # 记录中间数据（记录"选股时点"ym 的决策）
                self.recorder.record_selection(role, str(ym), top_stocks, top_scores)
                
                for _, row in top.iterrows():
                    score_dict = {c: row[c] for c in factor_cols if pd.notna(row[c])}
                    self.recorder.record_factor_score(
                        role, str(row["date"])[:10], row["symbol"],
                        score_dict, row["composite_score"]
                    )
                
                # 前视修复：ym 末选出的股票，用于 ym+1 月持有
                # 最后一个月选出的股票无后续持有月（未来无数据），自然丢弃
                if idx < len(sorted_months) - 1:
                    hold_month = sorted_months[idx + 1]
                    selections[str(hold_month)] = top_stocks
            
            role_selections[role] = selections
            print(f"  [{role}] {len(selections)} 个月选股完成（月末选股，次月持有）")
            self.progress.log(f"✓ {role}：{len(selections)} 个月选股完成")
            last_key = sorted(selections.keys())[-1] if selections else None
            sample_codes = selections.get(last_key, [])[:5] if last_key else []
            sample_labels = [self.loader.stock_label(s) for s in sample_codes]
            self.progress.role_factor_done(
                role,
                len(selections),
                sample_codes,
                role_idx + 1,
                len(role_list),
                18 + (role_idx + 1) * 5,
                sample_labels=sample_labels,
            )
        
        return role_selections
    
    def _simulate_backtest(self, df_daily, dates, role_selections, params):
        """回测模拟"""
        print("[Backtest] 模拟交易...")
        
        # 计算日收益率
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        role_returns = {}
        
        for role, selections in role_selections.items():
            monthly_returns = []
            prev_stocks = []
            
            sorted_months = sorted(selections.keys())
            for ym_str in sorted_months:
                ym = pd.Period(ym_str)
                stocks_in = selections[ym_str]
                
                # 确保stocks_in是字符串列表
                stocks_in = [str(s) for s in stocks_in]
                
                # 记录调仓事件
                if prev_stocks:
                    new_set = set(stocks_in) - set(prev_stocks)
                    old_set = set(prev_stocks) - set(stocks_in)
                    turnover = len(new_set) + len(old_set)
                    self.recorder.record_rebalance(
                        role, str(ym.start_time)[:10], "rebalance",
                        list(old_set), list(new_set), turnover
                    )
                else:
                    self.recorder.record_rebalance(
                        role, str(ym.start_time)[:10], "initial", 
                        [], stocks_in, len(stocks_in)
                    )
                prev_stocks = stocks_in
                
                # 获取月度数据
                month_start = ym.start_time
                if ym_str == sorted_months[-1]:
                    month_end = pd.Timestamp(dates[-1])
                else:
                    month_end = (ym + 1).start_time
                
                month_data = df_daily[
                    (df_daily["symbol"].isin(stocks_in)) &
                    (df_daily["date"] >= month_start) &
                    (df_daily["date"] < month_end)
                ]
                
                if len(month_data) == 0:
                    continue
                
                # 等权组合日收益
                daily_rets = month_data.groupby("date")["return"].mean()
                
                # 扣除调仓成本
                cost = (self.COMMISSION_RATE + self.SLIPPAGE_RATE) * 2
                if len(daily_rets) > 0:
                    daily_rets.iloc[0] -= cost
                
                # 记录每日收益
                for dt, ret in daily_rets.items():
                    self.recorder.record_daily_return(role, str(dt)[:10], ret, 0)
                
                # 月收益
                month_ret = (1 + daily_rets).prod() - 1
                monthly_returns.append({"month": ym, "return": month_ret})
            
            if monthly_returns:
                ret_df = pd.DataFrame(monthly_returns).set_index("month")
                role_returns[role] = ret_df["return"]
                total_ret = (1 + ret_df["return"]).prod() - 1
                print(f"  [{role}] 累计收益: {total_ret:.2%}")
        
        return role_returns
    
    def _run_pipeline_backtest(self, df_daily, dates, role_selections, index_returns, params,
                               active_roles=None):
        """
        Pipeline回测：整合各角色决策，生成最终组合
        
        Pipeline流程：
        1. 行业分析师选择行业（如果用户未指定行业）
        2. 个股分析师选股（用因子在行业内选股）
        3. 量化分析师优化（多策略平均）
        4. 策略分析师择时（仓位调整）
        5. 风控分析师约束（风险控制）

        Sprint 1（v7.0 §3.5）：支持 Shapley 归因所需的"任意角色子集"回测。
        - active_roles: 参与的角色集合（其余角色"缺席即跳过"用中性策略）。
          为 None 时全部参与（默认完整 Pipeline）。
        - 中性策略定义（缺席即跳过）：
            行业分析师缺席 → 不做行业选择（全池）
            个股分析师缺席 → 不精选，用选中行业内全部股票等权
            量化分析师缺席 → 不做多策略优化
            策略分析师缺席 → 满仓（position_ratio=1.0）
            风控分析师缺席 → 无风控约束
        """
        if active_roles is None:
            active_roles = set(self.DYNAMIC_ROLES)
        active_roles = set(active_roles)
        # 输出到控制台时只打一次（Shapley 遍历时避免刷屏）
        is_shapley_run = active_roles != set(self.DYNAMIC_ROLES)
        if not is_shapley_run:
            print("[Backtest] Pipeline回测...")
        
        # 使用 executor 级共享实例（跨 Shapley 子集复用缓存）
        timing = self.timing
        risk_control = self.risk_control
        industry_analyst = self.industry_analyst
        quant_analyst = self.quant_analyst
        
        # 获取行业映射
        industry_mapping = get_industry_mapping(self.loader)
        
        # 检查用户是否指定了行业
        user_industry = params.get("industry")
        
        # 计算日收益率
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        # 以个股分析师的选股为基础
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        if stock_role is None or not role_selections[stock_role]:
            raise ValueError("没有可用的选股结果")
        
        selections = role_selections[stock_role]
        
        monthly_returns = []
        prev_month_ret = 0.0
        
        # 角色参与标记（Sprint 1：缺席即跳过）
        industry_active = "行业分析师" in active_roles
        stock_active = "个股分析师" in active_roles
        quant_active = "量化分析师" in active_roles
        strategy_active = "策略分析师" in active_roles
        risk_active = "风控分析师" in active_roles
        
        sorted_months = sorted(selections.keys())
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            month_start = ym.start_time
            
            # ========== 步骤1：行业分析师选择行业 ==========
            if user_industry:
                # 用户指定了行业，直接使用（不依赖行业分析师）
                selected_industries = [user_industry]
            elif industry_active:
                # 行业分析师选择行业（多因子模型）
                selected_industries = industry_analyst.select_industries(
                    df_daily, industry_mapping, self.loader.df_index, month_start,
                    verbose=not is_shapley_run
                )
            else:
                # 行业分析师缺席：不做行业选择（全池）
                selected_industries = None
            
            # 过滤出选中行业的股票（行业分析师缺席时不过滤，全池）
            if selected_industries is None:
                stocks_in_industry = None  # 表示不过滤
            else:
                stocks_in_industry = [
                    s for s, ind in industry_mapping.items() 
                    if ind in selected_industries
                ]
            
            # ========== 步骤2：个股分析师选股 ==========
            if stock_active:
                # 使用已有的选股结果（role_selections）
                stocks_in = selections[ym_str]
                # 确保stocks_in是字符串列表
                stocks_in = [str(s) for s in stocks_in]
                # 只保留选中行业的股票（行业缺席时不过滤）
                if stocks_in_industry is not None:
                    stocks_in = [s for s in stocks_in if s in stocks_in_industry]
            else:
                # 个股分析师缺席：不精选，用选中行业内全部股票（行业缺席则全池）
                if stocks_in_industry is not None:
                    stocks_in = stocks_in_industry[:self.TOP_N * 2]
                else:
                    # 全池中性选择：取所有股票（等权，后续截断）
                    stocks_in = list(industry_mapping.keys())
            
            if not stocks_in:
                # 如果没有股票，使用行业内的所有股票（或全池）
                if stocks_in_industry is not None:
                    stocks_in = stocks_in_industry[:self.TOP_N]
                else:
                    stocks_in = list(industry_mapping.keys())[:self.TOP_N]
            
            # ========== 步骤3：量化分析师优化 ==========
            # 使用多策略平均优化选股（量化分析师缺席时跳过）
            if quant_active and len(stocks_in) > self.TOP_N:
                # 获取月初之前的数据用于优化
                hist_data = df_daily[df_daily["date"] < month_start]
                if len(hist_data) > 0:
                    optimized_stocks, _ = quant_analyst.optimize_selection(
                        hist_data, stocks_in, stock_role, self.TOP_N
                    )
                    if optimized_stocks:
                        stocks_in = optimized_stocks
            elif not quant_active:
                # 量化分析师缺席：截断到 TOP_N（等权持有，不做多策略优化）
                if len(stocks_in) > self.TOP_N:
                    stocks_in = stocks_in[:self.TOP_N]
            
            # 计算初始权重（等权）
            n_stocks = len(stocks_in)
            weights = {s: 1.0 / n_stocks for s in stocks_in}
            
            # ========== 步骤4：策略分析师择时 ==========
            if strategy_active:
                position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
                weights = apply_timing(weights, position_ratio)
            else:
                # 策略分析师缺席：满仓
                position_ratio = 1.0
            
            # ========== 步骤5：风控分析师约束 ==========
            if risk_active:
                weights = risk_control.apply_all(
                    weights, industry_mapping, 
                    monthly_return=prev_month_ret,
                    stock_returns=None
                )
            # 风控分析师缺席：无约束，直接使用权重
            
            # 记录调仓事件
            self.recorder.record_rebalance(
                "组合", str(ym.start_time)[:10], "rebalance",
                [], stocks_in, len(stocks_in)
            )
            
            # 获取月度数据
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            # 按权重加权计算日收益
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            
            # 扣除调仓成本
            cost = (self.COMMISSION_RATE + self.SLIPPAGE_RATE) * 2
            if len(daily_rets) > 0:
                daily_rets.iloc[0] -= cost
            
            # 记录每日收益
            for i, dt in enumerate(sorted(month_data["date"].unique())):
                self.recorder.record_daily_return("组合", str(dt)[:10], daily_rets.iloc[i], 0)
            
            # 月收益
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        # 构建收益序列
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        monthly_returns_series = ret_df["return"]
        
        total_ret = (1 + monthly_returns_series).prod() - 1
        if not is_shapley_run:
            print(f"  [Pipeline] 累计收益: {total_ret:.2%}, 仓位比: {position_ratio:.2%}")
        
        return {
            "monthly_returns": monthly_returns_series,
            "total_return": total_ret,
        }
    
    def _compute_relative_benchmark_attribution(self, df_daily, dates, role_selections, 
                                                index_returns, params, full_results):
        """
        相对基准归因：每个角色的贡献 = 该角色的决策 vs 该角色的"默认/中性"策略
        
        - 行业分析师: 选出的行业 vs 等权所有行业
        - 量化分析师: 因子选股 vs 随机选股
        - 个股分析师: 深度精选 vs 量化候选池
        - 策略分析师: 择时仓位 vs 永远满仓
        - 风控分析师: 风控后 vs 无风控
        """
        print("[Backtest] 相对基准归因...")
        
        full_return = full_results["total_return"]
        
        # 获取基准收益（沪深300）
        index_monthly = index_returns.resample('M').apply(lambda x: (1 + x).prod() - 1)
        index_monthly.index = index_monthly.index.to_period('M')
        
        benchmark_monthly = []
        for m in full_results["monthly_returns"].index:
            if m in index_monthly.index:
                benchmark_monthly.append(index_monthly[m])
            else:
                benchmark_monthly.append(0)
        benchmark_series = pd.Series(benchmark_monthly, index=full_results["monthly_returns"].index)
        benchmark_return = float((1 + benchmark_series).prod() - 1)
        
        attribution = {}
        
        # 计算每个角色的"基准"收益（默认/中性策略）
        role_baselines = {}
        
        # 1. 行业分析师基准：等权所有行业
        print("  [行业分析师] 计算基准（等权所有行业）...")
        baseline_industry = self._run_baseline_equal_weight_industry(
            df_daily, dates, role_selections, index_returns, params
        )
        role_baselines["行业分析师"] = baseline_industry["total_return"]
        
        # 2. 量化分析师基准：随机选股
        print("  [量化分析师] 计算基准（随机选股）...")
        baseline_quant = self._run_baseline_random_selection(
            df_daily, dates, role_selections, index_returns, params
        )
        role_baselines["量化分析师"] = baseline_quant["total_return"]
        
        # 3. 个股分析师基准：直接用量化候选池（不做深度精选）
        print("  [个股分析师] 计算基准（量化候选池）...")
        baseline_stock = self._run_baseline_quant_candidates(
            df_daily, dates, role_selections, index_returns, params
        )
        role_baselines["个股分析师"] = baseline_stock["total_return"]
        
        # 4. 策略分析师基准：永远满仓
        print("  [策略分析师] 计算基准（永远满仓）...")
        baseline_timing = self._run_baseline_always_invested(
            df_daily, dates, role_selections, index_returns, params
        )
        role_baselines["策略分析师"] = baseline_timing["total_return"]
        
        # 5. 风控分析师基准：无风控约束
        print("  [风控分析师] 计算基准（无风控）...")
        baseline_risk = self._run_baseline_no_risk_control(
            df_daily, dates, role_selections, index_returns, params
        )
        role_baselines["风控分析师"] = baseline_risk["total_return"]
        
        # 计算每个角色的相对贡献
        for role in self.DYNAMIC_ROLES:
            if role not in role_selections:
                attribution[role] = {
                    "contribution_raw": 0.0,
                    "contribution_pct": 0.0,
                    "highlight": "未参与",
                }
                continue
            
            baseline_return = role_baselines.get(role, full_return)
            # 相对贡献 = 实际收益 - 基准收益（正表示比默认好，负表示比默认差）
            contribution = full_return - baseline_return
            
            attribution[role] = {
                "contribution_raw": contribution,
                "baseline_return": baseline_return,
            }
            
            print(f"  [{role}] 实际收益: {full_return:.2%}, 基准收益: {baseline_return:.2%}, 相对贡献: {contribution:+.2%}")
        
        # 归一化：确保所有贡献为正
        raw_contributions = {r: attribution[r]["contribution_raw"] for r in self.DYNAMIC_ROLES if r in attribution}
        
        # 将贡献转换为正数（加上最小值的绝对值 + 一个小的正数）
        min_contribution = min(raw_contributions.values())
        if min_contribution < 0:
            offset = abs(min_contribution) + 0.01  # 加上最小值的绝对值 + 1%
        else:
            offset = 0
        
        positive_contributions = {r: v + offset for r, v in raw_contributions.items()}
        total_positive = sum(positive_contributions.values())
        
        if total_positive > 0:
            relative_contributions = {r: v / total_positive for r, v in positive_contributions.items()}
        else:
            relative_contributions = {r: 1.0 / len(raw_contributions) for r in raw_contributions}
        
        # 更新attribution
        for role in self.DYNAMIC_ROLES:
            if role not in attribution:
                attribution[role] = {
                    "contribution_raw": 0.0,
                    "contribution_relative": 0.0,
                    "contribution_pct": 0.0,
                    "highlight": "未参与",
                }
                continue
            
            raw = attribution[role]["contribution_raw"]
            relative = relative_contributions.get(role, 0)
            baseline_ret = attribution[role].get("baseline_return", 0)
            
            # 生成highlight
            if raw > 0:
                highlight = f"比默认策略好 +{raw:.2%}，权重 {relative:.1%}"
            elif raw < 0:
                highlight = f"比默认策略差 {raw:.2%}，权重 {relative:.1%}"
            else:
                highlight = "与默认策略持平"
            
            attribution[role]["contribution_relative"] = relative
            attribution[role]["contribution_pct"] = relative
            attribution[role]["highlight"] = highlight
        
        # 添加基准信息
        attribution["_benchmark"] = {
            "name": "沪深300",
            "return": benchmark_return,
            "excess": full_return - benchmark_return,
        }
        
        # 添加相对贡献汇总
        attribution["_relative_summary"] = {
            role: attribution[role]["contribution_pct"] 
            for role in self.DYNAMIC_ROLES 
            if role in attribution
        }
        
        print("  [相对贡献归因]")
        for role, pct in sorted(attribution["_relative_summary"].items(), key=lambda x: x[1], reverse=True):
            print(f"    {role}: {pct:.1%}")
        
        return attribution
        
        full_return = full_results["total_return"]
        full_monthly = full_results["monthly_returns"]
        
        # 获取基准收益（沪深300）
        # 需要将日度指数收益聚合为月度
        index_monthly = index_returns.resample('M').apply(lambda x: (1 + x).prod() - 1)
        index_monthly.index = index_monthly.index.to_period('M')
        
        benchmark_monthly = []
        for m in full_monthly.index:
            if m in index_monthly.index:
                benchmark_monthly.append(index_monthly[m])
            else:
                benchmark_monthly.append(0)
        benchmark_series = pd.Series(benchmark_monthly, index=full_monthly.index)
        benchmark_return = float((1 + benchmark_series).prod() - 1)
        
        attribution = {}
        
        # 对每个角色做Leave-One-Out
        for role in self.DYNAMIC_ROLES:
            if role not in role_selections:
                attribution[role] = {
                    "contribution": 0.0,
                    "contribution_pct": 0.0,
                    "excess_vs_benchmark": 0.0,
                    "highlight": "未参与",
                }
                continue
            
            # 去掉该角色后的行为
            if role == "行业分析师":
                # 去掉行业选择：使用所有行业
                loo_results = self._run_pipeline_without_industry_selection(
                    df_daily, dates, role_selections, index_returns, params
                )
            elif role == "个股分析师":
                # 去掉选股：等权持有所有股票
                loo_results = self._run_pipeline_with_equal_weight(
                    df_daily, dates, index_returns, params
                )
            elif role == "策略分析师":
                # 去掉择时：永远满仓
                loo_results = self._run_pipeline_without_timing(
                    df_daily, dates, role_selections, index_returns, params
                )
            elif role == "量化分析师":
                # 去掉优化：使用基本选股
                loo_results = self._run_pipeline_without_optimization(
                    df_daily, dates, role_selections, index_returns, params
                )
            elif role == "风控分析师":
                # 去掉风控：无约束
                loo_results = self._run_pipeline_without_risk_control(
                    df_daily, dates, role_selections, index_returns, params
                )
            else:
                loo_results = full_results
            
            loo_return = loo_results["total_return"]
            contribution = full_return - loo_return
            
            attribution[role] = {
                "contribution_raw": contribution,  # 原始贡献（可正可负）
            }
            
            print(f"  [{role}] 边际贡献: {contribution:+.2%}")
        
        # ========== 方案B：相对贡献归因 ==========
        # 计算各角色的相对贡献比例（都是正数，总和100%）
        raw_contributions = {r: attribution[r]["contribution_raw"] for r in self.DYNAMIC_ROLES if r in attribution}
        
        # 根据超额收益的正负，决定权重计算方式
        excess_return = full_return - benchmark_return
        
        if excess_return > 0:
            # 超额收益为正：只考虑正贡献的角色
            positive_contributions = {r: v for r, v in raw_contributions.items() if v > 0}
            total_positive = sum(positive_contributions.values())
            
            if total_positive > 0:
                relative_contributions = {r: v / total_positive for r, v in positive_contributions.items()}
            else:
                relative_contributions = {r: 1.0 / len(raw_contributions) for r in raw_contributions}
        else:
            # 超额收益为负：只考虑"保护"的角色（负贡献表示去掉后收益更差，说明在帮忙）
            # 负贡献 = 去掉后收益增加 = 该角色在帮忙
            helpers = {r: abs(v) for r, v in raw_contributions.items() if v < 0}
            total_helpers = sum(helpers.values())
            
            if total_helpers > 0:
                relative_contributions = {r: v / total_helpers for r, v in helpers.items()}
            else:
                relative_contributions = {r: 1.0 / len(raw_contributions) for r in raw_contributions}
        
        # 更新attribution
        for role in self.DYNAMIC_ROLES:
            if role not in attribution:
                attribution[role] = {
                    "contribution_raw": 0.0,
                    "contribution_relative": 0.0,
                    "contribution_pct": 0.0,
                    "highlight": "未参与",
                }
                continue
            
            raw = attribution[role]["contribution_raw"]
            relative = relative_contributions.get(role, 0)
            
            # 生成highlight
            if raw > 0 and relative > 0:
                highlight = f"贡献 +{raw:.2%}（正向贡献），权重 {relative:.1%}"
            elif raw < 0:
                highlight = f"贡献 {raw:.2%}（拖累收益），权重 {relative:.1%}"
            elif raw > 0 and relative == 0:
                highlight = f"贡献 +{raw:.2%}（正向但未分配权重）"
            else:
                highlight = "无贡献"
            
            attribution[role]["contribution_relative"] = relative
            attribution[role]["contribution_pct"] = relative
            attribution[role]["highlight"] = highlight
        
        # 添加基准信息
        attribution["_benchmark"] = {
            "name": "沪深300",
            "return": benchmark_return,
            "excess": full_return - benchmark_return,
        }
        
        # 添加相对贡献汇总
        attribution["_relative_summary"] = {
            "description": "各角色相对贡献比例（用于奖金分配）",
            "contributions": relative_contributions,
            "total": sum(relative_contributions.values()),
        }
        
        print(f"\n  [相对贡献归因]")
        for role, pct in sorted(relative_contributions.items(), key=lambda x: x[1], reverse=True):
            print(f"    {role}: {pct:.1%}")
        
        return attribution
    
    # ========== Shapley 归因（Sprint 1） ==========
    
    def _compute_shapley_attribution(self, df_daily, dates, role_selections, index_returns, params,
                                     full_results=None):
        """
        Shapley 归因：遍历 2^n 个角色子集，对每个子集做真实 Pipeline 回测得到 v(S)，
        再按 Shapley 公式计算每个角色的边际贡献（v7.0 大纲 §3.1/§3.3）。

        正确性：
          - v(S) 来自"对子集 S 的真实回测"（调用 _run_pipeline_backtest），而非均值近似
          - 公理化"有效性"：Σφᵢ == v(N)（贡献之和等于全组合收益），误差 < 1e-6
          - 取消"强制正贡献"，贡献为负则显示为负（考核意义所在）

        返回:
          dict: {角色: {"shapley_value", "contribution_pct", "highlight"}, "_shapley_summary", ...}
        """
        from itertools import combinations
        import math

        roles = list(self.DYNAMIC_ROLES)
        n = len(roles)

        print("\n[Backtest] Shapley归因（遍历 2^%d=%d 个子集真实回测）..." % (n, 2 ** n))

        # ---- 1. 计算所有子集的 v(S) ----
        # v_cache[mask] = 该角色子集的 Pipeline 真实回测收益
        v_cache = {0: 0.0}  # 空集 v(∅) = 0
        total_masks = (1 << n) - 1
        done_masks = 0

        for mask in range(1, 1 << n):
            subset = {roles[i] for i in range(n) if (mask >> i) & 1}
            try:
                res = self._run_pipeline_backtest(
                    df_daily, dates, role_selections, index_returns, params,
                    active_roles=subset,
                )
                v_cache[mask] = res["total_return"]
            except Exception as e:
                print(f"  [警告] 子集 {subset} 回测失败: {e}，按 0 处理")
                v_cache[mask] = 0.0
            done_masks += 1
            pct = 52 + (done_masks / total_masks) * 36
            subset_sorted = sorted(subset)
            self.progress.shapley_subset(
                done_masks,
                total_masks,
                subset_sorted,
                float(v_cache[mask]),
                pct,
                subset_label=coalition_label(subset_sorted),
                subset_full="、".join(subset_sorted) if subset_sorted else "空联盟",
            )

        # ---- 2. 计算每个角色的 Shapley 值 ----
        shapley_values = {}
        for i in range(n):
            phi = 0.0
            for mask in range(1 << n):
                if (mask >> i) & 1:
                    continue
                mask_with_i = mask | (1 << i)
                s_size = bin(mask).count("1")
                weight = (math.factorial(s_size) * math.factorial(n - s_size - 1)) / math.factorial(n)
                phi += weight * (v_cache[mask_with_i] - v_cache[mask])
            shapley_values[roles[i]] = phi

        # ---- 3. 公理化校验：Σφᵢ == v(N) ----
        total_shapley = sum(shapley_values.values())
        full_mask = (1 << n) - 1
        v_full = v_cache[full_mask]
        check_pass = abs(total_shapley - v_full) < 1e-6

        print(f"  公理化校验: Σφᵢ={total_shapley:.6f}, v(N)={v_full:.6f}, "
              f"{'✅ 通过' if check_pass else '❌ 不通过'}")

        # ---- 4. 组装 attribution 结构 ----
        attribution = {}
        for role in roles:
            phi = shapley_values[role]
            pct = phi / total_shapley if abs(total_shapley) > 1e-12 else 0.0
            if phi > 0:
                highlight = f"Shapley贡献 {phi:+.2%}，权重 {pct:.1%}"
            elif phi < 0:
                highlight = f"Shapley贡献 {phi:.2%}（负贡献），权重 {pct:.1%}"
            else:
                highlight = "零边际贡献"
            attribution[role] = {
                "shapley_value": phi,
                "contribution_raw": phi,
                "contribution_pct": pct,
                "contribution_relative": pct,
                "highlight": highlight,
            }

        attribution["_benchmark"] = {
            "name": "沪深300",
            "return": index_returns.get("benchmark_return", 0),
        }
        attribution["_shapley_summary"] = {
            "description": "各角色Shapley贡献（带符号，和为全组合收益）",
            "contributions": {r: attribution[r]["contribution_pct"] for r in roles},
            "sum": total_shapley,
            "full_return": v_full,
            "axiom_check": check_pass,
        }

        print("\n  [Shapley归因]")
        for role, pct in sorted(attribution["_shapley_summary"]["contributions"].items(),
                                key=lambda x: x[1], reverse=True):
            print(f"    {role}: {pct:+.1%}  (φ={shapley_values[role]:+.2%})")

        self.progress.partial_shapley({r: float(v) for r, v in shapley_values.items()})
        self.progress.log(
            f"Shapley 公理校验：{'通过' if check_pass else '未通过'} · Σφ={total_shapley:.4f}"
        )

        return attribution
    
    # ========== 相对基准归因的基准函数 ==========
    
    def _run_baseline_equal_weight_industry(self, df_daily, dates, role_selections, index_returns, params):
        """基准1：等权所有行业（不经过行业筛选）"""
        from industry_analyst import get_industry_mapping
        
        industry_mapping = get_industry_mapping(self.loader)
        timing = TimingModule(target_vol=0.15, lookback=20)
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        # 使用所有股票
        all_stocks = sorted(df_daily["symbol"].unique())
        
        monthly_returns = []
        prev_month_ret = 0.0
        months = sorted(df_daily["date"].dt.to_period("M").unique())
        
        for ym in months:
            ym_str = str(ym)
            month_start = ym.start_time
            if ym == months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            # 等权所有股票
            n_stocks = len(all_stocks)
            weights = {s: 1.0 / n_stocks for s in all_stocks}
            
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            weights = apply_timing(weights, position_ratio)
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            month_data = df_daily[
                (df_daily["symbol"].isin(all_stocks)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_baseline_random_selection(self, df_daily, dates, role_selections, index_returns, params):
        """基准2：随机选股（不使用因子）"""
        import random
        
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        timing = TimingModule(target_vol=0.15, lookback=20)
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        industry_mapping = get_industry_mapping(self.loader)
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        prev_month_ret = 0.0
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            month_start = ym.start_time
            
            # 获取该月可用的股票（从历史数据中）
            hist_data = df_daily[df_daily["date"] < month_start]
            available_stocks = sorted(hist_data["symbol"].unique())
            
            # 随机选择与原策略相同数量的股票
            n_stocks = min(self.TOP_N, len(available_stocks))
            stocks_in = random.sample(available_stocks, n_stocks)
            
            n_stocks = len(stocks_in)
            weights = {s: 1.0 / n_stocks for s in stocks_in}
            
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            weights = apply_timing(weights, position_ratio)
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_baseline_quant_candidates(self, df_daily, dates, role_selections, index_returns, params):
        """基准3：直接用量化候选池（不做深度精选）"""
        # 使用量化分析师的选择结果，而不是个股分析师的
        quant_role = "量化分析师"
        if quant_role not in role_selections:
            # 如果没有量化分析师，使用个股分析师的（但这是错误的）
            quant_role = next(iter(role_selections), None)
        
        selections = role_selections[quant_role]
        timing = TimingModule(target_vol=0.15, lookback=20)
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        industry_mapping = get_industry_mapping(self.loader)
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        prev_month_ret = 0.0
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            month_start = ym.start_time
            
            # 直接用原策略的选股结果（不做深度精选）
            stocks_in = [str(s) for s in selections[ym_str]]
            
            n_stocks = len(stocks_in)
            weights = {s: 1.0 / n_stocks for s in stocks_in}
            
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            weights = apply_timing(weights, position_ratio)
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_baseline_always_invested(self, df_daily, dates, role_selections, index_returns, params):
        """基准4：永远满仓（不使用择时）"""
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        industry_mapping = get_industry_mapping(self.loader)
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        prev_month_ret = 0.0
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            stocks_in = [str(s) for s in selections[ym_str]]
            
            # 永远满仓（不使用择时）
            n_stocks = len(stocks_in)
            weights = {s: 1.0 / n_stocks for s in stocks_in}
            
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            month_start = ym.start_time
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_baseline_no_risk_control(self, df_daily, dates, role_selections, index_returns, params):
        """基准5：无风控约束"""
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        timing = TimingModule(target_vol=0.15, lookback=20)
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            stocks_in = [str(s) for s in selections[ym_str]]
            
            # 应用择时但不应用风控
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            n_stocks = len(stocks_in)
            weights = {s: position_ratio / n_stocks for s in stocks_in}
            
            month_start = ym.start_time
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_pipeline_with_equal_weight(self, df_daily, dates, index_returns, params):
        """等权持有所有股票（去掉个股分析师）"""
        stocks = df_daily["symbol"].unique()
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        months = sorted(df_daily["date"].dt.to_period("M").unique())
        
        for ym in months:
            month_data = df_daily[df_daily["date"].dt.to_period("M") == ym]
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            # 等权所有股票
            daily_rets = month_data.groupby("date")["return"].mean()
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_pipeline_without_timing(self, df_daily, dates, role_selections, index_returns, params):
        """去掉择时：永远满仓"""
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            stocks_in = selections[ym_str]
            
            # 确保stocks_in是字符串列表
            stocks_in = [str(s) for s in stocks_in]
            
            month_start = ym.start_time
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            # 等权（满仓）
            daily_rets = month_data.groupby("date")["return"].mean()
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_pipeline_without_risk_control(self, df_daily, dates, role_selections, index_returns, params):
        """去掉风控：无约束"""
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        timing = TimingModule(target_vol=0.15, lookback=20)
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            stocks_in = selections[ym_str]
            
            # 确保stocks_in是字符串列表
            stocks_in = [str(s) for s in stocks_in]
            
            # 应用择时但不应用风控
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            n_stocks = len(stocks_in)
            weights = {s: position_ratio / n_stocks for s in stocks_in}
            
            month_start = ym.start_time
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            # 按权重加权
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(
                    weights.get(s, 0) * r 
                    for s, r in zip(day_data["symbol"], day_data["return"])
                    if pd.notna(r)
                )
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_pipeline_without_industry_selection(self, df_daily, dates, role_selections, index_returns, params):
        """去掉行业选择：等权持有所有股票"""
        from industry_analyst import get_industry_mapping
        
        industry_mapping = get_industry_mapping(self.loader)
        timing = TimingModule(target_vol=0.15, lookback=20)
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        # 使用所有股票（不经过行业筛选）
        all_stocks = sorted(df_daily["symbol"].unique())
        
        monthly_returns = []
        prev_month_ret = 0.0
        months = sorted(df_daily["date"].dt.to_period("M").unique())
        
        for ym in months:
            ym_str = str(ym)
            month_start = ym.start_time
            if ym == months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            # 等权所有股票（不经过行业筛选）
            n_stocks = len(all_stocks)
            weights = {s: 1.0 / n_stocks for s in all_stocks}
            
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            weights = apply_timing(weights, position_ratio)
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            month_data = df_daily[
                (df_daily["symbol"].isin(all_stocks)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(weights.get(s, 0) * r for s, r in zip(day_data["symbol"], day_data["return"]) if pd.notna(r))
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _run_pipeline_without_optimization(self, df_daily, dates, role_selections, index_returns, params):
        """去掉量化优化：使用基本选股（不使用多策略平均）"""
        from industry_analyst import IndustryAnalyst, get_industry_mapping
        
        industry_mapping = get_industry_mapping(self.loader)
        industry_analyst = IndustryAnalyst(top_n=3, lookback=20)
        
        stock_role = "个股分析师"
        if stock_role not in role_selections:
            stock_role = next(iter(role_selections), None)
        
        selections = role_selections[stock_role]
        timing = TimingModule(target_vol=0.15, lookback=20)
        risk_control = RiskControlModule({'max_single': 0.05, 'max_industry': 0.25, 'stop_loss_monthly': -0.05})
        
        user_industry = params.get("industry")
        
        df_daily = df_daily.copy()
        df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()
        df_daily["symbol"] = df_daily["symbol"].astype(str)
        
        monthly_returns = []
        prev_month_ret = 0.0
        sorted_months = sorted(selections.keys())
        
        for ym_str in sorted_months:
            ym = pd.Period(ym_str)
            month_start = ym.start_time
            
            # 行业分析师选择行业
            if user_industry:
                selected_industries = [user_industry]
            else:
                selected_industries = industry_analyst.select_industries(df_daily, industry_mapping, self.loader.df_index, month_start)
            
            stocks_in_industry = [s for s, ind in industry_mapping.items() if ind in selected_industries]
            
            # 使用基本选股结果（不优化）
            stocks_in = [s for s in selections[ym_str] if s in stocks_in_industry]
            if not stocks_in:
                stocks_in = stocks_in_industry[:self.TOP_N]
            
            # 确保stocks_in是字符串列表
            stocks_in = [str(s) for s in stocks_in]
            
            # 不使用量化优化，直接用选股结果
            
            n_stocks = len(stocks_in)
            weights = {s: 1.0 / n_stocks for s in stocks_in}
            
            position_ratio = timing.calculate_monthly_position(index_returns, ym_str)
            weights = apply_timing(weights, position_ratio)
            weights = risk_control.apply_all(weights, industry_mapping, monthly_return=prev_month_ret)
            
            if ym_str == sorted_months[-1]:
                month_end = pd.Timestamp(dates[-1])
            else:
                month_end = (ym + 1).start_time
            
            month_data = df_daily[
                (df_daily["symbol"].isin(stocks_in)) &
                (df_daily["date"] >= month_start) &
                (df_daily["date"] < month_end)
            ]
            
            if len(month_data) == 0:
                monthly_returns.append({"month": ym, "return": 0.0})
                continue
            
            daily_rets = []
            for dt in sorted(month_data["date"].unique()):
                day_data = month_data[month_data["date"] == dt]
                day_ret = sum(weights.get(s, 0) * r for s, r in zip(day_data["symbol"], day_data["return"]) if pd.notna(r))
                daily_rets.append(day_ret)
            
            daily_rets = pd.Series(daily_rets)
            month_ret = (1 + daily_rets).prod() - 1
            monthly_returns.append({"month": ym, "return": month_ret})
            prev_month_ret = month_ret
        
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        return {
            "monthly_returns": ret_df["return"],
            "total_return": (1 + ret_df["return"]).prod() - 1,
        }
    
    def _compute_single_performance(self, monthly_returns, index_returns):
        """计算单个组合的绩效指标"""
        print("[Backtest] 计算绩效...")
        
        if len(monthly_returns) < 2:
            return {}
        
        cum_ret = (1 + monthly_returns).prod() - 1
        n_months = len(monthly_returns)
        ann_ret = (1 + cum_ret) ** (12 / n_months) - 1 if n_months > 0 else 0
        ann_vol = monthly_returns.std() * np.sqrt(12)
        sharpe = (ann_ret - self.RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0
        max_dd = (1 + monthly_returns).cumprod().div((1 + monthly_returns).cumprod().cummax()).min() - 1
        win_rate = (monthly_returns > 0).mean()
        
        return {
            "组合": {
                "cumulative_return": cum_ret,
                "annual_return": ann_ret,
                "annual_volatility": ann_vol,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_dd,
                "win_rate": win_rate,
            }
        }
    
    def _compute_attribution(self, role_returns, index_returns, roles):
        """归因计算"""
        print("[Backtest] 归因计算...")
        
        attribution = {}
        
        # IC计算（简化版）
        role_ic = {}
        for role in roles:
            role_ic[role] = 0.5  # 占位，实际IC需要因子数据
        
        # 超额收益
        role_excess = {}
        for role in roles:
            if role not in role_returns:
                role_excess[role] = 0
                continue
            port_ret = role_returns[role]
            aligned_idx = []
            for m in port_ret.index:
                if m in index_returns.index:
                    aligned_idx.append(index_returns[m])
                else:
                    aligned_idx.append(0)
            excess = port_ret.values - np.array(aligned_idx)
            role_excess[role] = np.mean(excess)
        
        # 增量贡献
        role_incremental = {}
        all_combined = None
        for role in roles:
            if role not in role_returns:
                continue
            ret = role_returns[role]
            if all_combined is None:
                all_combined = ret.copy()
            else:
                common = all_combined.index.intersection(ret.index)
                all_combined = all_combined.loc[common] + ret.loc[common]
        
        if all_combined is not None:
            total_return = (1 + all_combined).prod() - 1
            for leave_role in roles:
                if leave_role not in role_returns:
                    role_incremental[leave_role] = 0
                    continue
                reduced = None
                for role in roles:
                    if role == leave_role or role not in role_returns:
                        continue
                    ret = role_returns[role]
                    if reduced is None:
                        reduced = ret.copy()
                    else:
                        common = reduced.index.intersection(ret.index)
                        reduced = reduced.loc[common] + ret.loc[common]
                
                if reduced is not None:
                    reduced_return = (1 + reduced).prod() - 1
                    role_incremental[leave_role] = total_return - reduced_return
                else:
                    role_incremental[leave_role] = total_return
        
        # 综合评分
        def normalize(d):
            vals = list(d.values())
            min_v, max_v = min(vals), max(vals)
            if max_v == min_v:
                return {k: 0.5 for k in d}
            return {k: (v - min_v) / (max_v - min_v) for k, v in d.items()}
        
        ic_norm = normalize(role_ic)
        excess_norm = normalize(role_excess)
        incr_norm = normalize(role_incremental)
        
        for role in roles:
            score = 0.3 * ic_norm.get(role, 0) + 0.4 * excess_norm.get(role, 0) + 0.3 * incr_norm.get(role, 0)
            attribution[role] = {
                "ic": role_ic.get(role, 0),
                "excess_return": role_excess.get(role, 0),
                "incremental": role_incremental.get(role, 0),
                "composite_score": score
            }
        
        return attribution
    
    def _compute_performance(self, role_returns, index_returns, attribution):
        """计算绩效指标"""
        print("[Backtest] 计算绩效...")
        
        performance = {}
        for role, ret in role_returns.items():
            if len(ret) < 2:
                continue
            
            cum_ret = (1 + ret).prod() - 1
            n_months = len(ret)
            ann_ret = (1 + cum_ret) ** (12 / n_months) - 1 if n_months > 0 else 0
            ann_vol = ret.std() * np.sqrt(12)
            sharpe = (ann_ret - self.RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0
            max_dd = (1 + ret).cumprod().div((1 + ret).cumprod().cummax()).min() - 1
            win_rate = (ret > 0).mean()
            
            performance[role] = {
                "cumulative_return": cum_ret,
                "annual_return": ann_ret,
                "annual_volatility": ann_vol,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_dd,
                "win_rate": win_rate,
            }
        
        return performance
    
    def _generate_time_series(self, role_returns, index_returns, granularity):
        """生成时间序列"""
        print("[Backtest] 生成时间序列...")
        
        time_series = []
        
        # 将日度指数收益聚合为月度
        index_monthly = index_returns.resample('M').apply(lambda x: (1 + x).prod() - 1)
        index_monthly.index = index_monthly.index.to_period('M')
        
        # 合并所有角色收益
        all_months = set()
        for ret in role_returns.values():
            all_months.update(ret.index)
        
        for month in sorted(all_months):
            # 计算所有角色的平均收益（而不是求和）
            role_rets = [role_returns[r].get(month, 0) for r in role_returns]
            total_ret = float(np.mean(role_rets)) if role_rets else 0
            bench_ret = float(index_monthly.get(month, 0)) if month in index_monthly.index else 0
            
            # 确定period格式
            if granularity == "yearly":
                period = str(month.year)
            elif granularity == "quarterly":
                quarter = (month.month - 1) // 3 + 1
                period = f"{month.year}-Q{quarter}"
            else:
                period = str(month)
            
            time_series.append({
                "period": period,
                "return": total_ret,
                "benchmark": bench_ret,
                "excess": total_ret - bench_ret
            })
        
        # 如果是季度/年度粒度，需要聚合
        if granularity in ("quarterly", "yearly"):
            df_ts = pd.DataFrame(time_series)
            df_ts["return_1plus"] = 1 + df_ts["return"]
            df_ts["bench_1plus"] = 1 + df_ts["benchmark"]
            
            agg = df_ts.groupby("period").agg({
                "return_1plus": "prod",
                "bench_1plus": "prod"
            }).reset_index()
            
            agg["return"] = agg["return_1plus"] - 1
            agg["benchmark"] = agg["bench_1plus"] - 1
            agg["excess"] = agg["return"] - agg["benchmark"]
            
            time_series = agg[["period", "return", "benchmark", "excess"]].to_dict("records")
        
        return time_series
    
    def _assemble_results(self, performance, attribution, time_series, params):
        """组装v4响应格式（适配Pipeline + Leave-One-Out归因）"""
        
        # 角色权重（Sprint 1：双池方案 - 新池40%内部测算）
        # 方案A：负贡献角色仍分配（用 |φ|），HR权重作调节系数，单角色上限50%
        # 计算步骤：
        #   1. 贡献份额_i = |Shapleyφ_i| / Σ|φ_j|   （绝对值占比，全部为正，负贡献角色也有份额）
        #   2. 加权份额_i = 贡献份额_i × HR权重_i      （HR权重=调节系数，默认1.0）
        #   3. 新池权重_i = 加权份额_i / Σ加权份额_j   （归一化）
        #   4. 单角色上限 50%（防止HR过度倾斜某角色）
        # 注意：只负责"新池40%"内部如何分，旧池60%的既定分配不在本系统计算范围内
        role_weights = params.get("role_weights") or {}
        default_weight = 1.0 / len(performance) if performance else 0.2
        MAX_ROLE_WEIGHT = 0.5  # 单角色新池权重上限
        
        # Step1: 绝对值贡献份额
        phi_abs = {}
        total_phi_abs = 0.0
        for role in self.DYNAMIC_ROLES:
            attr = attribution.get(role, {})
            phi = attr.get("contribution_raw", 0)  # Shapley φ（带符号）
            abs_val = abs(phi)
            phi_abs[role] = abs_val
            total_phi_abs += abs_val
        
        # Step2: 乘HR调节系数（默认1.0）
        weighted = {}
        for role in self.DYNAMIC_ROLES:
            share = phi_abs[role] / total_phi_abs if total_phi_abs > 1e-12 else 0.0
            w = role_weights.get(role, 1.0)  # HR调节系数
            weighted[role] = share * w
        
        # Step3: 归一化
        total_weighted = sum(weighted.values())
        final_weight = {}
        for role in self.DYNAMIC_ROLES:
            final_weight[role] = weighted[role] / total_weighted if total_weighted > 1e-12 else 0.0
        
        # Step4: 单角色上限 50% + 重新归一化
        for role in self.DYNAMIC_ROLES:
            if final_weight[role] > MAX_ROLE_WEIGHT:
                final_weight[role] = MAX_ROLE_WEIGHT
        capped_total = sum(final_weight.values())
        if capped_total > 1e-12:
            final_weight = {r: w / capped_total for r, w in final_weight.items()}
        
        # role_breakdown
        role_breakdown = []
        
        # 从attribution中提取基准信息和贡献汇总
        benchmark_info = attribution.pop("_benchmark", {})
        relative_summary = attribution.pop("_relative_summary", {})
        shapley_summary = attribution.pop("_shapley_summary", {})
        
        for role in self.DYNAMIC_ROLES:
            attr = attribution.get(role, {})
            perf = performance.get("组合", {})
            # 新池内权重（方案A：绝对值份额 × HR权重，单角色上限50%）
            weight = final_weight.get(role, 0.0)
            
            # 使用相对贡献
            contribution_raw = attr.get("contribution_raw", 0)
            contribution_relative = attr.get("contribution_relative", 0)
            highlight = attr.get("highlight", "未参与")
            
            role_breakdown.append({
                "role": role,
                "is_target": (params["target_role"] == role),   # 是否聚焦角色
                "weight": weight,
                "hr_weight": role_weights.get(role, None),   # 原始HR调节系数
                "shapley_raw": contribution_raw,
                "contribution_raw": contribution_raw,
                "contribution": contribution_raw,  # 规范键名：绝对贡献（与contribution_raw一致）
                "contribution_relative": contribution_relative,
                "contribution_pct": contribution_relative,  # 用于显示的百分比
                "highlight": highlight,
                "performance": perf
            })
        
        # overview
        # perf 是否含有效绩效指标（短区间如 ≤1 个调仓月时 performance["组合"] 可能缺失）
        has_perf = bool(perf)
        cum_return = perf.get("cumulative_return", 0) if has_perf else 0
        benchmark_return = benchmark_info.get("return", 0)
        excess_return = benchmark_info.get("excess", 0)
        
        # 归因贡献汇总：优先用 Shapley 归因的贡献（Sprint 1）
        if shapley_summary:
            contributions = shapley_summary.get("contributions", {})
            attribution_type = "shapley"
            attribution_desc = "各角色Shapley贡献（带符号，和为全组合收益）"
        else:
            contributions = relative_summary.get("contributions", {})
            attribution_type = "relative_benchmark"
            attribution_desc = "相对基准归因"

        overview = {
            "total_return": cum_return,
            "benchmark_return": benchmark_return,
            "excess_return": excess_return,
            "sharpe_ratio": perf.get("sharpe_ratio", 0) if has_perf else 0,
            "max_drawdown": perf.get("max_drawdown", 0) if has_perf else 0,
            "relative_contributions": contributions,
            "attribution_type": attribution_type,
            "attribution_description": attribution_desc,
        }
        
        # query_summary
        parts = []
        if params["start_date"] and params["end_date"]:
            parts.append(f"{params['start_date']}~{params['end_date']}")
        if params["target_role"]:
            parts.append(params["target_role"])
        else:
            parts.append("所有角色")
        if params["industry"]:
            parts.append(params["industry"])
        else:
            parts.append("全行业")
        parts.append(f"{params['rebalance_freq']}调仓")
        query_summary = "，".join(parts)

        # ========== 结论层（Sprint 2：供 Agent 直接生成 HR 报告） ==========
        # overview 数值 + 人话描述
        overview["total_return_desc"] = f"组合累计收益{cum_return*100:.2f}%"
        overview["benchmark_return_desc"] = f"基准({benchmark_info.get('name','沪深300')})收益{benchmark_return*100:.2f}%"
        if excess_return > 0:
            overview["excess_return_desc"] = f"超额收益{excess_return*100:.2f}%，跑赢基准"
        else:
            overview["excess_return_desc"] = f"超额收益{excess_return*100:.2f}%，跑输基准"
        if has_perf:
            overview["max_drawdown_desc"] = f"最大回撤{overview['max_drawdown']*100:.2f}%"
            sharpe_val = overview["sharpe_ratio"]
            if sharpe_val > 1:
                overview["sharpe_ratio_desc"] = f"夏普比率{sharpe_val:.2f}，风险调整后收益良好"
            elif sharpe_val > 0:
                overview["sharpe_ratio_desc"] = f"夏普比率{sharpe_val:.2f}，风险调整后收益一般"
            else:
                overview["sharpe_ratio_desc"] = f"夏普比率{sharpe_val:.2f}，风险调整后收益为负"
        else:
            # 短区间（≤1 个调仓月）无法计算夏普/回撤，给出降级人话描述
            overview["max_drawdown_desc"] = "回测区间过短，暂无法计算最大回撤"
            overview["sharpe_ratio_desc"] = "回测区间过短，暂无法计算夏普比率"

        # 贡献排名（按 Shapley 贡献 raw 从高到低）
        ranking_sorted = sorted(
            [(rb["role"], rb["contribution_raw"]) for rb in role_breakdown],
            key=lambda x: x[1], reverse=True
        )
        role_ranking = [r[0] for r in ranking_sorted]
        role_ranking_desc = " > ".join(role_ranking)
        ranking_map = {r[0]: i + 1 for i, r in enumerate(ranking_sorted)}

        # 亮点/主要发现（正负贡献）
        highlights = []
        pos_roles = [r for r in ranking_sorted if r[1] > 0]
        neg_roles = [r for r in ranking_sorted if r[1] < 0]
        top_pos = None
        worst_neg = None
        # 聚焦 target_role（方案 B）：若指定了重点角色，先输出该角色的表现
        target_role = params["target_role"]
        if target_role and target_role in ranking_map:
            t_rank = ranking_map[target_role]
            t_contri = dict(ranking_sorted)[target_role]
            if t_contri > 0:
                highlights.append({
                    "type": "target_positive",
                    "text": f"聚焦角色「{target_role}」贡献{t_contri*100:+.2f}%，排名第{t_rank}，为正贡献",
                })
            elif t_contri < 0:
                highlights.append({
                    "type": "target_negative",
                    "text": f"聚焦角色「{target_role}」贡献{t_contri*100:+.2f}%，排名第{t_rank}，为负贡献，建议重点复盘",
                })
            else:
                highlights.append({
                    "type": "target_neutral",
                    "text": f"聚焦角色「{target_role}」贡献≈0，排名第{t_rank}，影响中性",
                })
        if pos_roles:
            top_pos = pos_roles[0]
            highlights.append({
                "type": "positive",
                "text": f"{top_pos[0]}贡献最大（{top_pos[1]*100:+.2f}%），是组合收益的主要来源",
            })
        if neg_roles:
            worst_neg = neg_roles[-1]
            highlights.append({
                "type": "negative",
                "text": f"{worst_neg[0]}贡献为负（{worst_neg[1]*100:+.2f}%），拖累组合表现，建议重点复盘",
            })
        if excess_return > 0:
            highlights.append({
                "type": "info",
                "text": f"组合跑赢基准{excess_return*100:.2f}%，主动管理整体有效",
            })
        else:
            highlights.append({
                "type": "warning",
                "text": f"组合跑输基准{abs(excess_return)*100:.2f}%，主动管理未跑赢",
            })

        # 分配建议（新池40%）
        allocation_map = {rb["role"]: rb["weight"] for rb in role_breakdown}
        if top_pos:
            top_role = top_pos[0]
        else:
            top_role = role_ranking[0] if role_ranking else "无"
        recommendation = {
            "summary": overview["excess_return_desc"] + "，" + (
                f"建议新池40%按贡献分配，{top_role}分配最高（{allocation_map.get(top_role,0)*100:.1f}%）"
            ),
            "focus": (
                f"重点复盘{worst_neg[0]}（贡献{worst_neg[1]*100:+.2f}%），"
                f"其负贡献主要拖累组合" if neg_roles else "各角色均正贡献，可维持现状"
            ),
            "role_weights_impact": (
                "若HR调整某角色权重（新池内调节系数），其分配占比将相应变化"
            ),
        }

        return {
            "status": "success",
            "query_summary": query_summary,
            "results": {
                "overview": overview,
                "role_breakdown": role_breakdown,
                "role_ranking": role_ranking,
                "role_ranking_desc": role_ranking_desc,
                "target_role": params["target_role"],   # 聚焦角色（null=所有）
                "highlights": highlights,
                "recommendation": recommendation,
                "filter_detail": {
                    "industry": params["industry"],
                    "benchmark": params["benchmark"],
                    "rebalance_freq": params["rebalance_freq"],
                },
                "time_series": time_series,
            }
        }


# ============================================================
# 自定义错误（Sprint 2：规范 error_code，Agent 可识别）
# ============================================================
class BacktestError(Exception):
    """带 error_code 的回测错误。error_code 遵循 v4 接口规范。"""
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code
        self.error_message = message


# ============================================================
# 主入口函数
# ============================================================
def run_query(query_json: dict, progress_callback=None) -> dict:
    """
    主入口：接收v4 JSON，执行回测，返回结果
    
    Args:
        query_json: v4格式的查询JSON
        progress_callback: 可选，接收进度事件 dict（供 SSE / 前端）
    
    Returns:
        v4格式的结果JSON
    """
    from progress_reporter import ProgressReporter

    request_id = query_json.get("request_id", f"q_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    progress = ProgressReporter(progress_callback)
    
    print("=" * 60)
    print(f"🚀 回测引擎 - 请求ID: {request_id}")
    print("=" * 60)
    
    try:
        # 1. 解析查询
        print("\n[1/5] 解析查询...")
        progress.stage(1, 7, "parse", "解析查询参数…", 5)
        params = QueryParser.parse(query_json)
        print(f"  参数: {json.dumps(params, ensure_ascii=False, default=str)}")
        progress.log(f"区间 {params.get('start_date')} ~ {params.get('end_date')} · "
                     f"{params.get('industry') or '全行业'}")
        
        # 2. 初始化
        print("\n[2/5] 初始化...")
        progress.stage(2, 7, "init", "加载行情与行业映射数据…", 8)
        loader = DataLoader()
        recorder = IntermediateRecorder(request_id)
        loader.load()
        progress.log(f"数据加载完成：{len(loader.df_daily):,} 条日线")
        
        # 3. 执行回测
        print("\n[3/5] 执行回测...")
        executor = BacktestExecutor(loader, recorder, progress=progress)
        results = executor.execute(params)
        
        # 4. 保存中间数据
        print("\n[4/5] 保存中间数据...")
        progress.stage(6, 7, "save", "保存中间数据与结果 JSON…", 92)
        recorder.save_all()
        
        # 5. 组装响应
        print("\n[5/5] 组装响应...")
        progress.stage(7, 7, "assemble", "组装最终响应…", 97)
        response = {
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            **results
        }
        
        # 保存结果JSON
        with open(f"{recorder.output_dir}/response.json", "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2, default=str)
        print(f"  [保存] response.json")
        
        print("\n" + "=" * 60)
        print("✅ 回测完成!")
        print("=" * 60)
        progress.stage(7, 7, "complete", "回测完成", 100)
        
        return response
        
    except BacktestError as e:
        # 规范错误码（INDUSTRY_NOT_FOUND / ROLE_NOT_FOUND / DATE_INVALID / NO_DATA 等）
        error_response = {
            "request_id": request_id,
            "status": "error",
            "error_code": e.error_code,
            "error_message": e.error_message,
        }
        print(f"\n❌ 错误[{e.error_code}]: {e.error_message}")
        return error_response
    except Exception as e:
        error_response = {
            "request_id": request_id,
            "status": "error",
            "error_code": "EXECUTION_ERROR",
            "error_message": str(e),
        }
        print(f"\n❌ 错误: {e}")
        return error_response


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    # 测试查询
    test_query = {
        "request_id": "test_001",
        "timestamp": "2026-08-19T10:00:00+08:00",
        "query": {
            "time_range": {
                "start_date": "2024-01-01",
                "end_date": "2024-12-31"
            },
            "target_role": None,
            "industry": None,
            "role_weights": None,
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
            "granularity": "monthly"
        }
    }
    
    result = run_query(test_query)
    print("\n=== 结果摘要 ===")
    print(json.dumps(result.get("results", {}).get("overview", {}), indent=2, ensure_ascii=False))
