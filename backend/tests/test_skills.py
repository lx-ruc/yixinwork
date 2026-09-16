"""技能系统单测：目录加载、提示注入、load_skill 工具与防穿越。"""

import json

import pytest

from app.skills import list_skills, load_skill, skills_hint
from app.tools.base import ToolError, ToolRegistry
from app.tools.skill_tool import register_skill_tools


def test_list_skills_finds_installed_skill():
    metas = {m.name for m in list_skills()}
    assert "slides-design" in metas
    meta = next(m for m in list_skills() if m.name == "slides-design")
    assert "幻灯片" in meta.description or "PPT" in meta.description


def test_skills_hint_lists_names_and_mentions_loader():
    hint = skills_hint()
    assert "slides-design" in hint
    assert "load_skill" in hint


def test_load_skill_returns_guidance_mapping_to_tool_params():
    content = load_skill("slides-design")
    assert "save_slides" in content and "theme" in content


def test_load_skill_rejects_bad_names():
    for bad in ("", "../skills", "no/such", "SLIDES", ".hidden", "不存在"):
        with pytest.raises(ValueError):
            load_skill(bad)


async def test_skill_tools_roundtrip():
    registry = ToolRegistry()
    register_skill_tools(registry)
    listed = json.loads(await registry.execute("list_skills", {}))
    assert any(s["name"] == "slides-design" for s in listed["skills"])
    content = await registry.execute("load_skill", {"name": "slides-design"})
    assert "save_slides" in content
    with pytest.raises(ToolError, match="技能不存在"):
        await registry.execute("load_skill", {"name": "ghost"})
