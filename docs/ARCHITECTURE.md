# AlphaSplit 架构摘要（v0.5）

**AlphaSplit：多智能体驱动的投研协作激励与贡献计量平台**

AlphaSplit 以更合理的分配机制为手段，用可解释贡献证据调动投研各角色参与积极性，促进组织协同与决策质量提升，并以长期投资回报改善为目标。历史回测用于形成证据，不构成收益承诺。

## 主线

角色—因子映射 → Agent 规划反事实/对照回测 → 贡献系数 → 6:4合成建议 → 角色陈述参考 → 评审委员会决策

## 双轨分配（6:4）

落地设计（详见 [`双轨分配机制.md`](双轨分配机制.md)）：

```text
最终份额 = 60% × 机构现行分配 + 40% × 夏普利新池建议
```

- **回测层**（`query_engine`）：只算新池 40% 内各角色权重  
- **决策层**（`engine/web`）：展示旧池 / 新池 / 合成建议与角色参考意见，由评审委员会（或机构治理责任人）独立调整、确认后形成可应用方案
- 角色 Agent 只陈述贡献意见，不参与建议份额计算或最终裁决；系统只提供决策支持，不自动执行分配

## 分层

1. 信号层：公开数据与因子库（决策输入的可计算代理）  
2. 计量层：`v(S)=R(S)-R_HS300`、`v(∅)=0`，精确 Shapley 对齐全组合超额收益
3. 智能层：规划—执行—评估—重试；本地 Mock  
4. 输出层：贡献系数与解释

## 模块（代码）

| 模块 | 职责 |
|------|------|
| `engine/core/backtest.py` | 合成回测切片与三因素归因（Mock 演示） |
| `backtest/query_engine.py` | HS300 多角色回测 + Shapley 归因（真实数据） |
| `engine/integrations/quantskills_backtest.py` | FastAPI 与回测引擎桥接 |
| `agent_layer/` | **可替换** HS300 Agent（规划 / 解读），见 `agent_layer/README.md` |
| `engine/integrations/agent_bridge.py` | Agent 层唯一桥接入口 |
| `engine/agentic/attribution_agent.py` | 附录：三因素合成归因 Mock |
| `engine/core/settlement.py` | 锚点与确认辅助 |
| `engine/agentic/role_negotiation.py` | 角色贡献陈述与评审决策支持 |

参赛技术文档完整目录见 `技术文档目录.md`。
