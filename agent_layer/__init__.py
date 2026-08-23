"""
AlphaSplit 可替换 Agent 层（独立目录）

本包与 `engine/agentic/`（旧版场景 Mock）分离，专用于 HS300 回测规划与解读。
其他队员替换时：

1. 复制 `agent_layer/impl/` 为 `agent_layer/impl_xxx/` 并实现 `AgentRuntime`
2. 修改 `agent_layer/registry.py` 中 `DEFAULT_IMPL`，或设置环境变量 `AGENT_LAYER_IMPL`
3. 保持 `contracts.py` 中数据结构不变（或同步更新 `engine/integrations/agent_bridge.py`）

引擎侧仅通过 `engine/integrations/agent_bridge.py` 调用，请勿在 engine 其他模块直接 import impl。
"""

from agent_layer.contracts import (
    AgentPipelineResult,
    AgentReport,
    BacktestPlan,
    PlanStep,
)
from agent_layer.registry import create_runtime, get_runtime_class

__all__ = [
    "AgentPipelineResult",
    "AgentReport",
    "BacktestPlan",
    "PlanStep",
    "create_runtime",
    "get_runtime_class",
]
