# AlphaSplit 架构与叙述对齐（v0.4）

## 叙述主线

痛点（固定比例考不明贡献）  
→ 经典归因可自定义维度  
→ 维度延伸到组织角色  
→ Shapley + Agent 反事实/控制变量回测  
→ 贡献系数作考评锚点（双轨试点 + 人工确认）

## 方法分层

1. 资产层：Brinson / 多因子 / CT&CS  
2. 角色层：角色—归因项映射 + Shapley 贡献系数  
3. 考评层：协商锚点 + 人工确认；增量池可按新权重试点（建议 6:4）

## 工程主链路（与代码）

```
先验公式 / 场景参数
  → Agent 规划回测方案
  → core/backtest（切片回测与归因估计）
  → 贡献权重 / Impact 锚点
  → 协商带宽 + 人工确认
  → 可视化输出
```

| 模块 | 职责 |
|------|------|
| `core/backtest.py` | 回测切片与归因估计 |
| `agentic/attribution_agent.py` | 规划、解读、映射权重 |
| `core/settlement.py` | 锚点带宽 + 人工确认 |
| `agentic/negotiation.py` | Mock/LLM 协商 |
| `core/sensitivity.py` | 权重敏感性 / 回平衡演示 |

## API（现状）

| 路由 | 功能 |
|------|------|
| `POST /api/attribution` | Agent 规划回测归因 |
| `POST /api/negotiate` | 协商建议案 |
| `POST /api/confirm` | 人工确认 |
| `POST /api/rebalance` | 目标→回平衡轨迹 |
| `POST /api/sensitivity` | 权重扫描 |
| `POST /api/evolution` | 对照演化 |

## 边界

合成/套壳数据用于机制验证；贡献系数为估计而非精确因果；落账需人工确认。
