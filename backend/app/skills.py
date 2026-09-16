"""运行时技能系统：backend/skills/<name>/SKILL.md 即一份技能。

约定与 Claude Code 技能一致：目录名 = 技能名，SKILL.md 头部 frontmatter
带 name/description。系统提示只注入名称与描述（省 token），全文按需经
load_skill 工具加载。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path


def _skills_root() -> Path:
    root = Path(get_settings().skills_dir)
    return root if root.is_absolute() else Path.cwd() / root


def _parse_frontmatter(text: str) -> dict[str, str]:
    """极简 frontmatter 解析（只取 key: value 行，不引依赖）。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else ""
    out: dict[str, str] = {}
    for line in block.splitlines():
        if m := re.match(r"^([a-zA-Z_]+):\s*(.+)$", line.strip()):
            out[m.group(1).lower()] = m.group(2).strip().strip('"').strip("'")
    return out


def list_skills() -> list[SkillMeta]:
    """列出全部可用技能（目录名即技能名；无 SKILL.md 的目录忽略）。"""
    root = _skills_root()
    if not root.is_dir():
        return []
    metas: list[SkillMeta] = []
    for d in sorted(root.iterdir()):
        skill_md = d / "SKILL.md"
        if not (d.is_dir() and skill_md.is_file()):
            continue
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        metas.append(
            SkillMeta(
                name=d.name,
                description=meta.get("description", ""),
                path=skill_md,
            )
        )
    return metas


def skills_hint() -> str:
    """拼进系统提示的技能清单（无技能时返回空串）。"""
    metas = list_skills()
    if not metas:
        return ""
    lines = [f"- {m.name}：{m.description}" for m in metas]
    return (
        "可用技能（完成任务前，若有匹配的先调用 load_skill 加载并遵循其指南）：\n"
        + "\n".join(lines)
    )


def load_skill(name: str) -> str:
    """按名加载技能全文；名字不合法或不存在时抛 ValueError。"""
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"技能名不合法：{name!r}")
    path = _skills_root() / name / "SKILL.md"
    if not path.is_file():
        raise ValueError(f"技能不存在：{name}（可先用 list_skills 查看）")
    return path.read_text(encoding="utf-8")
