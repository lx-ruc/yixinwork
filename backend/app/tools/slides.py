"""幻灯片设计系统门面:核心令牌/归一 + HTML 预览 + pptx 下载三种能力。

实现拆分(小文件原则):
- slides_core:主题、版式归一、数据句式解析、正文版式决策
- slides_html:Web 预览(信息设计版式)
- slides_pptx:可编辑下载格式(与 HTML 逐页对应)
"""

from .slides_core import (
    DEFAULT_THEME,
    LAYOUTS,
    THEMES,
    body_mode,
    normalize_slides,
    resolve_theme,
    resolve_theme_name,
    split_unit,
    stat_parts,
)
from .slides_html import build_slides_html
from .slides_pptx import build_slides_pptx

__all__ = [
    "DEFAULT_THEME",
    "LAYOUTS",
    "THEMES",
    "body_mode",
    "build_slides_html",
    "build_slides_pptx",
    "normalize_slides",
    "resolve_theme",
    "resolve_theme_name",
    "split_unit",
    "stat_parts",
]
