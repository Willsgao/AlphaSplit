# 回测引擎接口 - Agent 同事交接说明

**给 Agent 负责同学的对接说明**：本说明 + `docs/回测引擎HTTP接口文档_v5.md`（唯一接口规范），即可在本地把接口跑起来并联调。

---

## 一、你收到了什么

交付包 `agent_delivery_YYYYMMDD.tar.gz` 解压后：

```
agent_delivery/
├── README.md                # 快速开始
├── backtest/                # 接口代码
│   ├── server.py            # Flask 接口（主入口）
│   ├── wsgi.py              # 生产 WSGI 入口
│   ├── query_engine.py      # 核心回测引擎
│   ├── data_loader.py / quant_engine.py / ...   # 引擎各模块
│   ├── requirements.txt     # 依赖
│   ├── start_server.sh / deploy.sh   # 启动 / 部署脚本
│   └── gunicorn.conf.py / Dockerfile / docker-compose.yml  # 生产部署
├── data/
│   └── processed/           # 回测必需数据（勿改动）
└── docs/
    ├── 回测引擎HTTP接口文档_v5.md   # ★ 对接接口的唯一文档
    └── Agent同事交接说明.md        # 本文档
```

---

## 二、本地部署（方式一：本地自测联调）

> 前提：本机已装 Python 3.8+。

```bash
cd backtest
python3 -m venv venv                 # 可选，建议建虚拟环境
source venv/bin/activate             # macOS/Linux；Windows 用 venv\Scripts\activate
pip install -r requirements.txt
python3 server.py                    # 启动，监听 0.0.0.0:5051
```

看到以下输出即成功：

```
🚀 回测引擎 HTTP 接口服务
   监听地址: 0.0.0.0:5051
   主入口:   POST http://0.0.0.0:5051/api/v1/run
```

**注意**：`data/processed/` 必须与 `backtest/` 处于同一项目根下（即 `data/` 在 `backtest/` 的上一级），引擎会自动探测；若目录结构不同，用环境变量指定：
```bash
FINBACK_BASE_DIR=/你的解压路径 python3 server.py
```

---

## 三、健康检查

```bash
curl http://127.0.0.1:5051/api/v1/health
# 期望返回: {"status":"ok","api_version":"v1",...}
```

---

## 四、调用接口（核心）

**唯一主入口**：`POST http://127.0.0.1:5051/api/v1/run`

### 4.1 一个最小可用请求

```bash
curl -X POST http://127.0.0.1:5051/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "q_001",
    "query": {
      "time_range": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
      "target_role": null,
      "industry": null,
      "role_weights": null,
      "benchmark": "hs300",
      "rebalance_freq": "monthly",
      "granularity": "monthly"
    }
  }'
```

### 4.2 调用流程

```
HR 自然语言（如"去年半导体行业，个股分析师贡献多少"）
   → Agent 按接口文档 §8 解析规则生成 JSON
   → POST /api/v1/run
   → 拿到结果 JSON
   → 直接读结论层字段生成 HR 报告
```

### 4.3 你（Agent）主要读哪些字段

| 字段 | 用途 |
|------|------|
| `results.recommendation.summary` | 一句话总结 + 分配建议 |
| `results.overview`（含 `*_desc`） | 整体绩效（人话描述） |
| `results.highlights[].text` | 主要发现（可直接转述） |
| `results.role_breakdown[].weight` | 各角色「新池 40%」分配权重 |
| `results.role_breakdown[].shapley_raw` | 各角色 Shapley 原始贡献 |

---

## 五、常见问题

| 问题 | 处理 |
|------|------|
| 回测很慢（30~60 秒） | 正常。Shapley 需跑多次子集回测。HTTP 客户端超时建议设 ≥600s |
| 返回 `INDUSTRY_NOT_FOUND` | 行业名不在 84 个内，`error_message` 里带全部行业 + 近似提示 |
| 返回 `INVALID_PARAM` | 参数格式错误（见接口文档 §4/§6） |
| 我改端口 | `python3 server.py --port 8080` |
| 需要远程调用 | 见下节「远程联调」 |

---

## 六、远程联调（无共用服务器时）

本地服务起来后，用内网穿透把 5051 端口暴露成公网地址，对方即可远程调用。

**方式 A：ngrok（最简单）**
```bash
pip install ngrok  # 或下载 ngrok
ngrok http 5051
# 得到 https://xxxx.ngrok-free.app
```
把该 URL 给对方，对方 POST `https://xxxx.ngrok-free.app/api/v1/run`。

**方式 B：cpolar / frp 等** 同理，本地隧道映射 5051。

> 生产长期使用建议租一台轻量云服务器，按 `docs/回测引擎HTTP接口文档_v5.md` §2.3 用 `deploy.sh` 或 Docker 部署。

---

## 七、接口文档速览

- **唯一规范**：`docs/回测引擎HTTP接口文档_v5.md`（调用方式、输入输出、错误码、Agent 解析规则、部署）
- **核心端点**：
  - `POST /api/v1/run` 执行回测
  - `GET /api/v1/health` 健康检查
  - `GET /api/v1/meta` 获取合法取值（角色/基准/频率枚举）
  - `GET /api/v1/results/{request_id}/response.json` 下载结果
