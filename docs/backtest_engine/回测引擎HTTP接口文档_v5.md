# 回测引擎 HTTP 接口文档 v5.2

**作者:** 徐远
**日期:** 2026年8月22日
**用途:** 面向 Agent / HR 系统的标准 HTTP 接口。Agent 将 HR 的自然语言查询解析为结构化 JSON，POST 到回测引擎，返回可直接生成报告的完整归因结果。**本文档是接口的唯一权威文档**（已整合原 v1/v2/v3/v4 规范，旧文档已删除）。

> **本文档对应的部署形态**：接口代码部署在本地或云服务器，Agent（LLM 服务）与回测引擎通过 HTTP 通信。流程为：**HR 自然语言 → Agent 解析为 JSON → POST `/api/v1/run` → 引擎回测 → 返回结果 JSON → Agent 生成报告**。网页版 `web_app.py` 仅供开发自测，不用于生产。

> **涵盖范围**：HTTP 调用方式、请求/响应格式、字段枚举（含 84 行业列表）、错误码、结果下载、Agent 解析规则（§8）、部署方式、约束事项。旧版 `Agent接口规范_v1~v4` 已并入本文档并删除。

---

## 1. 服务概述

| 项目 | 说明 |
|------|------|
| 服务名 | 金融产品业绩贡献计量与绩效考评系统 - 回测归因引擎 |
| 接口版本 | `v1`（URL 前缀 `/api/v1`） |
| 默认监听 | `0.0.0.0:5051` |
| 实现文件 | `backtest/server.py`（独立 HTTP 服务，与网页版解耦） |
| 核心引擎 | `backtest/query_engine.py` 的 `run_query()` |
| 响应格式 | JSON（UTF-8） |

### 1.1 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/health` | 健康检查 |
| `GET` | `/api/v1/meta` | 元信息（合法取值枚举） |
| `GET` | `/api/v1/docs` | 接口文档概要 |
| `POST` | `/api/v1/run` | **执行回测（主入口）** |
| `GET` | `/api/v1/results/{request_id}/response.json` | 下载某次回测完整结果 JSON |
| `GET` | `/api/v1/results/{request_id}/all.zip` | 下载某次回测全部中间数据 |

---

## 2. 启动与部署

本节分两部分：**开发自测启动**（本地 `python3 server.py`）与**生产部署**（gunicorn + supervisor / Docker，部署到本地或云服务器）。

> 部署形态：接口代码与数据**同机**（数据位于项目根目录 `data/processed`）。接口目录结构：
> ```
> FinTech/
> ├── data/processed/        # 回测数据（勿改动）
> ├── backtest/              # 接口代码
> │   ├── server.py          # Flask 应用（接口）
> │   ├── wsgi.py            # 生产 WSGI 入口
> │   ├── gunicorn.conf.py   # gunicorn 配置
> │   ├── deploy.sh          # 一键部署脚本
> │   ├── deploy/            # supervisor 配置
> │   ├── Dockerfile / docker-compose.yml
> │   └── requirements.txt
> └── docs/                  # 文档
> ```

### 2.1 依赖安装

```bash
cd backtest
pip install -r requirements.txt
# flask, pandas(>=1.5,<3.0), numpy
```

> **⚠️ pandas 版本强约束**：项目代码使用 `'M'` 频率（月度）。**pandas 3.0 起 `'M'` 被废弃、需改用 `'ME'`**，会导致回测报 `EXECUTION_ERROR: Invalid frequency: M`。`requirements.txt` 已锁定 `pandas>=1.5.0,<3.0`，请勿手动升级到 pandas 3.x。

### 2.2 开发自测启动（本地调试用）

```bash
cd backtest
python3 server.py                          # 默认 0.0.0.0:5051
python3 server.py --port 8080              # 自定义端口
python3 server.py --host 127.0.0.1 --port 9000 --debug
```

或使用脚本：

```bash
cd backtest
./start_server.sh                          # 默认 5051
./start_server.sh 8080                     # 指定端口
FINBACK_BASE_DIR=/path/to/FinTech ./start_server.sh   # 指定项目根目录（数据所在位置）
```

启动成功会打印：

```
🚀 回测引擎 HTTP 接口服务
   接口版本: v1
   监听地址: 0.0.0.0:5051
   主入口:   POST http://0.0.0.0:5051/api/v1/run
   健康检查: GET  http://0.0.0.0:5051/api/v1/health
```

### 2.3 生产部署（推荐，部署到本地/云服务器）

生产环境使用 **gunicorn**（WSGI 服务器）替代 Flask 开发服务器，并用 **supervisor**（或 systemd / Docker）保证进程常驻、崩溃自动拉起。

**一键部署脚本 `backtest/deploy.sh`：**

```bash
cd backtest
./deploy.sh install          # ① 首次部署：创建 venv + 安装依赖（含 gunicorn）
./deploy.sh start            # ② 启动服务（优先 supervisor，否则 gunicorn 后台运行）
./deploy.sh status           # ③ 查看运行状态
./deploy.sh health           # ④ 健康检查
./deploy.sh logs             # ⑤ 查看日志
./deploy.sh stop|restart     # 停止 / 重启
```

**方式 A：gunicorn 直接运行（无需 supervisor）**

```bash
cd backtest
./deploy.sh install
BACKTEST_BIND="0.0.0.0:5051" ./deploy.sh start
curl http://127.0.0.1:5051/api/v1/health
```

gunicorn 相关文件：
- `wsgi.py`：生产 WSGI 入口（`wsgi:app`）
- `gunicorn.conf.py`：配置（默认 `0.0.0.0:5051`，`workers=1`，`preload`，超时 `600s`）

手动启动 gunicorn：
```bash
cd backtest
venv/bin/gunicorn -c gunicorn.conf.py wsgi:app        # 前台
venv/bin/gunicorn -c gunicorn.conf.py wsgi:app --daemon --pid backtest.pid  # 后台
```

> **worker 数为何是 1**：引擎内部为串行计算，且每次回测需加载全量数据（数百 MB）。多 worker 会重复加载数据、内存成倍增长，且不会带来并发加速。若确有多个 Agent 同时请求，可通过 `BACKTEST_WORKERS` 调大，但要关注内存（约 = worker 数 × 单进程内存）。

**方式 B：supervisor 进程管理（生产推荐，崩溃自动拉起）**

配置模板在 `backtest/deploy/supervisor_backtest.conf`。部署：

```bash
# 1) 生成实际路径配置（deploy.sh 会自动做）
cd backtest
./deploy.sh start   # 会提示 supervisor 手动操作

# 2) 或手动：
sudo cp deploy/supervisor_backtest.conf /etc/supervisor/conf.d/backtest.conf
#    按需修改 directory / command / user / environment（默认 /opt/FinTech）
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start backtest
sudo supervisorctl status          # 查看状态
sudo supervisorctl restart backtest
```

**方式 C：Docker 容器化（可选）**

```bash
# 项目根目录下
docker compose -f backtest/docker-compose.yml up -d
curl http://127.0.0.1:5051/api/v1/health
docker compose -f backtest/docker-compose.yml logs -f
docker compose -f backtest/docker-compose.yml down
```

Docker 相关文件：`backtest/Dockerfile`、`backtest/docker-compose.yml`、`backtest/.dockerignore`。数据目录 `data/` 与结果目录 `backtest/results/` 通过 volume 挂载（代码与数据同机场景）。

> **说明**：`FINBACK_BASE_DIR` 环境变量用于指定项目根目录（数据在 `<BASE>/data/processed`，结果写入 `<BASE>/backtest/results`）。不设置时自动探测 `backtest/` 上一级是否为项目根目录。部署到云服务器时，若代码路径非标准位置，建议显式设置。

---

## 3. 健康检查与元信息

### 3.1 健康检查

```bash
curl http://<host>:5051/api/v1/health
```

```json
{
  "status": "ok",
  "service": "金融产品业绩贡献计量与绩效考评系统 - 回测归因引擎",
  "api_version": "v1",
  "time": "2026-08-22T04:02:51.528392"
}
```

### 3.2 元信息（Agent 动态获取合法取值）

```bash
curl http://<host>:5051/api/v1/meta
```

```json
{
  "api_version": "v1",
  "name": "金融产品业绩贡献计量与绩效考评系统 - 回测归因引擎",
  "roles": ["行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师"],
  "benchmarks": ["hs300", "csi500", "shanghai"],
  "rebalance_freq": ["monthly", "quarterly", "yearly"],
  "granularity": ["monthly", "quarterly", "yearly"],
  "error_codes": ["INDUSTRY_NOT_FOUND", "ROLE_NOT_FOUND", "INVALID_PARAM", "NO_DATA", "EXECUTION_ERROR"],
  "default_benchmark": "hs300",
  "default_rebalance_freq": "monthly",
  "default_granularity": "monthly"
}
```

Agent 集成时可先调用 `/api/v1/meta`，用返回的角色/基准/频率列表动态校验参数，避免硬编码枚举。

---

## 4. 执行回测（主入口）

```
POST /api/v1/run
Content-Type: application/json
```

### 4.1 请求格式

支持两种格式，引擎均能识别：

**格式 A：嵌套格式（v4 规范，推荐，Agent 解析自然语言后生成）**

```json
{
  "request_id": "q_20260822_001",
  "timestamp": "2026-08-22T10:00:00+08:00",
  "query": {
    "time_range": {
      "start_date": "2024-01-01",
      "end_date": "2024-12-31"
    },
    "target_role": null,
    "industry": null,
    "role_weights": null,
    "benchmark": null,
    "rebalance_freq": null,
    "granularity": null
  }
}
```

**格式 B：扁平格式（把 query 字段直接平铺在顶层）**

```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "industry": null,
  "target_role": null,
  "role_weights": null,
  "benchmark": "hs300",
  "rebalance_freq": "monthly",
  "granularity": "monthly"
}
```

> `request_id` / `timestamp` 缺省时引擎自动生成。`query` 下所有字段全部可选，留空/`null` 用默认值。

### 4.2 请求字段说明（全部可选）

| 字段 | 类型 | 说明 | 为空时处理 |
|------|------|------|-----------|
| `query.time_range` | object | 时间范围，含 `start_date`/`end_date`（`YYYY-MM-DD`） | 使用全部数据范围 |
| `query.target_role` | string | 聚焦角色（仅影响展示，归因仍为全集 5 角色） | 返回所有角色 |
| `query.industry` | string | 行业板块筛选（东方财富二级，84 个） | 全行业汇总 |
| `query.role_weights` | object | 各角色「相对调节系数」（新池 40% 内，未给角色默认 1.0=等权） | 各角色系数 = 1.0（纯 Shapley） |
| `query.benchmark` | string | 基准指数：`hs300`/`csi500`/`shanghai` | `hs300` |
| `query.rebalance_freq` | string | 调仓频率：`monthly`/`quarterly`/`yearly` | `monthly` |
| `query.granularity` | string | 结果时间粒度：`monthly`/`quarterly`/`yearly` | `monthly` |

#### 字段枚举

- **target_role**：`行业分析师` / `个股分析师` / `策略分析师` / `量化分析师` / `风控分析师`
- **benchmark**：`hs300`（沪深300）/ `csi500`（中证500）/ `shanghai`（上证指数）
- **rebalance_freq / granularity**：`monthly` / `quarterly` / `yearly`
- **industry**：84 个东方财富二级行业（与 `stock_industry_mapping.json` 一致），完整列表：
  ```
  半导体, 证券Ⅱ, 银行, 银行Ⅱ, 消费电子, 基础建设, 非银金融, 电力,
  食品饮料, 汽车, 计算机, 元件, 通信, 汽车零部件, 医药生物, 有色金属,
  电子, 工业金属, 通信设备, 光伏设备, 交通运输, 公用事业, 航空机场,
  机械设备, 家用电器, 国防军工, 基础化工, 电网设备, 电池, 农林牧渔,
  软件开发, 煤炭, 房地产, 农化制品, 小金属, 钢铁, 化学制药, 中药Ⅱ,
  物流, 传媒, 白酒Ⅱ, 能源金属, 航空装备Ⅱ, 生物制品, 电力设备,
  通信服务, 石油石化, 建筑材料, 炼化及贸易, 多元金融, 铁路公路,
  计算机设备, 专用设备, 游戏Ⅱ, 化学原料, 数字媒体, 医疗器械,
  IT服务Ⅱ, 贵金属, 饮料乳品, 电源设备, 保险Ⅱ, 轨交设备, 航运港口,
  光学光电子, 工程机械, 军工电子Ⅱ, 风电设备, 商贸零售, 医疗美容,
  农产品加工, 商用车, 船舶制造, 化学制品, 一般零售, 其他电源设备Ⅱ,
  燃气Ⅱ, 油气开采, 港口, 乘用车, 医药商业, 社会服务, 医疗服务,
  调味发酵品
  ```
  也可调用 `/api/v1/meta` 校验；引擎返回的 `INDUSTRY_NOT_FOUND` 错误信息中同样带上全部有效行业 + 模糊匹配提示。
- **role_weights** 示例（相对调节系数，权重自动归一化，单角色新池上限 50%）：
  ```json
  {
    "行业分析师": 0.3,
    "个股分析师": 3.0,
    "策略分析师": 0.2,
    "量化分析师": 0.15,
    "风控分析师": 0.15
  }
  ```

### 4.3 curl 调用示例

```bash
curl -X POST http://<host>:5051/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "q_001",
    "query": {
      "time_range": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
      "industry": "半导体",
      "target_role": null,
      "role_weights": null,
      "benchmark": "hs300",
      "rebalance_freq": "monthly",
      "granularity": "monthly"
    }
  }'
```

### 4.4 Python 调用示例

```python
import requests, json

resp = requests.post(
    "http://127.0.0.1:5051/api/v1/run",
    json={
        "request_id": "q_001",
        "query": {
            "time_range": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
            "industry": "半导体",
            "target_role": None,
            "role_weights": None,
            "benchmark": "hs300",
            "rebalance_freq": "monthly",
            "granularity": "monthly",
        },
    },
    timeout=600,
)
result = resp.json()
print(result["query_summary"])
print(result["results"]["recommendation"]["summary"])
```

---

## 5. 响应格式

### 5.1 成功响应（HTTP 200）

```json
{
  "request_id": "q_001",
  "timestamp": "2026-08-22T10:01:00+08:00",
  "status": "success",
  "query_summary": "2024-01-01~2024-12-31，所有角色，全行业，monthly调仓",

  "results": {
    "overview": {
      "total_return": 0.35,
      "total_return_desc": "组合累计收益35.00%",
      "benchmark_return": 0.12,
      "benchmark_return_desc": "基准(沪深300)收益12.00%",
      "excess_return": 0.23,
      "excess_return_desc": "超额收益23.00%，跑赢基准",
      "sharpe_ratio": 2.15,
      "sharpe_ratio_desc": "夏普比率2.15，风险调整后收益良好",
      "max_drawdown": -0.08,
      "max_drawdown_desc": "最大回撤8.00%",
      "relative_contributions": {"行业分析师": 0.20, "个股分析师": 0.15, "...": "..."},
      "attribution_type": "shapley",
      "attribution_description": "各角色Shapley贡献（带符号，和为全组合收益）"
    },

    "target_role": null,
    "role_ranking": ["行业分析师", "策略分析师", "个股分析师", "量化分析师", "风控分析师"],
    "role_ranking_desc": "行业分析师 > 策略分析师 > 个股分析师 > 量化分析师 > 风控分析师",

    "role_breakdown": [
      {
        "role": "行业分析师",
        "is_target": false,
        "weight": 0.20,
        "hr_weight": null,
        "shapley_raw": 0.28,
        "contribution_raw": 0.28,
        "contribution": 0.28,
        "contribution_relative": 0.33,
        "contribution_pct": 0.33,
        "highlight": "行业分析师贡献+28.00%，贡献最大",
        "performance": {
          "cumulative_return": 0.1211,
          "annual_return": 0.1211,
          "annual_volatility": 0.1532,
          "sharpe_ratio": 0.89,
          "max_drawdown": -0.1102,
          "win_rate": 0.5333
        }
      }
    ],

    "highlights": [
      { "type": "target_positive", "text": "聚焦角色「个股分析师」贡献+15.00%，排名第3，为正贡献" },
      { "type": "positive", "text": "行业分析师贡献最大（+28.00%），是组合收益的主要来源" },
      { "type": "negative", "text": "风控分析师贡献为负（-2.00%），拖累组合表现，建议重点复盘" },
      { "type": "info", "text": "组合跑赢基准23.00%，主动管理整体有效" }
    ],

    "recommendation": {
      "summary": "超额收益23.00%，跑赢基准，建议新池40%按贡献分配，行业分析师分配最高（20.0%）",
      "focus": "重点复盘风控分析师（贡献-2.00%），其负贡献主要拖累组合",
      "role_weights_impact": "若HR调整某角色权重（新池内调节系数），其分配占比将相应变化"
    },

    "filter_detail": {
      "industry": null,
      "benchmark": "hs300",
      "rebalance_freq": "monthly"
    },

    "time_series": [
      { "period": "2024-01", "return": 0.05, "benchmark": 0.02 },
      { "period": "2024-02", "return": -0.03, "benchmark": -0.05 }
    ]
  }
}
```

### 5.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | string | 请求 ID（回显） |
| `timestamp` | string | 响应时间 |
| `status` | string | `success` / `error` |
| `query_summary` | string | 人类可读的查询摘要（供 Agent 与用户确认） |
| `results.overview` | object | 整体绩效指标（每个数值带 `*_desc` 人话描述） |
| `results.target_role` | string\|null | 聚焦角色（null=所有角色） |
| `results.role_ranking` | array | 各角色贡献排名（从高到低） |
| `results.role_ranking_desc` | string | 排名的自然语言描述 |
| `results.role_breakdown` | array | 各角色贡献明细（5 个） |
| `results.highlights` | array | 主要发现（正负贡献、聚焦角色、超额结论） |
| `results.recommendation` | object | 新池 40% 分配建议 + 复盘建议 |
| `results.filter_detail` | object | 实际使用的筛选条件 |
| `results.time_series` | array | 按 granularity 分段的收益序列 |

**overview 中每个指标带人话描述：**

| 字段 | 说明 |
|------|------|
| `total_return` / `total_return_desc` | 组合累计收益 |
| `benchmark_return` / `benchmark_return_desc` | 基准收益 |
| `excess_return` / `excess_return_desc` | 超额收益（正=跑赢，负=跑输） |
| `sharpe_ratio` / `sharpe_ratio_desc` | 夏普比率 |
| `max_drawdown` / `max_drawdown_desc` | 最大回撤 |
| `relative_contributions` | 各角色 Shapley 份额（`φᵢ/Σφ`，带符号，可正可负；非原始 φ 值） |
| `attribution_type` / `attribution_description` | 归因方法说明 |

> **注**：`relative_contributions` 是归一化份额（Shapley φ 除以总和），因 `Σφ` 可正可负，故该字段带符号。若需每个角色的原始 Shapley 值，请用 `role_breakdown[].shapley_raw`。若 `attribution_type` 为 `relative_benchmark`（非 Shapley 分支），该字段为相对基准归因占比。
>
> **注**：当回测区间过短（≤ 1 个调仓月，无法计算夏普/回撤）时，`max_drawdown`/`sharpe_ratio` 为 `0`，其 `*_desc` 为"回测区间过短，暂无法计算……"（而非缺失）。

**role_breakdown 中每个元素：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | 角色名称 |
| `is_target` | boolean | 是否聚焦角色（target_role） |
| `weight` | number | **新池 40% 内分配权重**（归一化，单角色上限 50%） |
| `hr_weight` | number\|null | HR 调节系数（未设则 null） |
| `shapley_raw` | number | Shapley φ 原始值（带符号） |
| `contribution_raw` | number | 绝对贡献值（=shapley_raw） |
| `contribution` | number | 规范键名，与 `contribution_raw` 一致 |
| `contribution_relative` | number | Shapley 贡献占比（0~1） |
| `contribution_pct` | number | 贡献占比（=contribution_relative） |
| `highlight` | string | 一句话亮点（供 Agent 直接转述） |
| `performance` | object | 该角色参与组合的绩效指标 |

**highlights 中每个元素：**

| 字段 | 说明 |
|------|------|
| `type` | `positive` / `negative` / `info` / `warning` / `target_positive` / `target_negative` / `target_neutral` |
| `text` | 亮点人话描述（供 Agent 直接转述） |

> 指定 `target_role` 时，`highlights` 第一条会聚焦该角色（`target_*`），且 `role_breakdown` 中该角色 `is_target=true`。归因仍为全集 5 角色计算。

**time_series 中 period 格式取决于 granularity：**

| granularity | period 格式 | 示例 |
|-------------|-----------|------|
| monthly | `YYYY-MM` | `"2024-01"` |
| quarterly | `YYYY-QN` | `"2024-Q1"` |
| yearly | `YYYY` | `"2024"` |

---

## 6. 错误响应

### 6.1 错误格式

引擎会返回统一的错误结构，并附带 HTTP 状态码：

```json
{
  "request_id": "q_003",
  "status": "error",
  "error_code": "INDUSTRY_NOT_FOUND",
  "error_message": "无效行业「半导体行业」，请在以下行业中选择（共84个）：\n['半导体', '消费电子', ...]（近似: ['半导体']）"
}
```

### 6.2 错误码 → HTTP 状态码映射

| error_code | HTTP | 说明 |
|------------|------|------|
| `INDUSTRY_NOT_FOUND` | 400 | 行业名称无法识别（error_message 含 84 个有效行业 + 近似提示） |
| `ROLE_NOT_FOUND` | 400 | 角色名称无法识别 |
| `INVALID_PARAM` | 400 | 参数无效（非 JSON、无效基准/调仓频率/粒度） |
| `NO_DATA` | 404 | 查询范围内无数据（日期或行业无数据、下载时结果不存在） |
| `EXECUTION_ERROR` | 500 | 其他执行错误 |

> Agent 可从 `error_message` 中提取有效行业/角色列表做二次选择（如模糊匹配提示 `近似: ['半导体']`）。

---

## 7. 结果下载

每次回测会在 `backtest/results/<request_id>/` 下生成中间数据。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/results/<request_id>/response.json` | 下载该次回测完整结果 JSON |
| `GET` | `/api/v1/results/<request_id>/all.zip` | 下载全部中间数据（打包 zip） |

中间文件包括：

| 文件名 | 内容 |
|--------|------|
| `response.json` | 完整结果 JSON（主输出） |
| `daily_returns.csv` | 每日收益（组合+基准） |
| `selections.csv` | 每月选股明细（股票代码+权重+来源角色） |
| `rebalance_events.csv` | 调仓事件（买入/卖出/换手率） |
| `factor_scores.csv` | 因子得分 |
| `monthly_stats.csv` | 月度统计 |

---

## 8. 使用场景与 Agent 解析规则

### 8.1 使用场景

HR 用自然语言提问，Agent 识别意图和条件，生成查询 JSON。

**核心原则：HR 说多少，解析多少，没提到的字段留 `null`。**

| HR 的自然语言 | Agent 解析的条件 | 未提到的字段 |
|-------------|----------------|-------------|
| "2024年整体贡献分配" | time_range=2024全年 | 其他全部 null |
| "去年半导体行业的贡献" | time_range=2025, industry=半导体 | 角色/权重等 null |
| "个股分析师今年贡献多少" | time_range=2026, target_role=个股分析师 | 行业等 null |
| "按季度看贡献变化" | time_range=今年, granularity=quarterly | 行业/角色等 null |
| "相对中证500的超额收益" | benchmark=csi500 | 行业/角色等 null |
| "行业分析师权重按30%算" | role_weights.行业分析师=0.3 | 其他 null |
| "个股分析师重要性给3倍" | role_weights.个股分析师=3.0 | 其他 null |

### 8.2 时间识别

| HR 表述 | 解析结果 |
|--------|----------|
| "今年" | start_date=当年1月1日, end_date=今天 |
| "去年" | start_date=去年1月1日, end_date=去年12月31日 |
| "2024年" | start_date=2024-01-01, end_date=2024-12-31 |
| "Q3" / "第三季度" | start_date=当年7月1日, end_date=当年9月30日 |
| "上半年" | start_date=当年1月1日, end_date=当年6月30日 |

### 8.3 行业识别

Agent 需维护一张"自然语言 → 标准行业名"的映射表：

| HR 表述 | 解析结果 |
|--------|----------|
| "半导体" / "芯片" | industry = "半导体" |
| "银行" | industry = "银行" |
| "白酒" / "酒类" | industry = "白酒Ⅱ" |
| "医药" | industry = "医药生物" |
| "新能源" / "光伏" | industry = "光伏设备" |
| "汽车" / "造车" | industry = "汽车" |
| "券商" / "证券" | industry = "证券Ⅱ" |
| "基建" | industry = "基础建设" |
| "AI" / "人工智能" | industry = "计算机" |

完整行业列表见 §4.2 字段枚举。

### 8.4 角色识别

| HR 表述 | 解析结果 |
|--------|----------|
| "行业分析师" / "看行业的" | target_role = "行业分析师" |
| "个股分析师" / "选股的" | target_role = "个股分析师" |
| "策略分析师" / "择时的" | target_role = "策略分析师" |
| "量化" / "量化分析师" | target_role = "量化分析师" |
| "风控" / "风险控制" | target_role = "风控分析师" |

### 8.5 权重识别

| HR 表述 | 解析结果 |
|--------|----------|
| "行业分析师权重按30%" | role_weights.行业分析师 = 0.3, 其他 = null（用默认） |
| "各角色五五开" | role_weights = 各0.2 |

> **role_weights 语义（新池 40% 内的相对调节系数）**：
> - 未给角色默认系数 1.0（等权，纯 Shapley 客观贡献）；
> - 新池权重_i = |Shapleyφ_i| × role_weights_i（归一化，单角色上限 50%）；
> - 只影响"新池 40%"内部分配，不影响归因结果（Shapley 贡献不变）。

---

## 9. Agent 接入流程

```
HR 自然语言提问（如"去年半导体行业，个股分析师贡献多少，按季度看"）
   ↓
Agent 识别意图，构造 query JSON（参考 §4）
   ↓
POST /api/v1/run
   ↓
拿到 result JSON（status=success）
   ↓
Agent 直接读结论层字段生成报告：
   - query_summary        → 确认查询条件
   - results.overview     → 整体绩效（含人话 desc）
   - results.role_ranking → 角色贡献排名
   - results.highlights   → 主要发现（可直接转述）
   - results.recommendation → 新池 40% 分配建议
   - results.role_breakdown → 逐角色明细（含 is_target）
   ↓
返回自然语言回答给 HR
```

**Agent 优先使用的字段：**
- 一句话总结：`results.recommendation.summary`
- 整体表现：`results.overview`（配 `*_desc`）
- 关键发现：`results.highlights[*].text`
- 分配建议：`results.role_breakdown[*].weight`（新池 40% 内占比）
- 是否跑赢：`results.overview.excess_return`

---

## 10. 约束与注意事项

1. **数据范围**：日 K 线约 2022-06 至 2025-12（以实际数据为准，日期越界会触发 `NO_DATA`）。
2. **可用行业**：84 个（东方财富二级分类）。
3. **可用角色**：5 个（行业/个股/策略/量化/风控分析师）。
4. **计算耗时**：单次回测约 30~60 秒（Shapley 需跑多次子集回测）。HTTP 客户端应设置足够超时（建议 ≥ 600s）。
5. **结果是确定性的**：相同输入 → 相同输出（历史数据不变，种子固定）。
6. **6:4 双池**：`role_breakdown.weight` 只代表「新池 40%」内部测算权重；旧池 60% 既定分配不在本系统计算范围。
7. **role_weights** 是「相对调节系数」（默认 1.0），只影响新池 40% 内分配，不改变 Shapley 归因结果。
8. **生产部署**：默认 Flask 开发服务器（`python3 server.py`）**不适用于生产**，仅作开发自测。生产必须用 gunicorn（详见 §2.3），命令为 `venv/bin/gunicorn -c gunicorn.conf.py wsgi:app`。引擎内部为串行计算，`workers` 固定为 1（配置见 `gunicorn.conf.py`）。
9. **pandas 版本**：必须 `>=1.5,<3.0`。若意外升级到 pandas 3.x，回测会报 `Invalid frequency: M`（见 §2.1）。
10. **网页版 vs 接口**：`web_app.py`（5050 端口）是给开发者自测的网页演示；`server.py`/`gunicorn`（5051）才是给 Agent 调用的正式接口，两者可同时运行，互不影响。

---

## 11. 更新日志

- **2026-08-22（v5.2）**：文档自包含——将原 `Agent接口规范_v4.md` 的独有内容（84 个行业完整列表、使用场景、Agent 解析规则）并入本文档，删除全部旧规范文档（v1/v2/v3/v4），v5 成为唯一权威接口文档。
- **2026-08-22（v5.1）**：补齐生产部署章节（gunicorn + supervisor + Docker 三选一 + 一键部署脚本 `deploy.sh`）；新增生产 WSGI 入口 `wsgi.py`、`gunicorn.conf.py`、supervisor 模板、Dockerfile/docker-compose；`requirements.txt` 锁定 `pandas<3.0`（规避 pandas 3.x 的 `'M'` 频率破坏）。
- **2026-08-22（v5.0）**：新增独立 HTTP 服务 `backtest/server.py`，与网页版解耦；统一 `/api/v1/*` 端点、健康检查、元信息、标准错误码 + HTTP 状态码映射、结果下载；完整透传 v4.1 结论层。
