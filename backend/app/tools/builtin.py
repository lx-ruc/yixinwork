"""内置工具：G5 验证工具循环的最小实现，G6 逐个替换为真实产物工具。"""

from typing import Awaitable, Callable

from app.tools.base import ToolRegistry, ToolSpec

DRAFT_TOOL = "write_document_draft"

# 测试钩子：拦截草稿工具执行（如挂起等待执行中插话入队）；生产恒为 None
DRAFT_HOOK: Callable[[dict], Awaitable[str]] | None = None


async def _write_draft(args: dict) -> str:
    if DRAFT_HOOK is not None:
        return await DRAFT_HOOK(args)
    topic = args["topic"]
    outline = args.get("outline", "")
    draft = f"# {topic}\n\n" + (f"## 提纲\n{outline}\n\n" if outline else "")
    draft += "（占位草稿：G6 将接入真实文档/海报/表格/幻灯片工具）"
    return draft


def register_builtin_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name=DRAFT_TOOL,
            description="按主题与提纲写一份文档草稿（Markdown）",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "文档主题"},
                    "outline": {"type": "string", "description": "可选提纲，换行分隔"},
                },
                "required": ["topic"],
            },
            func=_write_draft,
        )
    )
