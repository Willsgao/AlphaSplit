"""
实现注册表 —— 队员替换 Agent 时通常只改 IMPLEMENTATION 指向的模块。

默认：agent_layer.impl.orchestrator.AgentRuntime
替换示例：agent_layer.impl_custom.orchestrator.AgentRuntime
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# 队员替换实现时修改此常量即可（或设置环境变量 AGENT_LAYER_IMPL）
DEFAULT_IMPL = "agent_layer.impl.orchestrator"

if TYPE_CHECKING:
    from agent_layer.contracts import AgentRuntimeProtocol


def get_runtime_class():
    import os

    module_path = os.environ.get("AGENT_LAYER_IMPL", DEFAULT_IMPL)
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "AgentRuntime"):
        raise ImportError(f"{module_path} 缺少 AgentRuntime 类")
    return mod.AgentRuntime


def create_runtime(**kwargs):
    cls = get_runtime_class()
    return cls(**kwargs)
