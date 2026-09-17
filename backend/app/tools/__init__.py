"""工具层入口：全局注册表（启动时装配）。"""

from functools import lru_cache

from app.tools.artifacts import register_artifact_tools
from app.tools.base import ToolError, ToolRegistry, ToolSpec
from app.tools.code import register_code_tools
from app.tools.context import ToolContext, get_tool_context, set_tool_context
from app.tools.search import register_search_tools
from app.tools.skill_tool import register_skill_tools


@lru_cache
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_artifact_tools(registry)
    register_code_tools(registry)
    register_search_tools(registry)
    register_skill_tools(registry)
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
