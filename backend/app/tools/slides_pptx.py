"""幻灯片原生 pptx 渲染(v2):与 HTML 版式逐页对应的可编辑下载格式。

16:9(10"×5.625"),微软雅黑(含 eastAsia 字形),数字用西文字体区分层级。
"""

import io

from .slides_core import body_mode, normalize_slides, resolve_theme, split_unit, stat_parts

_FONT = "微软雅黑"
_NUM_FONT = "Arial"


def _rgb(hex_color: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hex_color.lstrip("#"))


def _set_run_font(run, size_pt: float, hex_color: str, bold: bool = False, latin: str | None = None) -> None:
    """统一字体(含中日韩 eastAsia 字形,否则 CJK 回退宋体);数字可指定西文字体。"""
    from pptx.oxml.ns import qn
    from pptx.util import Pt

    run.font.name = latin or _FONT
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


def _num_runs(p, num: str, size_pt: float, hex_color: str) -> None:
    """大数字双 run:主数字西文字体,单位缩小到 .62 倍(数字是唯一主角)。"""
    n, u = split_unit(num)
    _set_run_font(p.add_run(), size_pt, hex_color, bold=True, latin=_NUM_FONT).text = n
    if u:
        _set_run_font(p.add_run(), size_pt * 0.62, hex_color, bold=True).text = u


def _textbox(slide, x: float, y: float, w: float, h: float, anchor="mid"):
    """零内边距文本框(与形状对齐的前提)。"""
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Inches

    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if anchor == "mid" else MSO_ANCHOR.TOP
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


def _ring(slide, x: float, y: float, size: float, hex_color: str) -> None:
    """无填充描边圆(封面/结尾同心圆母题)。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(size), Inches(size))
    sp.fill.background()
    sp.line.color.rgb = _rgb(hex_color)
    sp.line.width = Pt(1.5)
    sp.shadow.inherit = False


def _rings(slide, t: dict[str, str]) -> None:
    """同心圆簇:圆心锚在右下角 (10, 5.625)。"""
    _ring(slide, 8.2, 3.825, 3.6, t["soft"])
    _ring(slide, 8.75, 4.375, 2.5, t["soft"])
    _ring(slide, 9.25, 4.875, 1.5, t["soft"])


def _bg(slide, hex_color: str) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(hex_color)


def _hook_chips(slide, s: dict, t: dict[str, str]) -> None:
    """封面数字钩子:前 3 条数据句式 → 圆角 chip(大数字 + 小标签)。"""
    stats = [sp for sp in (stat_parts(b) for b in s["bullets"][:3]) if sp]
    if not stats:
        return
    w, gap, y, h = 2.55, 0.25, 4.05, 1.0
    from pptx.enum.shapes import MSO_SHAPE

    for i, (num, label) in enumerate(stats):
        x = 0.85 + i * (w + gap)
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, t["soft"], 0.14)
        # chip 用 soft 底 + dark 字(半透明白在 pptx 不可靠)
        tf = _textbox(slide, x + 0.2, y + 0.1, w - 0.4, 0.5, anchor="top")
        _num_runs(_para(tf, True), num, 20, t["dark"])
        tf = _textbox(slide, x + 0.2, y + 0.62, w - 0.4, 0.3, anchor="top")
        _set_run_font(_para(tf, True).add_run(), 9.5, t["dark"]).text = label


def _cover(slide, s: dict, t: dict[str, str], title_pt: float = 34, hooks: bool = True) -> None:
    _bg(slide, t["dark"])
    _rings(slide, t)
    tf = _textbox(slide, 0.85, 1.5, 7.4, 1.2)
    _set_run_font(_para(tf, True).add_run(), title_pt, "#FFFFFF", bold=True).text = s["title"]
    if s["subtitle"]:
        tf = _textbox(slide, 0.85, 2.8, 6.4, 0.8, anchor="top")
        _set_run_font(_para(tf, True).add_run(), 13, t["cover_sub"]).text = s["subtitle"]
    if hooks:
        _hook_chips(slide, s, t)


def _end(slide, s: dict, t: dict[str, str]) -> None:
    _cover(slide, s, t, title_pt=30, hooks=False)


def _section(slide, s: dict, t: dict[str, str]) -> None:
    _bg(slide, t["card"])
    tf = _textbox(slide, 0.85, 1.95, 4.0, 0.35)
    _set_run_font(_para(tf, True).add_run(), 12, t["primary"], bold=True).text = f"第 {s['no']} 部分"
    tf = _textbox(slide, 0.85, 2.4, 6.4, 0.9)
    _set_run_font(_para(tf, True).add_run(), 28, t["ink"], bold=True).text = s["title"]
    tf = _textbox(slide, 6.4, 2.7, 3.2, 2.6)
    _set_run_font(_para(tf, True).add_run(), 80, t["primary"], bold=True, latin=_NUM_FONT).text = s["no"]


def _agenda(slide, s: dict, t: dict[str, str]) -> None:
    from pptx.enum.text import PP_ALIGN

    _bg(slide, "#FFFFFF")
    tf = _textbox(slide, 0.6, 0.45, 3.0, 0.3, anchor="top")
    _set_run_font(_para(tf, True).add_run(), 11, t["primary"], bold=True).text = "目录"
    tf = _textbox(slide, 0.6, 0.8, 8.8, 0.6)
    _set_run_font(_para(tf, True).add_run(), 23, t["ink"], bold=True).text = s["title"]
    items = s["bullets"]
    if not items:
        return
    row_h = min(0.62, 3.5 / len(items))
    top = 1.7
    for i, b in enumerate(items):
        y = top + i * row_h
        tf = _textbox(slide, 0.85, y, 0.75, row_h)
        p = _para(tf, True)
        p.alignment = PP_ALIGN.LEFT
        _set_run_font(p.add_run(), 15, t["primary"], bold=True, latin=_NUM_FONT).text = f"{i + 1:02d}"
        tf = _textbox(slide, 1.75, y, 7.3, row_h)
        _set_run_font(_para(tf, True).add_run(), 15, t["ink"]).text = b


def _kpi_grid(slide, bullets: list[str], t: dict[str, str], top: float, avail: float) -> None:
    from pptx.enum.shapes import MSO_SHAPE

    stats = [sp for sp in (stat_parts(b) for b in bullets) if sp]
    n = len(stats)
    cols = 3 if n == 3 else 2
    rows = (n + cols - 1) // cols
    gap = 0.16
    w = (8.8 - gap * (cols - 1)) / cols
    h = (avail - gap * (rows - 1)) / rows
    for i, (num, label) in enumerate(stats):
        r, c = divmod(i, cols)
        x, y = 0.6 + c * (w + gap), top + r * (h + gap)
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, t["card"], 0.1)
        tf = _textbox(slide, x + 0.3, y + h * 0.14, w - 0.6, h * 0.48, anchor="top")
        _num_runs(_para(tf, True), num, 34, t["primary"])  # 数字即锚点:34pt 主数字
        tf = _textbox(slide, x + 0.3, y + h * 0.64, w - 0.6, h * 0.3, anchor="top")
        _set_run_font(_para(tf, True).add_run(), 12, t["ink"]).text = label


def _grid2(slide, bullets: list[str], t: dict[str, str], top: float, avail: float) -> None:
    from pptx.enum.shapes import MSO_SHAPE

    gap = 0.16
    w = (8.8 - gap) / 2
    h = (avail - gap) / 2
    for i, b in enumerate(bullets[:4]):
        r, c = divmod(i, 2)
        x, y = 0.6 + c * (w + gap), top + r * (h + gap)
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, t["card"], 0.1)
        _shape(slide, MSO_SHAPE.OVAL, x + 0.32, y + (h - 0.34) / 2, 0.34, 0.34, t["primary"])
        tf = _textbox(slide, x + 0.29, y + (h - 0.34) / 2, 0.34, 0.34)
        _set_run_font(_para(tf, True).add_run(), 11, "#FFFFFF", bold=True, latin=_NUM_FONT).text = str(i + 1)
        tf = _textbox(slide, x + 0.9, y, w - 1.2, h)
        _set_run_font(_para(tf, True).add_run(), 13.5, t["ink"]).text = b


def _stacked_cards(slide, bullets: list[str], t: dict[str, str], top: float, avail: float) -> None:
    from pptx.enum.shapes import MSO_SHAPE

    gap = 0.12
    ch = min(0.86, (avail - gap * (len(bullets) - 1)) / len(bullets))
    for i, b in enumerate(bullets):
        y = top + i * (ch + gap)
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.6, y, 8.8, ch, t["card"], 0.16)
        _shape(slide, MSO_SHAPE.OVAL, 0.9, y + (ch - 0.34) / 2, 0.34, 0.34, t["primary"])
        tf = _textbox(slide, 0.87, y + (ch - 0.34) / 2, 0.34, 0.34)
        _set_run_font(_para(tf, True).add_run(), 11, "#FFFFFF", bold=True, latin=_NUM_FONT).text = str(i + 1)
        tf = _textbox(slide, 1.5, y, 7.6, ch)
        if sp := stat_parts(b):
            p = _para(tf, True)
            _num_runs(p, sp[0], 17, t["primary"])
            _set_run_font(p.add_run(), 14, t["ink"]).text = "  " + sp[1]
        else:
            _set_run_font(_para(tf, True).add_run(), 14, t["ink"]).text = b


def _content(slide, s: dict, t: dict[str, str], idx: int, total: int) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Pt

    _bg(slide, "#FFFFFF")
    top = 0.5
    if s["subtitle"]:  # 眉题(章节归属,技能指导 LLM 填写)
        tf = _textbox(slide, 0.6, top, 8.8, 0.3, anchor="top")
        _set_run_font(_para(tf, True).add_run(), 11, t["primary"], bold=True).text = s["subtitle"]
        top += 0.36
    tf = _textbox(slide, 0.6, top, 8.8, 0.62)
    _set_run_font(_para(tf, True).add_run(), 23, t["ink"], bold=True).text = s["title"]
    body_top, avail = top + 0.75, 5.0 - (top + 0.75)
    bullets = s["bullets"]
    mode = body_mode(bullets)
    if not bullets:
        pass
    elif mode == "list":
        tf = _textbox(slide, 0.9, body_top, 8.3, avail, anchor="top")
        for i, b in enumerate(bullets):
            p = _para(tf, i == 0)
            p.space_after = Pt(8)
            _set_run_font(p.add_run(), 13, t["ink"]).text = f"· {b}"
    elif mode == "kpis":
        _kpi_grid(slide, bullets, t, body_top, avail)
    elif mode == "grid2":
        _grid2(slide, bullets, t, body_top, avail)
    else:
        _stacked_cards(slide, bullets, t, body_top, avail)
    _shape(slide, MSO_SHAPE.OVAL, 9.35, 5.32, 0.05, 0.05, t["primary"])  # 页码锚点
    tf = _textbox(slide, 8.7, 5.15, 0.7, 0.32)
    from pptx.enum.text import PP_ALIGN

    p = _para(tf, True)
    p.alignment = PP_ALIGN.RIGHT
    _set_run_font(p.add_run(), 10, t["muted"]).text = f"{idx}/{total}"


def build_slides_pptx(title: str, slides: list[dict], theme: str | None) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    t = resolve_theme(theme)
    norm = normalize_slides(title, slides)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]
    total = len(norm)

    for idx, s in enumerate(norm, 1):
        slide = prs.slides.add_slide(blank)
        if s["layout"] == "cover":
            _cover(slide, s, t)
        elif s["layout"] == "end":
            _end(slide, s, t)
        elif s["layout"] == "section":
            _section(slide, s, t)
        elif s["layout"] == "agenda":
            _agenda(slide, s, t)
        else:
            _content(slide, s, t, idx, total)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
