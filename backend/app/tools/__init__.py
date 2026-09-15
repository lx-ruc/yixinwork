"""工具层入口：全局注册表（启动时装配）。"""

from functools import lru_cache

from app.tools.artifacts import register_artifact_tools
from app.tools.base import ToolError, ToolRegistry, ToolSpec
from app.tools.context import ToolContext, get_tool_context, set_tool_context


@lru_cache
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_artifact_tools(registry)
    return registry


__all__ = [
    "EXECUTE_HOOK",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolSpec",
    "get_tool_context",
    "get_tool_registry",
    "set_tool_context",
]
