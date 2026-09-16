"""幻灯片 HTML 预览渲染(v2):信息设计优先的版式。

- 封面/结尾:左对齐排版,数字钩子 chip,同心圆母题
- 数据页:KPI 网格(数字放大)/ 两列卡片 / 纵向卡片 / 紧凑列表
- 目录页:双栏编号列表
"""

from datetime import date
from html import escape

from .slides_core import body_mode, normalize_slides, resolve_theme, split_unit, stat_parts

_NUM_FONT = '"Helvetica Neue",Arial,"PingFang SC",sans-serif'


def _num_html(num: str) -> str:
    """大数字 = 主数字 + 小号单位(“1,500亿”→ 1,500 大 / 亿 小),数字是唯一主角。"""
    n, u = split_unit(num)
    unit = f'<span class="u">{escape(u)}</span>' if u else ""
    return f"{escape(n)}{unit}"

_CSS = """
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#e8e8ec}}
.slide{{width:960px;height:540px;position:relative;overflow:hidden;page-break-after:always;margin:0 auto 24px}}

/* ── 封面/结尾:深色左对齐 ─────────────────────────────── */
.cover,.end{{background:{t[dark]};padding:0 84px;display:flex;flex-direction:column;justify-content:center}}
.cover h1{{font-size:48px;color:#fff;font-weight:800;line-height:1.28;margin-bottom:20px;max-width:660px}}
.cover .sub,.end .sub{{font-size:19px;color:{t[cover_sub]};opacity:.95;line-height:1.7;max-width:560px}}
.hooks{{display:flex;gap:16px;margin-top:36px}}
.hook{{background:{t[soft]};border-radius:14px;padding:16px 22px;min-width:168px;box-shadow:0 6px 18px rgba(0,0,0,.18)}}
.hook .n{{font-family:{nf};font-size:32px;font-weight:800;color:{t[dark]};line-height:1.1}}
.hook .l{{font-size:13px;color:{t[dark]};opacity:.78;margin-top:8px}}
.n .u,.num .u{{font-size:.52em;font-weight:700;margin-left:2px}}
.meta{{position:absolute;left:84px;bottom:36px;font-size:13px;color:{t[cover_sub]};opacity:.7;letter-spacing:1px}}
.end h1{{font-size:40px;color:#fff;font-weight:800;letter-spacing:2px;margin-bottom:16px}}
.ring{{position:absolute;border-radius:50%;border:2px solid {t[soft]}}}

/* ── 章节:浅底巨号 ───────────────────────────────────── */
.section{{background:{t[card]};display:flex;flex-direction:column;justify-content:center;padding:0 90px}}
.section .kick{{font-size:14px;font-weight:700;color:{t[primary]};letter-spacing:4px;margin-bottom:14px}}
.section h2{{font-size:38px;color:{t[ink]};font-weight:800}}
.section .no{{position:absolute;right:70px;bottom:6px;font-family:{nf};font-size:190px;font-weight:800;color:{t[primary]};opacity:.13;line-height:1}}

/* ── 内容页:眉题 + 标题 + 正文 ────────────────────────── */
.content{{background:#fff;padding:46px 64px 44px;display:flex;flex-direction:column}}
.kicker{{font-size:13px;font-weight:700;color:{t[primary]};letter-spacing:3px;margin-bottom:6px}}
.content h2{{font-size:29px;color:{t[ink]};font-weight:800}}
.body{{flex:1;min-height:0;display:flex;flex-direction:column;margin-top:22px}}

.cards{{display:flex;flex-direction:column;gap:14px;flex:1;min-height:0}}
.card{{background:{t[card]};border-radius:14px;padding:14px 22px;display:flex;align-items:center;gap:16px;flex:1;min-height:0}}
.badge{{width:34px;height:34px;border-radius:50%;background:{t[primary]};color:#fff;font-family:{nf};font-size:15px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.card p{{font-size:18px;color:{t[ink]};line-height:1.5}}
.card .num{{font-family:{nf};font-size:26px;font-weight:800;color:{t[primary]};margin-right:6px}}

.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;flex:1;min-height:0}}
.grid2 .card{{flex:none}}

.kpis{{display:grid;gap:18px;flex:1;min-height:0}}
.kpi{{background:{t[card]};border-radius:16px;display:flex;flex-direction:column;align-items:flex-start;justify-content:center;padding:22px 30px}}
.kpi .n{{font-family:{nf};font-size:54px;font-weight:800;color:{t[primary]};line-height:1.05}}
.kpi .l{{font-size:15px;color:{t[ink]};margin-top:12px;line-height:1.45}}

.agenda .items{{display:grid;grid-template-columns:1fr 1fr;gap:14px 44px;align-content:center;flex:1;margin-top:20px}}
.agenda .item{{display:flex;align-items:baseline;gap:14px;padding:10px 4px}}
.agenda .no{{font-family:{nf};font-size:22px;font-weight:800;color:{t[primary]};opacity:.55}}
.agenda .txt{{font-size:18px;color:{t[ink]};font-weight:600}}

.list{{display:flex;flex-direction:column;justify-content:center;flex:1;gap:10px}}
.list p{{font-size:16px;color:{t[ink]};line-height:1.55;padding-left:16px;position:relative}}
.list p::before{{content:"";position:absolute;left:0;top:.62em;width:7px;height:7px;border-radius:50%;background:{t[primary]}}}

.pageno{{position:absolute;right:34px;bottom:20px;font-size:12px;color:{t[muted]}}}
"""


def _rings() -> str:
    """同心圆母题:右下角三环 + 实心点,封面/结尾共用。"""
    return (
        '<div class="ring" style="width:360px;height:360px;right:-130px;bottom:-130px;opacity:.35"></div>'
        '<div class="ring" style="width:250px;height:250px;right:-75px;bottom:-75px;opacity:.55"></div>'
        '<div class="ring" style="width:150px;height:150px;right:-25px;bottom:-25px;opacity:.8"></div>'
    )


def _hooks(bullets: list[str], t: dict[str, str]) -> str:
    """封面数字钩子:bullets 命中数据句式的前 3 条渲染为大数字 chip。"""
    chips = []
    for b in bullets[:3]:
        if sp := stat_parts(b):
            chips.append(
                f'<div class="hook"><div class="n">{_num_html(sp[0])}</div>'
                f'<div class="l">{escape(sp[1])}</div></div>'
            )
    return f'<div class="hooks">{"".join(chips)}</div>' if chips else ""


def _kicker(s: dict, fallback: str, t: dict[str, str]) -> str:
    text = s.get("subtitle") or fallback
    return f'<div class="kicker">{escape(text)}</div>' if text else ""


def _body_html(s: dict) -> str:
    bullets = s["bullets"]
    mode = body_mode(bullets)
    if mode == "list" or not bullets:
        rows = "".join(f"<p>{escape(b)}</p>" for b in bullets) or "<p> </p>"
        return f'<div class="list">{rows}</div>'
    if mode == "kpis":
        cols = "repeat(3,1fr)" if len(bullets) == 3 else "repeat(2,1fr)"
        cells = "".join(
            f'<div class="kpi"><div class="n">{_num_html(sp[0])}</div>'
            f'<div class="l">{escape(sp[1])}</div></div>'
            for sp in (stat_parts(b) for b in bullets)
        )
        return f'<div class="kpis" style="grid-template-columns:{cols}">{cells}</div>'
    if mode == "grid2":
        cells = []
        for i, b in enumerate(bullets, 1):
            cells.append(f'<div class="card"><span class="badge">{i}</span><p>{escape(b)}</p></div>')
        return f'<div class="grid2">{"".join(cells)}</div>'
    cards = []
    for i, b in enumerate(bullets, 1):
        badge = f'<span class="badge">{i}</span>'
        if sp := stat_parts(b):
            cards.append(
                f'<div class="card">{badge}<span class="num">{_num_html(sp[0])}</span>'
                f"<p>{escape(sp[1])}</p></div>"
            )
        else:
            cards.append(f'<div class="card">{badge}<p>{escape(b)}</p></div>')
    return f'<div class="cards">{"".join(cards)}</div>'


def _slide_html(s: dict, idx: int, total: int, t: dict[str, str]) -> str:
    if s["layout"] == "cover":
        sub = f'<p class="sub">{escape(s["subtitle"])}</p>' if s["subtitle"] else ""
        meta = f'<div class="meta">{date.today().strftime("%Y.%m")}</div>'  # 只留日期,避免与主标题重复
        return (
            f'<div class="slide cover">{_rings()}<h1>{escape(s["title"])}</h1>{sub}'
            f"{_hooks(s['bullets'], t)}{meta}</div>"
        )
    if s["layout"] == "end":
        sub = f'<p class="sub">{escape(s["subtitle"])}</p>' if s["subtitle"] else ""
        return f'<div class="slide end">{_rings()}<h1>{escape(s["title"])}</h1>{sub}</div>'
    if s["layout"] == "section":
        return (
            f'<div class="slide section"><div class="kick">第 {s["no"]} 部分</div>'
            f'<h2>{escape(s["title"])}</h2><span class="no">{s["no"]}</span></div>'
        )
    if s["layout"] == "agenda":
        items = "".join(
            f'<div class="item"><span class="no">{i:02d}</span>'
            f'<span class="txt">{escape(b)}</span></div>'
            for i, b in enumerate(s["bullets"], 1)
        )
        return (
            f'<div class="slide content agenda"><div class="kicker">目录</div>'
            f'<h2>{escape(s["title"])}</h2><div class="items">{items}</div>'
            f'<span class="pageno">{idx} / {total}</span></div>'
        )
    # content
    return (
        f'<div class="slide content">{_kicker(s, "", t)}<h2>{escape(s["title"])}</h2>'
        f'<div class="body">{_body_html(s)}</div>'
        f'<span class="pageno">{idx} / {total}</span></div>'
    )


def build_slides_html(title: str, slides: list[dict], theme: str | None) -> str:
    t = resolve_theme(theme)
    norm = normalize_slides(title, slides)
    body = "".join(_slide_html(s, i, len(norm), t) for i, s in enumerate(norm, 1))
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        f"<style>{_CSS.format(t=t, nf=_NUM_FONT)}</style></head>"
        f"<body>{body}</body></html>"
    )
