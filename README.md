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

AlphaSplit 以更合理的分配机制为手段：把组合超额收益归因从资产 / 因子 / 风格**延伸到投研组织角色**，用五角色 Pipeline + **Shapley 联盟归因**形成可解释贡献证据，并在 **6:4 双轨**框架下支持广义价值分配。直接目标是调动各角色参与积极性、促进投研协同与决策质量提升，长期目标是促进投资回报改善。系统不承诺收益，最终分配由评审委员会（或机构治理责任人）独立确认。

---

## 核心能力

| 模块 | 说明 |
|------|------|
| **五角色建模** | 行业 / 个股 / 策略 / 量化 / 风控，场景见 `data/scenarios/hs300_five_roles.json` |
| **Shapley 归因** | `v(S)=联盟收益−同期HS300收益`，2⁵=32 子集输出角色超额边际贡献（非仅 LOO） |
| **6:4 双轨价值分配** | `最终 = 60%×现行方案 + 40%×夏普利证据池`，可用于预算、研究资源、项目机会、数据/算力额度和激励权益，详见 [`docs/双轨分配机制.md`](docs/双轨分配机制.md) |
| **Agent 层** | 独立目录 `agent_layer/`；无 Key 时提供经校验的离线 Agent 演示缓存，配置 Key 后可调用 DeepSeek |
| **路演 Demo UI** | 单页全流程：回测 → 归因 → 角色贡献陈述（参考）→ 评审委员会决策 |
| **HS300 真实数据** | `data/processed/` 离线行情与因子，开箱可跑 |

---

## 要解决什么问题

资管与量化投研是多角色协作。经典业绩归因能回答「收益来自配置还是选股」，却很少回答：

> **各投研角色分别贡献了多少？依据是什么？**

缺少客观、可回测的贡献证据时，考核只能依赖固定比例或主观评议。本项目提供可复现链路：

```
角色建模 → 反事实 / 联盟回测 → Shapley 贡献系数 → 6:4 合成建议 → 角色陈述参考 → 评审委员会决策
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
Shapley 贡献 + 回测证据 + 6:4 双轨建议 + 角色陈述参考 + 评审委员会决策
```

| 层次 | 做什么 |
|------|--------|
| 信号层 | 公开行情 + 因子库，表达各角色「决策输入」 |
| 计量层 | 特征函数 v(S)、32 子集 Shapley，向公理化目标对齐 |
| 智能层 | `agent_layer/` 规划回测、结果解读；夏普利计算不走 LLM |
| 输出层 | 贡献系数、归因图、角色参考意见、评审委员会决策接口 |

---

## 演示流程（Web UI）

启动后访问 **http://127.0.0.1:8000**，按页签顺序体验：

1. **回测归因** — 选择时间区间，运行 HS300 五角色 Pipeline，查看 NAV / 角色选股与 Shapley 表  
2. **Agent 规划** — 自然语言或预设生成回测方案，一键「规划并回测」  
3. **角色贡献陈述（评审参考）** — 五类角色基于贡献证据表达意见，但不参与建议份额计算
4. **评审委员会决策** — 录入机构现行分配，查看 **6:4 双轨建议**，由评审委员会（或机构治理责任人）独立调整并确认

界面截图见 `docs/figures/`（如 `fig5-4a~e` 路演页）。

---

## 快速开始

### 环境要求

- Python 3.10+（推荐 3.11）
- 日常安装使用 `requirements-lock.txt`（已验证锁定版本）
- `requirements.txt` 保留为开发依赖范围声明

### Linux / macOS

```bash
git clone https://github.com/Willsgao/AlphaSplit.git
cd AlphaSplit
pip install -r requirements-lock.txt
python -m engine.api.main
# 浏览器打开 http://127.0.0.1:8000
```

### Windows

将项目完整解压到本地目录（不要直接在压缩包预览中运行），确认已安装
Python 3.11 64 位后，直接双击 **`一键启动.cmd`**。单击文件时，资源管理器
右侧可能只显示脚本预览；需要在文件列表中双击文件本身：

- 首次运行自动创建项目专用 `.venv` 并安装锁定依赖，需要联网，通常耗时 1–5 分钟；
- 后续运行会校验依赖清单，未变化时直接跳过安装；
- 服务就绪后自动打开浏览器，无需激活虚拟环境；
- 保持命令窗口开启，按 `Ctrl+C` 停止服务。

需要诊断或自定义端口时，可在项目目录打开 PowerShell：

```powershell
.\install.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\start.ps1
.\start.ps1 -Port 8765
.\install.ps1 -Force  # 强制重装依赖
```

### 运行测试

```bash
pip install pytest
pytest tests/ -q
```

### 腾讯云部署

推荐使用根目录 `Dockerfile` 与 `compose.yaml` 部署完整 Web 应用，并由 Nginx
对外提供访问。OpenCloudOS 的首次安装、公开演示模式、安全组和更新命令见：

[`deploy/tencent/README.md`](deploy/tencent/README.md)

服务器已安装 Docker 与 Compose 后，在服务器执行：

```bash
cd /data
git clone https://github.com/Willsgao/AlphaSplit.git
cd AlphaSplit
cp deploy/tencent/alphasplit.env.example .env
chmod 600 .env
bash deploy/tencent/install.sh
```

默认采用公开演示模式：离线 Agent 缓存和预跑演示包可以完整展示，同时阻止
公网匿名用户触发高耗时真实回测。腾讯云安全组只需放行 TCP 80，不要放行
容器绑定的本机端口 8766。

### 可选：接入 DeepSeek（Agent 自然语言）

新用户会在页面“告诉Agent你希望怎样投资”区域顶部看到“选择 Agent 运行方式”，可直接选择“保持离线完整演示”，也可选择“输入 API Key”启用在线 Agent。密钥只保存在当前本地服务的进程内存中，不写入项目文件或浏览器，服务重启后自动清除；也可在页面随时清除并恢复离线缓存模式。不输入密钥时，系统默认使用随提交包提供的离线 Agent 缓存，仍可完整体验建议、确认和回测流程。

也可以在启动前通过环境变量配置：

```bash
export DEEPSEEK_API_KEY=sk-...   # Windows: $env:DEEPSEEK_API_KEY="sk-..."
# 未配置时使用 Mock，演示不依赖外网
```

Windows 设置环境变量后，在同一个 PowerShell 窗口执行 `.\start.ps1`。

未配置 Key 时，默认路演偏好及三组常见偏好会命中
`agent_layer/cache/factor_agent_responses.json` 中的预置 Agent 响应。缓存响应会在每次使用时重新经过
因子白名单、参数范围、归一化和人工确认校验，并在界面明确标注“预置Agent响应 · 离线”；未命中缓存的自由输入才回退规则 Agent。

---

## 主要 API

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/scenarios` | 场景列表 |
| POST | `/api/calculate` | 合成回测 + 归因（轻量） |
| POST | `/api/negotiate` | 生成五角色贡献陈述与评审建议（接口名保留兼容） |
| POST | `/api/confirm` | 评审委员会确认分配决定（含 6:4 双轨） |
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

公开演示（例如 ngrok）建议只开放预计算演示包：

```powershell
$env:ALPHASPLIT_PUBLIC_DEMO_ONLY = "1"
python -m engine.api.main --mode mock --host 127.0.0.1 --port 8000
```

如需远程访问真实回测与历史结果，可设置 Token，并在请求头中传入
`X-AlphaSplit-Token`。真实回测采用单任务互斥，已有任务运行时返回 HTTP 409。

```powershell
$env:ALPHASPLIT_API_TOKEN = "请替换为高强度随机值"
```

---

## 仓库结构

```
AlphaSplit/
├── README.md
├── requirements.txt          # 开发依赖范围声明
├── requirements-lock.txt     # 已验证依赖锁定版本
├── 一键启动.cmd              # Windows 唯一双击启动入口
├── install.ps1               # 自动创建环境并安装锁定依赖
├── start.ps1                 # 校验环境、启动服务并打开浏览器
├── agent_layer/              # 可替换 Agent 实现（独立目录）
│   └── cache/                # 无 API Key 时的经校验离线 Agent 演示响应
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
    ├── agentic/              # 角色贡献陈述与评审决策支持
    ├── api/                  # FastAPI
    └── web/                  # 路演 Demo 前端
```

### 数据说明

真实回测依赖 `data/processed/` 中的前复权日 K（仓库保存为
`hs300_daily_qfq.csv.gz`）、清洗后财务数据（`financial_monthly_clean.csv.gz`）
及指数、行业和股票映射表；Pandas 会直接读取压缩文件，无需手动解压。
原始全量未复权文件和重复的回退副本不纳入 Git。本地保留同名 `.csv` 时，
引擎仍兼容读取。

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
| 投研角色贡献计量 Demo / 可扩展框架 | 可直接替代机构治理的自动决策系统 |
| Shapley + Agent 规划的可解释证据链 | 精确因果的唯一真相 |
| 公开因子「套壳」或脱敏数据做机制验证 | 已替代机构内部真实决策日志 |
| 协商锚点 + 6:4 双轨供人工决策 | 算法自动确定最终分配方案 |

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
