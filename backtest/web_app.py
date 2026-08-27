"""
回测引擎 Web 演示界面
=====================
简单的Flask应用，展示v4接口全流程。

功能：
- 下拉框选择查询参数
- 执行回测
- 展示分析报告
- 下载结果JSON

作者: 徐远 | 日期: 2026-08-19
"""
from flask import Flask, render_template, request, jsonify, send_file
import json
import os
import sys
from datetime import datetime

# 添加路径（Sprint 0: 自适应本地/服务器）
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKTEST_DIR not in sys.path:
    sys.path.insert(0, _BACKTEST_DIR)
from query_engine import run_query

# results 目录（可用 FINBACK_BASE_DIR 覆盖）
if os.getenv("FINBACK_BASE_DIR"):
    RESULTS_DIR = os.path.join(os.environ["FINBACK_BASE_DIR"], "backtest", "results")
else:
    RESULTS_DIR = os.path.join(_BACKTEST_DIR, "results")

app = Flask(__name__)

# 行业列表（从数据中提取）
INDUSTRIES = [
    "半导体", "证券Ⅱ", "银行", "银行Ⅱ", "消费电子", "基础建设", "非银金融", "电力",
    "食品饮料", "汽车", "计算机", "元件", "通信", "汽车零部件", "医药生物", "有色金属",
    "电子", "工业金属", "通信设备", "光伏设备", "交通运输", "公用事业", "航空机场",
    "机械设备", "家用电器", "国防军工", "基础化工", "电网设备", "电池", "农林牧渔",
    "软件开发", "煤炭", "房地产", "农化制品", "小金属", "钢铁", "化学制药", "中药Ⅱ",
    "物流", "传媒", "白酒Ⅱ", "能源金属", "航空装备Ⅱ", "生物制品", "电力设备",
    "通信服务", "石油石化", "建筑材料", "炼化及贸易", "多元金融", "铁路公路",
    "计算机设备", "专用设备", "游戏Ⅱ", "化学原料", "数字媒体", "医疗器械",
    "IT服务Ⅱ", "贵金属", "饮料乳品", "电源设备", "保险Ⅱ", "轨交设备", "航运港口",
    "光学光电子", "工程机械", "军工电子Ⅱ", "风电设备", "商贸零售", "医疗美容",
    "农产品加工", "商用车", "船舶制造", "化学制品", "一般零售", "其他电源设备Ⅱ",
    "燃气Ⅱ", "油气开采", "港口", "乘用车", "医药商业", "社会服务", "医疗服务",
    "调味发酵品"
]

ROLES = ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"]

@app.route("/")
def index():
    """主页"""
    return render_template("index.html", industries=INDUSTRIES, roles=ROLES)

@app.route("/api/run", methods=["POST"])
def run_backtest():
    """执行回测API
    
    支持两种请求格式：
      1. 团队约定的嵌套格式（Agent 解析自然语言后生成）：
         {"query": {"time_range": {"start_date","end_date"}, "industry", ...}}
      2. 前端的扁平格式：
         {"start_date", "end_date", "industry", ...}
    """
    try:
        data = request.json or {}

        # 若传入的是团队约定的嵌套 query 格式，直接透传 run_query
        if "query" in data and isinstance(data["query"], dict) and "time_range" in data["query"]:
            # 补充缺失的 request_id
            q = dict(data)
            if not q.get("request_id"):
                q["request_id"] = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if not q.get("timestamp"):
                q["timestamp"] = datetime.now().isoformat()
            result = run_query(q)
            return jsonify(result)

        # 否则按扁平格式处理（前端表单）
        query = {
            "request_id": f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "query": {
                "time_range": {
                    "start_date": data.get("start_date", "2024-01-01"),
                    "end_date": data.get("end_date", "2024-12-31")
                },
                "target_role": data.get("target_role") or None,
                "industry": data.get("industry") or None,
                "role_weights": data.get("role_weights") or None,
                "benchmark": data.get("benchmark", "hs300"),
                "rebalance_freq": data.get("rebalance_freq", "monthly"),
                "granularity": data.get("granularity", "monthly")
            }
        }
        
        # 执行回测
        result = run_query(query)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error_message": str(e)
        }), 400

@app.route("/api/download/<request_id>")
def download_result(request_id):
    """下载结果JSON"""
    filepath = os.path.join(RESULTS_DIR, request_id, "response.json")
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=f"backtest_{request_id}.json")
    return jsonify({"error": "文件不存在"}), 404

@app.route("/api/download_all/<request_id>")
def download_all(request_id):
    """下载所有中间数据（打包）"""
    import zipfile
    import io
    
    result_dir = os.path.join(RESULTS_DIR, request_id)
    if not os.path.exists(result_dir):
        return jsonify({"error": "目录不存在"}), 404
    
    # 创建zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in os.listdir(result_dir):
            filepath = os.path.join(result_dir, filename)
            if os.path.isfile(filepath):
                zf.write(filepath, filename)
    
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'backtest_{request_id}_all.zip'
    )

@app.route("/api/hr_report/<request_id>")
def hr_report(request_id):
    """生成治理责任人友好版报告（保留路由名以兼容旧调用）。"""
    filepath = os.path.join(RESULTS_DIR, request_id, "response.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "结果不存在"}), 404
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 提取关键信息
    results = data.get("results", {})
    overview = results.get("overview", {})
    breakdown = results.get("role_breakdown", [])
    filter_detail = results.get("filter_detail", {})
    
    total_return = overview.get("total_return", 0)
    benchmark_return = overview.get("benchmark_return", 0)
    excess_return = overview.get("excess_return", 0)
    sharpe_ratio = overview.get("sharpe_ratio", 0)
    max_drawdown = overview.get("max_drawdown", 0)
    relative_contributions = overview.get("relative_contributions", {})
    
    # 生成治理责任人友好版报告
    report = {
        "summary": "",
        "performance_summary": {},
        "role_contributions": [],
        "key_metrics": [],
        "recommendation": ""
    }
    
    # 1. 一句话总结
    industry = filter_detail.get("industry", "全行业")
    time_range = data.get("query_summary", "").split("，")[0] if "，" in data.get("query_summary", "") else "未知"
    
    if excess_return > 0.00005:
        report["summary"] = f"✅ {time_range}期间，{industry}行业主动管理策略表现优秀，跑赢沪深300基准{excess_return:.2%}。"
    elif excess_return < -0.00005:
        report["summary"] = f"⚠️ {time_range}期间，{industry}行业主动管理策略表现不佳，跑输沪深300基准{abs(excess_return):.2%}。"
    else:
        report["summary"] = f"ℹ️ {time_range}期间，{industry}行业主动管理策略与沪深300基准基本持平。"
    
    # 2. 绩效总结
    report["performance_summary"] = {
        "portfolio_return": f"{total_return:.2%}",
        "benchmark_return": f"{benchmark_return:.2%}",
        "excess_return": f"{excess_return:.2%}",
        "verdict": (
            "跑赢基准" if excess_return > 0.00005
            else "跑输基准" if excess_return < -0.00005
            else "与基准基本持平"
        )
    }
    
    # 3. 角色贡献（治理版）
    role_explanations = {
        "行业分析师": "负责选择投资哪些行业，通过分析行业趋势和前景做出决策",
        "个股分析师": "负责在选定行业内选择具体股票，通过分析公司基本面和财务数据做出决策",
        "策略分析师": "负责决定何时买卖和仓位管理，通过分析市场波动和趋势做出决策",
        "量化分析师": "负责优化选股策略，通过多策略平均降低选股的随机性",
        "风控分析师": "负责控制投资风险，通过设置仓位限制和止损线保护资金安全"
    }
    
    for role in breakdown:
        role_name = role.get("role", "")
        contribution_raw = role.get("contribution_raw", 0)
        contribution_pct = role.get("contribution_pct", 0)
        highlight = role.get("highlight", "")
        
        # 解释贡献
        if contribution_raw > 0:
            contribution_explanation = f"正向贡献，提升了组合收益{contribution_raw:.2%}"
        elif contribution_raw < 0:
            contribution_explanation = f"负向贡献，拖累了组合收益{abs(contribution_raw):.2%}"
        else:
            contribution_explanation = "无明显贡献"
        
        report["role_contributions"].append({
            "role": role_name,
            "explanation": role_explanations.get(role_name, ""),
            "contribution": contribution_explanation,
            "weight": f"{contribution_pct:.1%}",
            "highlight": highlight
        })
    
    # 4. 关键指标解释
    report["key_metrics"] = [
        {
            "name": "组合收益",
            "value": f"{total_return:.2%}",
            "explanation": "我们实际的投资回报率"
        },
        {
            "name": "基准收益",
            "value": f"{benchmark_return:.2%}",
            "explanation": "如果什么都不做，直接买入沪深300指数能获得的收益"
        },
        {
            "name": "超额收益",
            "value": f"{excess_return:.2%}",
            "explanation": "我们比基准多赚或少赚的部分，正数表示跑赢，负数表示跑输"
        },
        {
            "name": "夏普比率",
            "value": f"{sharpe_ratio:.2f}",
            "explanation": "风险调整后的收益指标，越高越好，大于1表示较好"
        },
        {
            "name": "最大回撤",
            "value": f"{max_drawdown:.2%}",
            "explanation": "投资期间的最大亏损幅度，越小越好"
        }
    ]
    
    # 5. 广义价值分配建议
    if excess_return > 0:
        report["recommendation"] = f"超额收益为正（{excess_return:.2%}），可将角色权重用于广义价值分配决策。"
        report["bonus_allocation"] = [
            {"role": r["role"], "weight": r["weight"], "reason": r["contribution"]}
            for r in report["role_contributions"]
        ]
    else:
        report["recommendation"] = f"⚠️ 超额收益为负（{excess_return:.2%}），主动管理未创造价值。建议："
        report["recommendation_details"] = [
            "暂停扩大贡献证据池",
            "现行资源方案保持稳定，暂不按本期结果增加动态份额",
            "重点改进拖累收益最大的角色（个股分析师）"
        ]
        report["bonus_allocation"] = [
            {"role": r["role"], "weight": r["weight"], "reason": r["contribution"]}
            for r in report["role_contributions"]
        ]
    
    return jsonify(report)


if __name__ == "__main__":
    # 端口 5050（5000 常被 macOS AirPlay 占用）
    app.run(host="0.0.0.0", port=5050, debug=False)
