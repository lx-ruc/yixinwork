"""工具执行上下文：产物工具落盘所需的 user/task/版本信息。

经 ContextVar 注入（TaskRunner 在启动/恢复执行流前设置），
工具函数保持无状态签名（只收 args），注册表全局只读。
"""

from contextvars import ContextVar
from dataclasses import dataclass

from app.storage.base import StorageService


@dataclass
class ToolContext:
    user_id: str
    task_id: str
    storage: StorageService
    # 该任务执行流内的产物保存序号（v1 起；G8 落库版本链）
    _version: int = 0

    def next_version(self) -> int:
        self._version += 1
        return self._version


_context: ContextVar[ToolContext | None] = ContextVar("tool_context", default=None)


def set_tool_context(ctx: ToolContext) -> None:
    _context.set(ctx)


def clear_tool_context() -> None:
    """清除注入（测试收尾用；生产 runner 每次执行流前都会重新 set）。"""
    _context.set(None)


def get_tool_context() -> ToolContext:
    ctx = _context.get()
    if ctx is None:
        raise RuntimeError("工具执行上下文未设置（应在 TaskRunner 执行流内）")
    return ctx
