"""工具层入口：全局注册表（启动时装配）。"""

from functools import lru_cache

from app.tools.base import ToolError, ToolRegistry, ToolSpec
from app.tools.builtin import register_builtin_tools


@lru_cache
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


__all__ = ["ToolError", "ToolRegistry", "ToolSpec", "get_tool_registry"]
