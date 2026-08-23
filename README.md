# AlphaSplit：多智能体驱动的投研角色贡献计量平台

> *Alpha is earned. Contribution should be measured.*

面向：[第五届中国研究生金融科技创新大赛](https://cpipc.acge.org.cn/cw/hp/2c90800c8093eef401809d3501080654)  
赛道：自拟题目 · **人工智能技术在金融领域的创新应用**

| 仓库 | 地址 |
|------|------|
| GitHub | https://github.com/Willsgao/AlphaSplit |
| Gitee | https://gitee.com/willsgao/AlphaSplit |

技术文档目录：[`docs/技术文档目录.md`](docs/技术文档目录.md) · 架构摘要：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 一句话

把组合收益的归因，从资产 / 因子 / 风格**延伸到投研组织角色**；用五角色 Pipeline + **Shapley 联盟归因**量化贡献，经多智能体规划反事实回测产出可解释证据，并在 **6:4 双轨**框架下供人工确认——**贡献计量与决策参考，不是自动发薪系统**。

---

## 核心能力

| 模块 | 说明 |
|------|------|
| **五角色建模** | 行业 / 个股 / 策略 / 量化 / 风控，场景见 `data/scenarios/hs300_five_roles.json` |
| **Shapley 归因** | 2⁵=32 联盟子集回测，输出角色边际贡献（非仅 LOO） |
| **6:4 双轨分配** | `最终 = 60%×现行分配 + 40%×夏普利新池`，详见 [`docs/双轨分配机制.md`](docs/双轨分配机制.md) |
| **Agent 层** | 独立目录 `agent_layer/`，可替换规划 / 解读实现；默认 Mock，可选 DeepSeek |
| **路演 Demo UI** | 单页全流程：回测 → 归因 → 五角色协商 → 双轨确认 |
| **HS300 真实数据** | `data/processed/` 离线行情与因子，开箱可跑 |

---

## 要解决什么问题

资管与量化投研是多角色协作。经典业绩归因能回答「收益来自配置还是选股」，却很少回答：

> **各投研角色分别贡献了多少？依据是什么？**

缺少客观、可回测的贡献证据时，考核只能依赖固定比例或主观评议。本项目提供可复现链路：

```
角色建模 → 反事实 / 联盟回测 → Shapley 贡献系数 → 协商锚点 → 6:4 合成 → 人工确认
```

与「自动挖因子」类工作的区隔：QuantSkills / Loop 解决**因子发现**；本项目借用因子与回测能力，解决**角色贡献计量**。

---

## 解题思路

```
经典业绩归因（配置 / 选股 / 择时 / 风格 …）
        │ 映射
        ▼
投研组织五角色（行业 / 个股 / 策略 / 量化 / 风控）
        │ 决策输入用公开因子「套壳」表达（可替换为真实决策日志）
        ▼
Agent 层：规划对照方案 → 执行回测 → 解读 → 不达标可重试
        │
        ▼
Shapley 贡献 + 回测证据 + 五角色协商 + 6:4 双轨确认
```

| 层次 | 做什么 |
|------|--------|
| 信号层 | 公开行情 + 因子库，表达各角色「决策输入」 |
| 计量层 | 特征函数 v(S)、32 子集 Shapley，向公理化目标对齐 |
| 智能层 | `agent_layer/` 规划回测、结果解读；夏普利计算不走 LLM |
| 输出层 | 贡献系数、归因图、协商记录、人工确认接口 |

---

## 演示流程（Web UI）

启动后访问 **http://127.0.0.1:8000**，按页签顺序体验：

1. **回测归因** — 选择时间区间，运行 HS300 五角色 Pipeline，查看 NAV / 角色选股与 Shapley 表  
2. **Agent 规划** — 自然语言或预设生成回测方案，一键「规划并回测」  
3. **五角色协商** — 基于回测与基线权重生成协商建议（非三人 `quant_fund` 旧 Demo）  
4. **人工确认** — 录入机构现行分配，查看 **6:4 双轨合成** 与确认结果  

界面截图见 `docs/figures/`（如 `fig5-4a~e` 路演页）。

---

## 快速开始

### 环境要求

- Python 3.10+（推荐 3.11）
- 依赖见 `requirements.txt`

### Linux / macOS

```bash
git clone https://github.com/Willsgao/AlphaSplit.git
cd AlphaSplit
pip install -r requirements.txt
python -m engine.api.main
# 浏览器打开 http://127.0.0.1:8000
```

### Windows

```powershell
.\start.ps1
# 或手动：python -m engine.api.main --host 127.0.0.1 --port 8000
```

### 运行测试

```bash
pip install pytest
pytest tests/ -q
```

### 可选：接入 DeepSeek（Agent 自然语言）

```bash
export DEEPSEEK_API_KEY=sk-...   # Windows: $env:DEEPSEEK_API_KEY="sk-..."
# 未配置时使用 Mock，演示不依赖外网
```

---

## 主要 API

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/scenarios` | 场景列表 |
| POST | `/api/calculate` | 合成回测 + 归因（轻量） |
| POST | `/api/negotiate` | 五角色协商 |
| POST | `/api/confirm` | 人工确认（含 6:4 双轨） |
| GET | `/api/backtest/meta` | 回测引擎元信息 |
| POST | `/api/backtest/run` | 提交 HS300 回测任务 |
| GET | `/api/backtest/results/{id}` | 获取回测结果 |
| GET | `/api/agent/meta` | Agent 层元信息 |
| POST | `/api/agent/plan` | 规划回测方案 |
| POST | `/api/agent/pipeline` | 规划 + 回测 + 解读 |

完整回测 HTTP 契约：`docs/backtest_engine/回测引擎HTTP接口文档_v5.md`  
Agent 替换说明：[`agent_layer/README.md`](agent_layer/README.md)

回测请求示例：

```json
{
  "request_id": "demo_001",
  "query": {
    "time_range": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
    "benchmark": "hs300",
    "rebalance_freq": "monthly",
    "granularity": "monthly"
  }
}
```

> 单次完整 Shapley 回测约 1–7 分钟，请设置足够 HTTP 超时。

---

## 仓库结构

```
AlphaSplit/
├── README.md
├── requirements.txt
├── start.ps1                 # Windows 一键启动
├── agent_layer/              # 可替换 Agent 实现（独立目录）
├── backtest/                 # QuantSkills 回测归因引擎
├── data/
│   ├── scenarios/            # 场景与先验（含 hs300_five_roles.json）
│   └── processed/            # HS300 离线数据（复权日 K 等）
├── docs/
│   ├── ARCHITECTURE.md
│   ├── 双轨分配机制.md
│   ├── backtest_engine/      # 回测接口文档
│   └── figures/              # 文档 / 路演插图
├── tests/
└── engine/
    ├── core/                 # 合成回测 · 归因 · 结算
    ├── integrations/         # 回测引擎与 agent_layer 桥接
    ├── agentic/              # 五角色协商等
    ├── api/                  # FastAPI
    └── web/                  # 路演 Demo 前端
```

### 数据说明

演示依赖 `data/processed/` 中的复权日 K（`hs300_daily_qfq.csv`）及配套因子表。  
原始全量未复权文件 `hs300_daily_all.csv`（>100MB）未纳入 Git；本地若有可自行放置，引擎会优先使用 `hs300_daily_qfq.csv`。

### 独立回测服务（可选）

与主 API 并列，亦可单独启动交付包风格服务：

```bash
cd backtest
pip install flask "pandas>=1.5.0,<3.0" numpy
python server.py --host 127.0.0.1 --port 5051   # POST /api/v1/run
python web_app.py                                # 浏览器 http://127.0.0.1:5050
```

---

## 团队分工

| 成员 | 职责 |
|------|------|
| **高玉伟** | 整体把控、报名对接、前端、报告 / 技术文档统稿 |
| **汪皓怡** | 审核、精益画布与答辩材料、原创性声明流程 |
| **董斌** | 金融叙事、共享方与角色口径、权重公式与行业依据 |
| **徐远** | 回测数据、因子—角色映射与回测实现、实验指标 |
| **朱宗基** | 多智能体方案评估与优化、自动化回测闭环、结果解读 |

---

## 诚实边界

| 是 | 不是 |
|----|------|
| 投研角色贡献计量 Demo / 可扩展框架 | 已上线自动薪酬系统 |
| Shapley + Agent 规划的可解释证据链 | 精确因果的唯一真相 |
| 公开因子「套壳」或脱敏数据做机制验证 | 已替代机构内部真实决策日志 |
| 协商锚点 + 6:4 双轨供人工决策 | 算法自动确定最终薪酬 |

---

## 赛事节点

| 节点 | 日期 |
|------|------|
| 报名截止 | 约 2026-08-17 |
| 作品提交 | 2026-08-31 15:00 |
| 初赛评审（含可运行性测试） | 8 月下旬–9 月中旬 |
| 决赛路演 | 10 月中下旬 |

初赛四件套：精益画布 · 可运行成果 · 技术文档 · 原创性声明。

---

## License

MIT © 2026 AlphaSplit Team
