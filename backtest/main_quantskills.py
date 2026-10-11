"""
完整回测系统 — 基于QuantSkills因子库
====================================
实现「业绩归因 → 组织角色 → 绩效考评」的闭环系统。
采用6:4双轨制：旧池60%沿用，新池40%动态分配。

核心流程:
  1. 加载HS300日线数据
  2. 计算所有角色的因子
  3. 每月调仓，根据因子综合得分选股
  4. 计算各角色组合收益
  5. 归因计算各角色贡献
  6. 生成分配方案

作者: 徐远 | 日期: 2026-08
"""
from __future__ import annotations
import os, sys, warnings, json
import numpy as np
import pandas as pd
from datetime import datetime
# from scipy.optimize import minimize  # unused

warnings.filterwarnings("ignore")
np.random.seed(42)

# ============================================================
# 配置（Sprint 0: 自适应本地/服务器，支持 FINBACK_BASE_DIR 环境变量覆盖）
# ============================================================
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getenv("FINBACK_BASE_DIR"):
    BASE_DIR = os.environ["FINBACK_BASE_DIR"]
elif os.path.isdir(os.path.join(_BACKTEST_DIR, "..", "data")):
    BASE_DIR = os.path.normpath(os.path.join(_BACKTEST_DIR, ".."))
else:
    BASE_DIR = "/home/ubuntu/FinTech"
DATA_DIR = f"{BASE_DIR}/data/processed"
REPORT_DIR = f"{BASE_DIR}/backtest/reports"
os.makedirs(REPORT_DIR, exist_ok=True)

# 回测参数
INITIAL_CAPITAL = 10_000_000       # 1000万
TOP_N = 10                         # 每角色选前10只股票
REBALANCE_FREQ = "M"               # 月度调仓
COMMISSION_RATE = 0.001            # 手续费0.1%
SLIPPAGE_RATE = 0.001              # 滑点0.1%
RISK_FREE_RATE = 0.02              # 无风险利率2%
OLD_POOL_RATIO = 0.6               # 旧池比例60%
NEW_POOL_RATIO = 0.4               # 新池比例40%

# 分配方案配置：旧池沿用固定比例
OLD_POOL_WEIGHTS = {
    "基金经理": 0.35,
    "投资经理": 0.20,
    "行业分析师": 0.15,
    "个股分析师": 0.12,
    "策略分析师": 0.06,
    "量化分析师": 0.05,
    "风控分析师": 0.04,
    "团队协作": 0.03,
}

# 新池动态分配的角色
DYNAMIC_ROLES = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]

# ============================================================
# 导入因子引擎
# ============================================================
sys.path.insert(0, f"{BASE_DIR}/backtest")
from quant_engine import compute_factor, ROLE_FACTORS, compute_financial_factors, zscore_financial_factors

# ============================================================
# 数据加载
# ============================================================
print("=" * 60)
print("📊 加载数据...")
print("=" * 60)

# 股票日K线数据（仓库内保留前复权主数据集）
daily_file = f"{DATA_DIR}/hs300_daily_qfq.csv.gz"
if not os.path.exists(daily_file):
    daily_file = f"{DATA_DIR}/hs300_daily_qfq.csv"
df_daily = pd.read_csv(daily_file, encoding="utf-8-sig")
df_daily["date"] = pd.to_datetime(df_daily["date"])
df_daily = df_daily.rename(columns={"stock_code": "symbol"})
df_daily = df_daily.sort_values(["symbol", "date"]).reset_index(drop=True)

# 补齐缺失列（如果数据中没有open/high/low列）
if "open" not in df_daily.columns and "close" in df_daily.columns:
    df_daily["open"] = df_daily["close"]
if "high" not in df_daily.columns:
    df_daily["high"] = df_daily["close"]
if "low" not in df_daily.columns:
    df_daily["low"] = df_daily["close"]

# 沪深300指数数据
df_index = pd.read_csv(f"{DATA_DIR}/hs300_index_daily.csv", encoding="utf-8-sig")
df_index["date"] = pd.to_datetime(df_index["date"])
df_index = df_index.sort_values("date").reset_index(drop=True)

# 行业映射数据
df_industry = pd.read_csv(f"{DATA_DIR}/stock_industry_mapping.csv", encoding="utf-8-sig")

# 财务数据（已清洗，避免未来数据）
financial_file = f"{DATA_DIR}/financial_monthly_clean.csv.gz"
if not os.path.exists(financial_file):
    financial_file = f"{DATA_DIR}/financial_monthly_clean.csv"
df_financial = pd.read_csv(financial_file, encoding="utf-8-sig")
df_financial["date"] = pd.to_datetime(df_financial["date"])
df_financial = df_financial.rename(columns={"stock_code": "symbol"})
print(f"  财务数据: {len(df_financial):,} 条记录")

stocks = sorted(df_daily["symbol"].unique())
dates = sorted(df_daily["date"].unique())
print(f"  股票数: {len(stocks)}")
print(f"  日期范围: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}")
print(f"  交易日数: {len(dates)}")

# ============================================================
# 计算所有角色的因子
# ============================================================
print("\n" + "=" * 60)
print("🔧 计算因子...")
print("=" * 60)

# 按股票计算因子（向量化处理）
role_factor_data = {}

for role, factor_defs in ROLE_FACTORS.items():
    print(f"\n  [{role}] 计算 {len(factor_defs)} 个因子...")
    role_results = []

    for i, fdef in enumerate(factor_defs):
        col_name = fdef["col"]
        all_stock_factors = []

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
                all_stock_factors.append(result[["date", "symbol", col_name]])
            except Exception as e:
                pass

        if all_stock_factors:
            factor_df = pd.concat(all_stock_factors, ignore_index=True)
            role_results.append(factor_df)
            print(f"    ✅ {col_name}: {len(all_stock_factors)} 只股票")

    if role_results:
        # 合并该角色的所有因子
        merged = role_results[0]
        for r in role_results[1:]:
            merged = merged.merge(r, on=["date", "symbol"], how="outer")
        role_factor_data[role] = merged
        print(f"  [{role}] 完成, 因子列数: {len(merged.columns) - 2}")

# ============================================================
# 因子综合得分 & 选股
# ============================================================
print("\n" + "=" * 60)
print("🎯 因子综合评分 & 选股...")
print("=" * 60)

# ============================================================
# 财务因子计算（新增）
# ============================================================
print("\n  [财务因子] 计算价值+质量因子...")

# 1. 计算财务因子
df_with_financial = compute_financial_factors(df_financial, df_daily)

# 2. Z-score标准化
financial_cols = ['value_pe', 'value_pb', 'quality_roe']
df_with_financial = zscore_financial_factors(df_with_financial, financial_cols)

# 3. 提取财务因子列
financial_factor_cols = [f'factor_{col}' for col in financial_cols]
financial_factors = df_with_financial[['date', 'symbol'] + financial_factor_cols].copy()
financial_factors = financial_factors.dropna(subset=financial_factor_cols, how='all')

print(f"    ✅ 财务因子计算完成: {len(financial_factors):,} 条记录")
print(f"    包含因子: {', '.join(financial_factor_cols)}")

# 4. 将财务因子添加到「个股分析师」的角色因子中
if '个股分析师' in role_factor_data:
    # 合并财务因子
    existing = role_factor_data['个股分析师']
    merged = existing.merge(financial_factors, on=['date', 'symbol'], how='left')
    role_factor_data['个股分析师'] = merged
    print(f"    ✅ 财务因子已添加到「个股分析师」角色")
    print(f"    「个股分析师」因子数: {len(merged.columns) - 2}")

role_selections = {}  # {role: {month: [stock_list]}}

for role, fdata in role_factor_data.items():
    factor_cols = [c for c in fdata.columns if c not in ("date", "symbol")]
    fdata = fdata.copy()

    # 综合得分 = 各因子等权平均（已标准化）
    fdata["composite_score"] = fdata[factor_cols].mean(axis=1)
    fdata["year_month"] = fdata["date"].dt.to_period("M")

    selections = {}
    for ym, group in fdata.groupby("year_month"):
        # 每月末取综合得分最高的TOP_N只
        month_end = group[group["date"] == group["date"].max()]
        if len(month_end) < TOP_N:
            continue
        top_stocks = month_end.nlargest(TOP_N, "composite_score")["symbol"].tolist()
        selections[ym] = top_stocks

    role_selections[role] = selections
    print(f"  [{role}] 调仓月数: {len(selections)}, 每月选 {TOP_N} 只")

# ============================================================
# 回测模拟
# ============================================================
print("\n" + "=" * 60)
print("📈 回测模拟...")
print("=" * 60)

# 计算每只股票的日收益率
df_daily["return"] = df_daily.groupby("symbol")["close"].pct_change()

# 指数收益率
df_index["index_return"] = df_index["close"].pct_change()
index_returns = df_index.set_index("date")["index_return"]

role_portfolio_returns = {}  # {role: pd.Series of monthly returns}

for role in DYNAMIC_ROLES:
    if role not in role_selections:
        continue

    selections = role_selections[role]
    monthly_returns = []

    sorted_months = sorted(selections.keys())
    for ym in sorted_months:
        stocks_in = selections[ym]
        # 获取该月的交易日
        month_start = ym.start_time
        if ym == sorted_months[-1]:
            month_end = dates[-1]
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
        # 扣除调仓成本（月初一天）
        cost = (COMMISSION_RATE + SLIPPAGE_RATE) * 2  # 买卖双边
        if len(daily_rets) > 0:
            daily_rets.iloc[0] -= cost

        # 月收益 = (1 + r1) * (1 + r2) * ... - 1
        month_ret = (1 + daily_rets).prod() - 1
        monthly_returns.append({"month": ym, "return": month_ret})

    if monthly_returns:
        ret_df = pd.DataFrame(monthly_returns).set_index("month")
        role_portfolio_returns[role] = ret_df["return"]
        total_ret = (1 + ret_df["return"]).prod() - 1
        ann_ret = (1 + total_ret) ** (12 / len(ret_df)) - 1 if len(ret_df) > 0 else 0
        print(f"  [{role}] 月数: {len(ret_df)}, 累计收益: {total_ret:.2%}, 年化收益: {ann_ret:.2%}")

# ============================================================
# 指数基准收益
# ============================================================
index_monthly = df_index.copy()
index_monthly["year_month"] = index_monthly["date"].dt.to_period("M")
index_monthly_ret = index_monthly.groupby("year_month")["index_return"].apply(
    lambda x: (1 + x.dropna()).prod() - 1
)

# ============================================================
# 贡献度计算
# ============================================================
print("\n" + "=" * 60)
print("📊 贡献度计算...")
print("=" * 60)

# 方法1: 信息系数 (IC) — 因子选股能力
print("\n  --- 方法1: 信息系数 (IC) ---")
role_ic = {}
for role in DYNAMIC_ROLES:
    if role not in role_factor_data:
        role_ic[role] = 0
        continue
    fdata = role_factor_data[role]
    factor_cols = [c for c in fdata.columns if c not in ("date", "symbol")]
    fdata = fdata.copy()
    fdata["composite_score"] = fdata[factor_cols].mean(axis=1)

    # 计算IC: 因子得分与下期收益的秩相关
    fdata["next_ret"] = fdata.groupby("symbol")["date"].transform(
        lambda x: fdata.loc[x.index, "composite_score"].shift(-1)
    )
    # 简化：按月计算IC
    fdata["year_month"] = fdata["date"].dt.to_period("M")
    ic_values = []
    for ym, group in fdata.groupby("year_month"):
        if len(group) < 20:
            continue
        month_end = group[group["date"] == group["date"].max()]
        if len(month_end) < 10:
            continue
        # 使用下月收益计算IC
        next_month = ym + 1
        next_data = fdata[fdata["year_month"] == next_month]
        if len(next_data) == 0:
            continue
        next_month_end = next_data[next_data["date"] == next_data["date"].max()]
        merged = month_end[["symbol", "composite_score"]].merge(
            next_month_end[["symbol", "composite_score"]],
            on="symbol", suffixes=("_curr", "_next")
        )
        if len(merged) >= 10:
            ic = merged["composite_score_curr"].corr(merged["composite_score_next"])
            if not np.isnan(ic):
                ic_values.append(ic)

    avg_ic = np.mean(ic_values) if ic_values else 0
    role_ic[role] = avg_ic
    print(f"    {role}: IC = {avg_ic:.4f} ({len(ic_values)} 个月)")

# 方法2: 超额收益归因
print("\n  --- 方法2: 超额收益归因 ---")
role_excess = {}
for role in DYNAMIC_ROLES:
    if role not in role_portfolio_returns:
        role_excess[role] = 0
        continue
    port_ret = role_portfolio_returns[role]
    # 对齐指数收益
    aligned_idx = []
    for m in port_ret.index:
        if m in index_monthly_ret.index:
            aligned_idx.append(index_monthly_ret[m])
        else:
            aligned_idx.append(0)
    excess = port_ret.values - np.array(aligned_idx)
    avg_excess = np.mean(excess)
    role_excess[role] = avg_excess
    print(f"    {role}: 月均超额 = {avg_excess:.4%}")

# 方法3: 增量贡献法 (Leave-One-Out)
print("\n  --- 方法3: 增量贡献法 ---")
# 计算所有角色组合的总收益
all_combined = None
for role in DYNAMIC_ROLES:
    if role not in role_portfolio_returns:
        continue
    ret = role_portfolio_returns[role]
    if all_combined is None:
        all_combined = ret.copy()
    else:
        # 对齐索引
        common = all_combined.index.intersection(ret.index)
        all_combined = all_combined.loc[common] + ret.loc[common]

role_incremental = {}
if all_combined is not None:
    total_return = (1 + all_combined).prod() - 1
    for leave_role in DYNAMIC_ROLES:
        if leave_role not in role_portfolio_returns:
            role_incremental[leave_role] = 0
            continue
        # 去掉该角色后的组合收益
        reduced = None
        for role in DYNAMIC_ROLES:
            if role == leave_role or role not in role_portfolio_returns:
                continue
            ret = role_portfolio_returns[role]
            if reduced is None:
                reduced = ret.copy()
            else:
                common = reduced.index.intersection(ret.index)
                reduced = reduced.loc[common] + ret.loc[common]

        if reduced is not None:
            reduced_return = (1 + reduced).prod() - 1
            incremental = total_return - reduced_return
        else:
            incremental = total_return
        role_incremental[leave_role] = incremental
        print(f"    去掉 {leave_role}: 总收益下降 {incremental:.4%}")

# ============================================================
# 综合评分
# ============================================================
print("\n" + "=" * 60)
print("🏆 综合评分...")
print("=" * 60)

# 归一化各指标
def normalize(d):
    vals = list(d.values())
    min_v, max_v = min(vals), max(vals)
    if max_v == min_v:
        return {k: 0.5 for k in d}
    return {k: (v - min_v) / (max_v - min_v) for k, v in d.items()}

ic_norm = normalize(role_ic)
excess_norm = normalize(role_excess)
incr_norm = normalize(role_incremental)

# 综合得分 = IC权重30% + 超额收益权重40% + 增量贡献权重30%
role_final_scores = {}
for role in DYNAMIC_ROLES:
    score = 0.3 * ic_norm.get(role, 0) + 0.4 * excess_norm.get(role, 0) + 0.3 * incr_norm.get(role, 0)
    role_final_scores[role] = score

# 确保所有贡献为正
min_score = min(role_final_scores.values())
if min_score <= 0:
    for role in role_final_scores:
        role_final_scores[role] -= min_score - 0.01

# 归一化为权重
total_score = sum(role_final_scores.values())
new_pool_weights = {role: score / total_score for role, score in role_final_scores.items()}

print("\n  新池动态权重 (研究支持层):")
for role, w in sorted(new_pool_weights.items(), key=lambda x: -x[1]):
    print(f"    {role}: {w:.2%}")

# ============================================================
# 最终分配方案
# ============================================================
print("\n" + "=" * 60)
print("📋 最终分配方案 (6:4双轨制)")
print("=" * 60)

# 新池中：研究支持层占新池的权重
# 研究层总权重 = sum(new_pool_weights.values()) = 1.0
# 证据池资源量 = 可分配资源总量 * 40%
# 研究层证据池资源量 = 可分配资源总量 * 40% * 1.0

# 最终个人权重 = 旧池 * 60% + 新池动态 * 40%
final_weights = {}
for role, old_w in OLD_POOL_WEIGHTS.items():
    if role in new_pool_weights:
        new_w = new_pool_weights[role]
        final_w = OLD_POOL_RATIO * old_w + NEW_POOL_RATIO * new_w
    else:
        final_w = OLD_POOL_RATIO * old_w
    final_weights[role] = final_w

# 归一化
total_final = sum(final_weights.values())
final_weights = {k: v / total_final for k, v in final_weights.items()}

print("\n  角色        旧池权重  新池动态  最终权重  变化")
print("  " + "-" * 55)
for role in OLD_POOL_WEIGHTS:
    old_w = OLD_POOL_WEIGHTS[role]
    new_w = new_pool_weights.get(role, 0)
    final_w = final_weights[role]
    change = final_w - old_w
    direction = "↑" if change > 0.001 else ("↓" if change < -0.001 else "→")
    print(f"  {role:<10}  {old_w:>6.1%}   {new_w:>6.1%}   {final_w:>6.1%}   {direction} {abs(change):.1%}")

# ============================================================
# 绩效指标
# ============================================================
print("\n" + "=" * 60)
print("📊 角色绩效指标")
print("=" * 60)

perf_data = []
for role in DYNAMIC_ROLES:
    if role not in role_portfolio_returns:
        continue
    ret = role_portfolio_returns[role]
    if len(ret) < 2:
        continue

    cum_ret = (1 + ret).prod() - 1
    n_months = len(ret)
    ann_ret = (1 + cum_ret) ** (12 / n_months) - 1 if n_months > 0 else 0
    ann_vol = ret.std() * np.sqrt(12)
    sharpe = (ann_ret - RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0
    max_dd = (1 + ret).cumprod().div((1 + ret).cumprod().cummax()).min() - 1
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    win_rate = (ret > 0).mean()

    perf_data.append({
        "角色": role,
        "累计收益": cum_ret,
        "年化收益": ann_ret,
        "年化波动": ann_vol,
        "夏普比率": sharpe,
        "最大回撤": max_dd,
        "卡尔玛比率": calmar,
        "胜率": win_rate,
        "IC均值": role_ic.get(role, 0),
        "月均超额": role_excess.get(role, 0),
        "新池权重": new_pool_weights.get(role, 0),
    })

perf_df = pd.DataFrame(perf_data)
print(perf_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

# ============================================================
# 保存报告
# ============================================================
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# 1. 绩效报告
perf_df.to_csv(f"{REPORT_DIR}/quantskills_performance_{timestamp}.csv", index=False, encoding="utf-8-sig")

# 2. 分配方案
alloc_data = []
for role in OLD_POOL_WEIGHTS:
    alloc_data.append({
        "角色": role,
        "旧池权重": OLD_POOL_WEIGHTS[role],
        "新池动态权重": new_pool_weights.get(role, 0),
        "最终权重": final_weights[role],
        "类型": "研究支持层" if role in DYNAMIC_ROLES else ("决策层" if role in ["基金经理", "投资经理"] else "团队层"),
    })
alloc_df = pd.DataFrame(alloc_data)
alloc_df.to_csv(f"{REPORT_DIR}/quantskills_allocation_{timestamp}.csv", index=False, encoding="utf-8-sig")

# 3. 各角色选股记录
for role, selections in role_selections.items():
    records = []
    for ym, stocks in selections.items():
        for s in stocks:
            records.append({"月份": str(ym), "股票代码": s})
    pd.DataFrame(records).to_csv(
        f"{REPORT_DIR}/quantskills_selections_{role}_{timestamp}.csv",
        index=False, encoding="utf-8-sig"
    )

# 4. 汇总报告
report_lines = []
report_lines.append("=" * 60)
report_lines.append("基于QuantSkills因子库的业绩归因回测报告")
report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append("=" * 60)
report_lines.append("")
report_lines.append("一、因子库概况")
report_lines.append(f"  - 因子来源: QuantSkills标准化因子库")
report_lines.append(f"  - 覆盖方向类因子 (directional-alpha): 296个")
report_lines.append(f"  - 覆盖风险类因子 (risk-pattern-alpha): 288个")
report_lines.append(f"  - 覆盖量能类因子 (volume-stat-alpha): 216个")
report_lines.append(f"  - 实际使用因子数: {sum(len(f) for f in ROLE_FACTORS.values())}")
report_lines.append("")
report_lines.append("二、角色-因子映射")
for role, factors in ROLE_FACTORS.items():
    report_lines.append(f"  {role}: {len(factors)} 个因子")
    for f in factors:
        report_lines.append(f"    - {f['col']}: {f['base']} + {f['transform']}")
report_lines.append("")
report_lines.append("三、回测参数")
report_lines.append(f"  - 初始资金: {INITIAL_CAPITAL:,.0f}")
report_lines.append(f"  - 调仓频率: {REBALANCE_FREQ}")
report_lines.append(f"  - 每角色选股数: {TOP_N}")
report_lines.append(f"  - 手续费率: {COMMISSION_RATE:.2%}")
report_lines.append(f"  - 滑点率: {SLIPPAGE_RATE:.2%}")
report_lines.append("")
report_lines.append("四、绩效指标")
report_lines.append(perf_df.to_string(index=False))
report_lines.append("")
report_lines.append("五、分配方案")
report_lines.append(alloc_df.to_string(index=False))
report_lines.append("")
report_lines.append("六、结论")
report_lines.append("  基于QuantSkills标准化因子库的回测，各研究支持层角色的贡献度排序为:")
for role, w in sorted(new_pool_weights.items(), key=lambda x: -x[1]):
    report_lines.append(f"    {role}: {w:.2%}")

with open(f"{REPORT_DIR}/quantskills_report_{timestamp}.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print(f"\n✅ 报告已保存到: {REPORT_DIR}/")
print(f"  - quantskills_performance_{timestamp}.csv")
print(f"  - quantskills_allocation_{timestamp}.csv")
print(f"  - quantskills_report_{timestamp}.txt")
print(f"  - quantskills_selections_*_{timestamp}.csv")
