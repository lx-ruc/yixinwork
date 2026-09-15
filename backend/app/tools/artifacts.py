"""产物工具：文档 / 海报 / 表格 / 幻灯片。

中间格式策略（决策 5/C）：文档=Markdown、海报与幻灯片=HTML、表格=xlsx+HTML 预览。
下载转换（md→docx、HTML→png、slides→pptx）在工具侧同步产出一次，
预览与签名 URL 下载由 G8 产物生命周期承接。
"""

import asyncio
import json
import re
from html import escape

from app.storage.base import artifact_key
from app.tools.base import ToolRegistry, ToolSpec, ToolError
from app.tools.context import get_tool_context

MAX_CONTENT_BYTES = 200_000  # 单产物内容上限（防滥用）


def _save(filename: str, content: str | bytes) -> str:
    """按 {user}/{task}/v{n}/{filename} 落盘，返回存储 key。"""
    ctx = get_tool_context()
    key = artifact_key(ctx.user_id, ctx.task_id, ctx.next_version(), filename)
    data = content.encode("utf-8") if isinstance(content, str) else content
    if len(data) > MAX_CONTENT_BYTES:
        raise ToolError(f"内容超出上限（{len(data)} > {MAX_CONTENT_BYTES} 字节）")
    ctx.storage.save(key, data)
    return key


async def _save_document(args: dict) -> str:
    title = args["title"].strip()
    content = args["content_md"].strip()
    if not content:
        raise ToolError("文档内容为空")
    key = _save("document.md", f"# {title}\n\n{content}\n")
    try:
        docx_key = _save_docx(title, content)
        extra = f"；docx={docx_key}"
    except Exception:  # 转换失败不阻塞预览（md 为主格式）
        extra = ""
    return json.dumps({"saved": [{"kind": "document", "key": key}], "note": f"文档《{title}》已保存{extra}"}, ensure_ascii=False)


def _save_docx(title: str, markdown: str) -> str:
    from docx import Document

    doc = Document()
    doc.add_heading(title, level=0)
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            continue
        if m := re.match(r"^#{1,4}\s+(.*)", text):
            doc.add_heading(m.group(1), level=min(len(text) - len(text.lstrip("#")), 4))
        elif re.match(r"^[-*]\s+", text):
            doc.add_paragraph(re.sub(r"^[-*]\s+", "", text), style="List Bullet")
        else:
            doc.add_paragraph(text)
    import io

    buf = io.BytesIO()
    doc.save(buf)
    return _save("document.docx", buf.getvalue())


POSTER_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 750px; height: 1060px; font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
       background: {bg}; color: {fg}; display: flex; flex-direction: column;
       align-items: center; justify-content: center; text-align: center; padding: 60px; }}
h1 {{ font-size: 64px; margin-bottom: 28px; letter-spacing: 4px; }}
.slogan {{ font-size: 28px; opacity: .9; margin-bottom: 18px; }}
.footer {{ font-size: 18px; opacity: .7; margin-top: 48px; }}
</style></head>
<body>
<h1>{title}</h1>
<p class="slogan">{slogan}</p>
<p class="footer">{footer}</p>
</body></html>
"""


async def _save_poster(args: dict) -> str:
    title = args["title"].strip()
    html = POSTER_HTML_TEMPLATE.format(
        title=escape(title),
        slogan=escape(args.get("slogan", "")),
        footer=escape(args.get("footer", "")),
        bg=args.get("bg_color", "#1f2d3d"),
        fg=args.get("fg_color", "#ffffff"),
    )
    key = _save("poster.html", html)
    png_note = ""
    try:
        png_key = await asyncio.to_thread(_render_png, key, "poster.png")
        png_note = f"；png={png_key}"
    except Exception as exc:  # 渲染器缺失/失败不阻塞，HTML 预览兜底
        png_note = f"；png渲染跳过（{type(exc).__name__}）"
    return json.dumps({"saved": [{"kind": "poster", "key": key}], "note": f"海报《{title}》已保存{png_note}"}, ensure_ascii=False)


def _render_png(html_key: str, filename: str, width: int = 750, height: int = 1060) -> str:
    """playwright 截图（同步 API 放线程执行；无浏览器时抛错由调用方降级）。"""
    from playwright.sync_api import sync_playwright

    ctx = get_tool_context()
    html = ctx.storage.read_text(html_key)
    version_dir = html_key.rsplit("/", 1)[0]
    png_key = f"{version_dir}/{filename}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html)
            png = page.screenshot(full_page=False)
        finally:
            browser.close()
    ctx.storage.save(png_key, png)
    return png_key


async def _save_table(args: dict) -> str:
    import io

    from openpyxl import Workbook

    title = args["title"].strip()
    headers = args["headers"]
    rows = args["rows"]
    if not headers or any(len(r) != len(headers) for r in rows):
        raise ToolError("表格每行列数必须与表头一致")

    wb = Workbook()
    ws = wb.active
    # openpyxl 工作表名禁用 /\*?:[] 等字符，统一清洗
    ws.title = re.sub(r"[\\/*?:\[\]]", "-", title)[:31] or "Sheet"
    ws.append(headers)
    for r in rows:
        ws.append([str(c) for c in r])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_key = _save("table.xlsx", buf.getvalue())

    # HTML 预览数据（G8 预览接口直接可用）
    thead = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in rows
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        "table{border-collapse:collapse;font:14px sans-serif}th,td{border:1px solid #ccc;"
        "padding:6px 14px}th{background:#f5f7fa}</style></head>"
        f"<body><h3>{escape(title)}</h3><table><thead><tr>{thead}</tr></thead>"
        f"<tbody>{tbody}</tbody></table></body></html>"
    )
    html_key = _save("table_preview.html", html)
    return json.dumps(
        {"saved": [{"kind": "table", "key": xlsx_key}, {"kind": "table_preview", "key": html_key}],
         "note": f"表格《{title}》已保存（{len(rows)} 行）"},
        ensure_ascii=False,
    )


SLIDE_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#202124;color:#f5f5f5}}
.slide{{width:960px;height:540px;padding:70px 80px;display:flex;flex-direction:column;
        justify-content:center;page-break-after:always;border-bottom:1px solid #3c4043}}
.slide h2{{font-size:40px;margin-bottom:30px}}
.slide li{{font-size:24px;line-height:1.8;margin-left:34px}}
</style></head><body>
{slides}
</body></html>
"""


async def _save_slides(args: dict) -> str:
    title = args["title"].strip()
    slides = args["slides"]
    if not slides:
        raise ToolError("至少需要一页幻灯片")

    parts = []
    for s in slides:
        items = "".join(f"<li>{escape(str(b))}</li>" for b in s.get("bullets", []))
        parts.append(f"<div class='slide'><h2>{escape(s['title'])}</h2><ul>{items}</ul></div>")
    html_key = _save(
        "slides.html", SLIDE_HTML_TEMPLATE.format(title=escape(title), slides="".join(parts))
    )

    pptx_key = ""
    try:
        pptx_key = _save_pptx(title, slides)
    except Exception:
        pass  # pptx 转换为尽力而为；HTML 预览为主格式（保真度降级路径）
    note = f"幻灯片《{title}》（{len(slides)} 页）已保存"
    if pptx_key:
        note += f"；pptx={pptx_key}"
    return json.dumps({"saved": [{"kind": "slides", "key": html_key}], "note": note}, ensure_ascii=False)


def _save_pptx(title: str, slides: list[dict]) -> str:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    prs.slide_width = 9144000  # 16:9
    prs.slide_height = 5143500
    blank = prs.slide_layouts[6]
    for s in slides:
        slide = prs.slides.add_slide(blank)
        tb = slide.shapes.add_textbox(457200, 457200, 8229600, 4226560)
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = s["title"]
        p.font.size = Pt(32)
        for b in s.get("bullets", []):
            bp = tf.add_paragraph()
            bp.text = f"• {b}"
            bp.font.size = Pt(20)
    import io

    buf = io.BytesIO()
    prs.save(buf)
    return _save("slides.pptx", buf.getvalue())


def register_artifact_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="save_document",
            description="保存/更新文档产物（Markdown）。content_md 为正文（不含大标题）",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content_md": {"type": "string"},
                },
                "required": ["title", "content_md"],
            },
            func=_save_document,
        )
    )
    registry.register(
        ToolSpec(
            name="save_poster",
            description="保存海报产物（HTML 模板渲染，自动转 png）",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "slogan": {"type": "string"},
                    "footer": {"type": "string"},
                    "bg_color": {"type": "string"},
                    "fg_color": {"type": "string"},
                },
                "required": ["title"],
            },
            func=_save_poster,
        )
    )
    registry.register(
        ToolSpec(
            name="save_table",
            description="保存表格产物（xlsx + HTML 预览）。rows 每行列数与 headers 一致",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "headers": {"type": "array", "items": {"type": "string"}},
                    "rows": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                    },
                },
                "required": ["title", "headers", "rows"],
            },
            func=_save_table,
        )
    )
    registry.register(
        ToolSpec(
            name="save_slides",
            description="保存幻灯片产物（HTML 预览 + pptx）。slides 每页 {title, bullets[]}",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["title", "slides"],
            },
            func=_save_slides,
        )
    )
