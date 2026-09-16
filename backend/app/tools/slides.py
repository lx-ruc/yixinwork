"""幻灯片设计系统:主题令牌 + 四种版式(封面/章节/内容/结尾),双格式渲染。

设计准则取自 pptx 技能(anthropics/skills):
- 三明治结构:封面/结尾深色,内容页浅色;主色主导(60-70% 视觉权重),点缀色克制
- 母题 = 圆形数字徽章(贯穿封面装饰圆、章节巨号、内页卡片序号)
- 禁忌:标题下不加线、无装饰色条、正文左对齐、内容页白底、统一间距节奏
- 溢出防护:bullets > 6 条自动降级为紧凑列表版式
"""

import io
import re
from html import escape

THEMES: dict[str, dict[str, str]] = {
    # dark=封面/结尾底色 primary=主操作色 card=卡片浅底 soft=浅色辅色
    # ink=内页正文色 muted=次要文字 cover_sub=封面副标题色
    "midnight": {"dark": "#1E2761", "primary": "#1E2761", "card": "#EEF3FC",
                 "soft": "#CADCFC", "ink": "#1F2430", "muted": "#6B7699", "cover_sub": "#CADCFC"},
    "teal": {"dark": "#043F47", "primary": "#028090", "card": "#E9F6F5",
             "soft": "#BDE8E6", "ink": "#17313A", "muted": "#5E7F84", "cover_sub": "#A5E3DC"},
    "forest": {"dark": "#1E3E1F", "primary": "#2C5F2D", "card": "#EFF7EA",
               "soft": "#CDE6C4", "ink": "#22331F", "muted": "#6D8266", "cover_sub": "#B9DCA8"},
    "coral": {"dark": "#2F3C7E", "primary": "#E14B52", "card": "#FEF3E2",
              "soft": "#F9E795", "ink": "#33344A", "muted": "#8A7F6E", "cover_sub": "#F9E795"},
    "charcoal": {"dark": "#232E36", "primary": "#36454F", "card": "#F2F4F6",
                 "soft": "#D7DEE3", "ink": "#232E36", "muted": "#77848D", "cover_sub": "#C6D0D8"},
    "berry": {"dark": "#4E1F32", "primary": "#6D2E46", "card": "#F8EFF2",
              "soft": "#E8D5DC", "ink": "#3A2530", "muted": "#8A6F7B", "cover_sub": "#D9B8C6"},
}
DEFAULT_THEME = "midnight"
LAYOUTS = frozenset({"cover", "section", "content", "end"})
LIST_MODE_THRESHOLD = 7  # bullets 超过此数降级为紧凑列表(防溢出)
STAT_RE = re.compile(r"^(\d[\d,.]*\s*(?:%|万|亿|倍|[+×x])?)\s*(.{2,32})$")


def stat_parts(bullet: str) -> tuple[str, str] | None:
    """命中“数值 说明”返回 (数值, 说明)，否则 None；说明剥掉“的”等连接字开头。"""
    m = STAT_RE.match(bullet)
    if not m:
        return None
    num = re.sub(r"\s+([%万亿倍+×x])", r"\1", m.group(1)).strip()  # “8 亿”→“8亿”
    return num, re.sub(r"^[的使得是]", "", m.group(2).strip())


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


# ── HTML 预览(主格式:Web 预览直接渲染) ────────────────────────────────

_CSS = """
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#e8e8ec}}
.slide{{width:960px;height:540px;position:relative;overflow:hidden;page-break-after:always;margin:0 auto 24px}}
.cover,.end{{background:{t[dark]};display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}}
.cover h1{{font-size:52px;color:#fff;letter-spacing:3px;margin-bottom:22px;font-weight:700}}
.cover .sub{{font-size:22px;color:{t[cover_sub]}}}
.deco{{position:absolute;border-radius:50%;background:{t[soft]};opacity:.14}}
.cover .end-title{{font-size:42px}}
.end h1{{font-size:42px;color:#fff;letter-spacing:6px;margin-bottom:18px}}
.end .sub{{font-size:18px;color:{t[cover_sub]};opacity:.85}}
.section{{background:{t[card]};display:flex;align-items:center;padding:0 90px}}
.section .no{{font-size:150px;font-weight:800;color:{t[primary]};opacity:.18;margin-right:34px;line-height:1}}
.section h2{{font-size:38px;color:{t[ink]};font-weight:700}}
.content{{background:#fff;padding:56px 70px 50px;display:flex;flex-direction:column}}
.content h2{{font-size:30px;color:{t[ink]};font-weight:700;margin-bottom:26px}}
.cards{{display:flex;flex-direction:column;gap:14px;flex:1;min-height:0}}
.card{{background:{t[card]};border-radius:14px;padding:14px 22px;display:flex;align-items:center;gap:16px;flex:1;min-height:0}}
.badge{{width:34px;height:34px;border-radius:50%;background:{t[primary]};color:#fff;font-size:15px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.card p{{font-size:19px;color:{t[ink]};line-height:1.5}}
.card .num{{font-size:26px;font-weight:800;color:{t[primary]};margin-right:8px}}
.list{{display:flex;flex-direction:column;justify-content:center;flex:1;gap:10px}}
.list p{{font-size:17px;color:{t[ink]};line-height:1.55;padding-left:16px;position:relative}}
.list p::before{{content:"";position:absolute;left:0;top:.62em;width:7px;height:7px;border-radius:50%;background:{t[primary]}}}
.pageno{{position:absolute;right:34px;bottom:20px;font-size:13px;color:{t[muted]}}}
"""


def _cover_deco() -> str:
    return (
        '<div class="deco" style="width:340px;height:340px;left:-120px;top:-120px"></div>'
        '<div class="deco" style="width:220px;height:220px;right:-70px;bottom:-70px"></div>'
    )


def _slide_html(s: dict, idx: int, total: int, t: dict[str, str]) -> str:
    if s["layout"] == "cover":
        sub = f'<p class="sub">{escape(s["subtitle"])}</p>' if s["subtitle"] else ""
        return f'<div class="slide cover">{_cover_deco()}<h1>{escape(s["title"])}</h1>{sub}</div>'
    if s["layout"] == "end":
        sub = f'<p class="sub">{escape(s["subtitle"])}</p>' if s["subtitle"] else ""
        return f'<div class="slide end"><h1>{escape(s["title"])}</h1>{sub}</div>'
    if s["layout"] == "section":
        return (
            f'<div class="slide section"><span class="no">{s["no"]}</span>'
            f'<h2>{escape(s["title"])}</h2></div>'
        )
    # content
    bullets = s["bullets"]
    if not bullets:
        body = '<div class="list"><p> </p></div>'
    elif len(bullets) > LIST_MODE_THRESHOLD:
        rows = "".join(f"<p>{escape(b)}</p>" for b in bullets)
        body = f'<div class="list">{rows}</div>'
    else:
        cards = []
        for i, b in enumerate(bullets, 1):
            badge = f'<span class="badge">{i}</span>'
            if sp := stat_parts(b):
                cards.append(
                    f'<div class="card">{badge}<span class="num">{escape(sp[0])}</span>'
                    f"<p>{escape(sp[1])}</p></div>"
                )
            else:
                cards.append(f'<div class="card">{badge}<p>{escape(b)}</p></div>')
        body = f'<div class="cards">{"".join(cards)}</div>'
    return (
        f'<div class="slide content"><h2>{escape(s["title"])}</h2>{body}'
        f'<span class="pageno">{idx} / {total}</span></div>'
    )


def build_slides_html(title: str, slides: list[dict], theme: str | None) -> str:
    t = resolve_theme(theme)
    norm = normalize_slides(title, slides)
    body = "".join(_slide_html(s, i, len(norm), t) for i, s in enumerate(norm, 1))
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title><style>{_CSS.format(t=t)}</style></head>"
        f"<body>{body}</body></html>"
    )


# ── 原生 pptx(下载格式:文本可编辑) ──────────────────────────────────

_FONT = "微软雅黑"


def _rgb(hex_color: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hex_color.lstrip("#"))


def _set_run_font(run, size_pt: float, hex_color: str, bold: bool = False) -> None:
    """统一字体(含中日韩 eastAsia 字形,否则 CJK 回退宋体)。"""
    from pptx.oxml.ns import qn
    from pptx.util import Pt

    run.font.name = _FONT
    rPr = run.font._rPr
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", _FONT)
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = _rgb(hex_color)
    return run


def _textbox(slide, x: float, y: float, w: float, h: float):
    """零内边距文本框(与形状对齐的前提),垂直居中。"""
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Inches

    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, 0)
    return tf


def _para(tf, first: bool):
    return tf.paragraphs[0] if first else tf.add_paragraph()


def _shape(slide, kind, x: float, y: float, w: float, h: float, fill: str, radius: float = 0.0):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    sp = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    sp.fill.solid()
    sp.fill.fore_color.rgb = _rgb(fill)
    sp.line.fill.background()
    sp.shadow.inherit = False
    if radius:
        try:
            sp.adjustments[0] = radius
        except (IndexError, ValueError):
            pass
    return sp


def _bg(slide, hex_color: str) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(hex_color)


def build_slides_pptx(title: str, slides: list[dict], theme: str | None) -> bytes:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    t = resolve_theme(theme)
    norm = normalize_slides(title, slides)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]
    total = len(norm)

    for idx, s in enumerate(norm, 1):
        slide = prs.slides.add_slide(blank)
        if s["layout"] == "cover":
            _bg(slide, t["dark"])
            _shape(slide, MSO_SHAPE.OVAL, -1.2, -1.2, 3.4, 3.4, t["soft"])
            _shape(slide, MSO_SHAPE.OVAL, 8.4, 3.9, 2.3, 2.3, t["soft"])
            tf = _textbox(slide, 1.0, 1.9, 8.0, 1.2)
            _set_run_font(_para(tf, True).add_run(), 40, "#FFFFFF", bold=True).text = s["title"]
            if s["subtitle"]:
                tf2 = _textbox(slide, 1.0, 3.15, 8.0, 0.6)
                _set_run_font(_para(tf2, True).add_run(), 16, t["cover_sub"]).text = s["subtitle"]
        elif s["layout"] == "end":
            _bg(slide, t["dark"])
            _shape(slide, MSO_SHAPE.OVAL, 7.9, -1.6, 3.2, 3.2, t["soft"])
            tf = _textbox(slide, 1.0, 2.0, 8.0, 1.0)
            _set_run_font(_para(tf, True).add_run(), 34, "#FFFFFF", bold=True).text = s["title"]
            if s["subtitle"]:
                tf2 = _textbox(slide, 1.0, 3.1, 8.0, 0.6)
                _set_run_font(_para(tf2, True).add_run(), 14, t["cover_sub"]).text = s["subtitle"]
        elif s["layout"] == "section":
            _bg(slide, t["card"])
            tf = _textbox(slide, 6.0, 1.3, 3.4, 2.8)
            _set_run_font(_para(tf, True).add_run(), 96, t["primary"], bold=True).text = s["no"]
            tf2 = _textbox(slide, 0.8, 2.35, 5.6, 0.9)
            _set_run_font(_para(tf2, True).add_run(), 28, t["ink"], bold=True).text = s["title"]
        else:  # content
            _bg(slide, "#FFFFFF")
            tf = _textbox(slide, 0.55, 0.4, 8.9, 0.65)
            _set_run_font(_para(tf, True).add_run(), 24, t["ink"], bold=True).text = s["title"]
            bullets = s["bullets"]
            top, avail = 1.35, 3.8
            if not bullets:
                continue
            if len(bullets) > LIST_MODE_THRESHOLD:  # 紧凑列表版式(防溢出)
                tf = _textbox(slide, 0.85, top, 8.3, avail)
                for i, b in enumerate(bullets):
                    p = _para(tf, i == 0)
                    p.space_after = Pt(8)
                    _set_run_font(p.add_run(), 13, t["ink"]).text = f"· {b}"
            else:
                gap = 0.12
                ch = min(0.86, (avail - gap * (len(bullets) - 1)) / len(bullets))
                for i, b in enumerate(bullets):
                    y = top + i * (ch + gap)
                    _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.55, y, 8.9, ch, t["card"], 0.16)
                    # 序号徽章贯穿所有卡片(视觉母题),数字卡片不例外
                    _shape(slide, MSO_SHAPE.OVAL, 0.85, y + (ch - 0.34) / 2, 0.34, 0.34, t["primary"])
                    tf = _textbox(slide, 0.82, y + (ch - 0.34) / 2, 0.34, 0.34)
                    _set_run_font(_para(tf, True).add_run(), 11, "#FFFFFF", bold=True).text = str(i + 1)
                    tf = _textbox(slide, 1.45, y, 7.7, ch)
                    if sp := stat_parts(b):  # 数值大字 + 说明
                        p = _para(tf, True)
                        _set_run_font(p.add_run(), 17, t["primary"], bold=True).text = sp[0]
                        _set_run_font(p.add_run(), 14, t["ink"]).text = "  " + sp[1]
                    else:
                        _set_run_font(_para(tf, True).add_run(), 14, t["ink"]).text = b
            tfp = _textbox(slide, 8.9, 5.1, 0.7, 0.35)
            _set_run_font(_para(tfp, True).add_run(), 10, t["muted"]).text = f"{idx}/{total}"

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
