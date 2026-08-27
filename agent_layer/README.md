# Agent 层（可替换）

本目录为 **独立 Agent 实现**，与 `engine/agentic/` 旧版 Mock 分离。

## 职责

| 组件 | 文件 | 作用 |
|------|------|------|
| 契约 | `contracts.py` | 稳定数据结构，engine 只依赖此层 |
| 注册 | `registry.py` | 切换实现模块 |
| 规划 | `impl/planner.py` | NL / 预设 → query JSON |
| 因子Agent | `impl/factor_agent.py` | 客户偏好 → 受限因子配置建议与审计轨迹 |
| 模型调用 | `impl/llm.py` | DeepSeek兼容调用、有限重试和安全元数据 |
| 证据 | `impl/evidence.py` | 回测结果一致性校验与证据白名单 |
| 解读 | `impl/interpreter.py` | 回测结果 → 业务报告 |
| 编排 | `impl/orchestrator.py` | `AgentRuntime` 入口 |

## 队员替换步骤

```bash
# 方式 A：新目录
cp -r agent_layer/impl agent_layer/impl_zhang
# 编辑 agent_layer/registry.py:
#   DEFAULT_IMPL = "agent_layer.impl_zhang.orchestrator"

# 方式 B：环境变量（不改代码）
export AGENT_LAYER_IMPL=agent_layer.impl_zhang.orchestrator
```

新实现必须提供 `AgentRuntime` 类，并实现：

- `plan_backtest(...) -> BacktestPlan`
- `interpret_backtest(backtest, plan, mode) -> AgentReport`
- `run_pipeline(..., run_backtest=...) -> AgentPipelineResult`

## API（经 bridge 暴露）

- `GET  /api/agent/meta`
- `GET  /api/agent/presets`
- `POST /api/agent/plan`
- `POST /api/agent/interpret`
- `POST /api/agent/pipeline`

## LLM 模式

设置 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`，请求 `mode: "llm"`。
未配置时自动回退规则 Mock，保证大赛可离线演示。

可选可靠性参数：

- `AGENT_LAYER_LLM_TIMEOUT`：单次请求超时，默认60秒，限制5到120秒。
- `AGENT_LAYER_LLM_MAX_RETRIES`：失败后的最大重试次数，默认1，限制0到3。
- `AGENT_LAYER_LLM_RETRY_BACKOFF`：重试退避基数，默认0.25秒，限制0到2秒。

调用审计不保存API Key、完整提示词、完整服务地址或模型原始错误正文。
