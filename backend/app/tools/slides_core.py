"""幻灯片设计系统核心:主题令牌、版式归一、数据句式解析。

设计准则(v2,信息设计优先):
- 三明治结构:封面/结尾深色,内容页浅色
- 封面左对齐 + 数字钩子(bullets 渲染为大数字 chip)
- 数据页自动 KPI 网格:全部要点命中"数值 说明"句式时,
  数字放大为视觉锚点,不再叠加序号徽章
- 版式:cover / agenda(目录) / section / content / end
"""

import re

THEMES: dict[str, dict[str, str]] = {
    # dark=封面/结尾底色 primary=主操作色 card=卡片浅底 soft=浅色辅色
    # ink=内页正文色 muted=次要文字 cover_sub=封面副标题色
    "midnight": {"dark": "#1B2452", "primary": "#27357E", "card": "#EEF2FB",
                 "soft": "#C7D4F5", "ink": "#1F2430", "muted": "#6B7699", "cover_sub": "#C9D6F7"},
    "teal": {"dark": "#06343B", "primary": "#0E7C8A", "card": "#E8F5F4",
             "soft": "#B5E3E0", "ink": "#17313A", "muted": "#5E7F84", "cover_sub": "#A5E3DC"},
    "forest": {"dark": "#1E3A1F", "primary": "#2F6230", "card": "#EFF6EA",
               "soft": "#CBE3C2", "ink": "#22331F", "muted": "#6D8266", "cover_sub": "#BCDCAE"},
    "coral": {"dark": "#322D55", "primary": "#D94F57", "card": "#FDF2E7",
              "soft": "#F6DFA8", "ink": "#33344A", "muted": "#8A7F6E", "cover_sub": "#F3E3B8"},
    "charcoal": {"dark": "#232B31", "primary": "#3A4A55", "card": "#F2F4F6",
                 "soft": "#D7DEE3", "ink": "#232E36", "muted": "#77848D", "cover_sub": "#C6D0D8"},
    "berry": {"dark": "#471D2E", "primary": "#7A3350", "card": "#F9F0F3",
              "soft": "#E6D2DB", "ink": "#3A2530", "muted": "#8A6F7B", "cover_sub": "#DCBCCB"},
}
DEFAULT_THEME = "midnight"
LAYOUTS = frozenset({"cover", "agenda", "section", "content", "end"})
LIST_MODE_THRESHOLD = 7  # bullets 超过此数降级为紧凑列表(防溢出)
# 单位集合:百分比/量级/常见量词,保证“120家”“28元”“22杯”整体作为大数字
_STAT_UNITS = r"%万亿倍kKwWxX+×家个店杯人城元年"
STAT_RE = re.compile(rf"^(\d[\d,.]*\s*(?:[{_STAT_UNITS}]|㎡)?)\s*(.{{2,32}})$")


def stat_parts(bullet: str) -> tuple[str, str] | None:
    """命中“数值 说明”返回 (数值, 说明)，否则 None；说明剥掉“的”等连接字开头。"""
    m = STAT_RE.match(bullet)
    if not m:
        return None
    num = re.sub(rf"\s+([{_STAT_UNITS}]|㎡)", r"\1", m.group(1)).strip()  # “8 亿”→“8亿”
    return num, re.sub(r"^[的使得是]", "", m.group(2).strip())


def split_unit(num: str) -> tuple[str, str]:
    """把大数字拆成 (主数字, 单位),如“1,500亿”→(“1,500”,“亿”)。

    单位以小一号字重渲染,让数字本身成为视觉主角。
    """
    m = re.match(r"^(\d[\d,.]*)\s*(.*)$", num)
    if m and m.group(2):
        return m.group(1), m.group(2)
    return num, ""


def resolve_theme(name: str | None) -> dict[str, str]:
    """未知主题名兜底为默认主题(LLM 传脏值不应毁掉整次保存)。"""
    return THEMES[resolve_theme_name(name)]


def resolve_theme_name(name: str | None) -> str:
    """主题名归一(非法/未知 → 默认主题名)。"""
    key = (name or "").strip()
    return key if key in THEMES else DEFAULT_THEME


def normalize_slides(title: str, slides: list[dict]) -> list[dict]:
    """校验/补全:layout 归一、自动三明治(首封尾结)、章节编号。

    返回新列表,不改入参(不可变约定)。
    """
    out: list[dict] = []
    for s in slides:
        layout = str(s.get("layout") or "content").strip()
        if layout not in LAYOUTS:
            layout = "content"
        out.append({
            "layout": layout,
            "title": str(s.get("title") or "").strip() or " ",
            "subtitle": str(s.get("subtitle") or "").strip(),
            "bullets": [str(b) for b in (s.get("bullets") or [])],
        })
    if not out or out[0]["layout"] != "cover":
        out = [{"layout": "cover", "title": title, "subtitle": "", "bullets": []}, *out]
    if out[-1]["layout"] != "end":
        out = [*out, {"layout": "end", "title": "谢谢观看", "subtitle": title, "bullets": []}]
    section_no = 0
    numbered: list[dict] = []
    for s in out:
        item = dict(s)
        if s["layout"] == "section":
            section_no += 1
            item["no"] = f"{section_no:02d}"
        numbered.append(item)
    return numbered


def body_mode(bullets: list[str]) -> str:
    """内容页正文版式选择:kpis / grid2 / cards / list。

    - 全部要点为数据句式且 2-4 条 → kpis(数字放大网格,无徽章)
    - ≥4 条且数据占比 < 1/2 → grid2(两列卡片,填满横向空间)
    - 其余 → cards(纵向卡片,序号徽章 + 可选行内大数字)
    - 超过 LIST_MODE_THRESHOLD 条 → list(紧凑列表防溢出)
    """
    if not bullets:
        return "cards"
    if len(bullets) > LIST_MODE_THRESHOLD:
        return "list"
    stats = sum(1 for b in bullets if stat_parts(b))
    if stats == len(bullets) and 2 <= len(bullets) <= 4:
        return "kpis"
    if len(bullets) >= 4 and stats * 2 < len(bullets):
        return "grid2"
    return "cards"
