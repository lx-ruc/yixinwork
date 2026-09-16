"""技能工具：list_skills / load_skill——把技能指南带进 Agent 上下文。"""

import json

from app.skills import list_skills, load_skill as read_skill
from app.tools.base import ToolRegistry, ToolSpec, ToolError


async def _list_skills(_: dict) -> str:
    metas = list_skills()
    return json.dumps(
        {"skills": [{"name": m.name, "description": m.description} for m in metas]},
        ensure_ascii=False,
    )


async def _load_skill(args: dict) -> str:
    try:
        content = read_skill(str(args["name"]).strip())
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return content


def register_skill_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="list_skills",
            description="列出可用技能（名称与简介）",
            parameters={"type": "object", "properties": {}},
            func=_list_skills,
        )
    )
    registry.register(
        ToolSpec(
            name="load_skill",
            description="加载指定技能的完整指南并遵循其要求执行。先看系统提示里的技能清单",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名，如 slides-design"}},
                "required": ["name"],
            },
            func=_load_skill,
        )
    )
