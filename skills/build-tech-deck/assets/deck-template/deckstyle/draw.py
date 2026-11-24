"""繪製原語：文字、線、圓角卡片、徽章、膠囊與卡片疊放。圖表區塊（blocks.py）只呼叫這裡，不直接碰 python-pptx 的形狀細節。

每個函式的第一個參數是 `Theme`：色票、線寬、字級都從它取，沒有模組層級的全域設定。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from .spec import as_lines
from .theme import Theme

# ---- 文字 ----

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def runs(t: Theme, par: Any, text: str, size: float, color: RGBColor, bold: bool = False, keep: bool = False) -> None:
    """支援 **粗體** 標記解析：粗體文字凸顯，其餘保留指定色。字型繼承主題，語言標 `t.lang`。"""
    title_text = (t.accent_text, t.tones["green"].text)  # 這兩種標題色的卡片裡，粗體改墨色
    for i, part in enumerate(_BOLD.split(text)):
        if not part:
            continue
        r = par.add_run()
        r.text = part
        r._r.get_or_add_rPr().set("lang", t.lang)  # 語言標記：拼字檢查與朗讀依它選語言
        r.font.size = Pt(size)
        is_bold = bold or (i % 2 == 1)
        r.font.bold = is_bold
        if is_bold and not keep and color in title_text:
            r.font.color.rgb = t.ink  # 標題色卡片裡的粗體段落改墨色；keep=True（語義儲存格）保留語義色
        elif is_bold and color == t.dark_sub:
            r.font.color.rgb = t.white
        else:
            r.font.color.rgb = color


def alt_text(shape: Any, text: str) -> None:
    """圖片、圖表、表格的替代文字（螢幕閱讀器朗讀；寫在 cNvPr 的 descr）。"""
    shape._element.xpath(".//p:cNvPr")[0].set("descr", text)


def text_box(
    t: Theme,
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    paras: str | Sequence[str],
    size: float = 14,
    color: RGBColor | None = None,
    bold: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
    bullet: bool = False,
    space: float = 4,
    line_spacing: float = 1.15,
) -> Any:
    color = color or t.ink
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    items = [paras] if isinstance(paras, str) else list(paras)
    for i, text in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space if i < len(items) - 1 else 0)
        p.line_spacing = line_spacing
        runs(t, p, ("・" + text) if bullet else text, size, color, bold)
    return tb


# ---- 線 ----


def seg(
    t: Theme,
    slide: Any,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: RGBColor | None = None,
    weight: float | None = None,
    dash: bool = False,
    arrow: bool = True,
) -> Any:
    """繪製由 (x1, y1) 指向 (x2, y2) 的直線或箭頭連線。"""
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color or t.ink
    c.line.width = Pt(weight if weight is not None else t.line_strong)
    if dash:
        c.line.dash_style = MSO_LINE.DASH
    if arrow:
        ln = c.line._get_or_add_ln()
        for old in ln.findall(qn("a:tailEnd")):
            ln.remove(old)
        ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


def line(
    t: Theme,
    slide: Any,
    x: float,
    y: float,
    w: float,
    color: RGBColor | None = None,
    weight: float | None = None,
    vertical: bool = False,
    h: float = 0.0,
) -> Any:
    """水平線（寬 w）；vertical=True 時是高 h 的垂直線。預設是細分隔線。"""
    return seg(
        t,
        slide,
        x,
        y,
        x + (0 if vertical else w),
        y + (h if vertical else 0),
        color=color or t.rule,
        weight=weight if weight is not None else t.line_hair,
        arrow=False,
    )


# ---- 形狀 ----


def _shape(
    slide: Any,
    mso: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: RGBColor | None,
    line_color: RGBColor | None,
    weight: float,
) -> Any:
    """帶填色與框線的形狀；fill 或 line_color 為 None 表示無填色或無框線。"""
    sh = slide.shapes.add_shape(mso, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line_color is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line_color
        sh.line.width = Pt(weight)
    sh.shadow.inherit = False
    return sh


def rect(
    t: Theme,
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: RGBColor | None = None,
    line_color: RGBColor | None = None,
    weight: float | None = None,
) -> Any:
    return _shape(
        slide, MSO_SHAPE.RECTANGLE, x, y, w, h, fill, line_color, weight if weight is not None else t.line_normal
    )


def _rounded(
    t: Theme, slide: Any, x: float, y: float, w: float, h: float, fill: RGBColor, line_color: RGBColor, weight: float
) -> Any:
    """圓角矩形：半徑取自設計參數（design.yml 的 geometry.radius-pt）。"""
    sh = _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill, line_color, weight)
    sh.adjustments[0] = min(0.5, t.radius_pt / 72.0 / max(0.01, min(w, h)))
    return sh


def badge(
    t: Theme,
    slide: Any,
    cx: float,
    cy: float,
    text: str,
    fill: RGBColor | None = None,
    ink: RGBColor | None = None,
    line_color: RGBColor | None = None,
    d: float = 0.28,
    fs: float = 10.5,
) -> Any:
    """繪製圓形序號或狀態徽章（置中於 cx, cy）。"""
    fill, ink = fill or t.ink, ink or t.white
    sh = _shape(slide, MSO_SHAPE.OVAL, cx - d / 2, cy - d / 2, d, d, fill, line_color or fill, t.line_normal)
    tf = sh.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    runs(t, p, text, fs, ink, bold=True)
    return sh


def pill(
    t: Theme, slide: Any, x: float, y: float, w: float, h: float, text: str, kind: str = "green_fill", fs: float = 11.5
) -> Any:
    """繪製膠囊狀態標籤。"""
    spec = t.cards.get(kind, t.cards["gray"])
    sh = _rounded(t, slide, x, y, w, h, spec.fill, spec.line, t.line_normal)
    tf = sh.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.06)
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    runs(t, p, text, fs, spec.head, bold=True)
    return sh


def card(
    t: Theme,
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    kind: str,
    title: str,
    body: str | Sequence[str] | None = None,
    tfs: float = 16.0,
    bfs: float = 13.0,
    bullet: bool = False,
    valign: MSO_ANCHOR = MSO_ANCHOR.TOP,
    pad_x: float = 0.13,
    pad_y: float = 0.08,
    en: str | None = None,
) -> Any:
    """繪製單一語義卡片：圓角、細線、語義強調色。

    `en` 是標題下一行較小的英文名稱（中英並列的專有名詞，如「生產系譜」下的 Production Genealogy）：
    字級約標題的七成、不加粗、灰字（深底卡片用內文色），與標題之間不留段距。
    """
    spec = t.cards.get(kind, t.cards["gray"])
    sh = _rounded(t, slide, x, y, w, h, spec.fill, spec.line, spec.weight)
    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = valign
    tf.margin_left = tf.margin_right = Inches(pad_x)
    tf.margin_top = tf.margin_bottom = Inches(pad_y)

    items = as_lines(body)
    if title:
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.LEFT
        p0.space_after = Pt(3 if items and not en else 0)
        p0.line_spacing = 1.12
        runs(t, p0, title, tfs, spec.head, bold=True)
        if en:
            pe = tf.add_paragraph()
            pe.alignment = PP_ALIGN.LEFT
            pe.space_after = Pt(3 if items else 0)
            pe.line_spacing = 1.05
            runs(t, pe, en, round(tfs * 0.70 * 2) / 2, spec.ink if kind == "solid_dark" else t.muted, bold=False)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if (i == 0 and not title) else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(3 if i < len(items) - 1 else 0)
        p.line_spacing = 1.14
        runs(t, p, ("・" + item) if bullet else item, bfs, spec.ink, bold=False)
    return sh


# ---- 版面分割與疊放 ----


def split(start: float, total: float, n: int, gap: float) -> list[tuple[float, float]]:
    """把長度 total 等分成 n 格、格距 gap；回傳每格的（起點, 長度）。水平與垂直共用。"""
    size = (total - gap * (n - 1)) / n
    return [(start + i * (size + gap), size) for i in range(n)]


def card_stack(
    t: Theme,
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    items: Sequence[dict[str, Any]],
    bullet: bool,
    gap: float | None = None,
) -> None:
    """在 (x, y, w, h) 內垂直等分疊放語義卡片（右側論證欄）；item 的 kind、title、body、bullet 與規格同名。"""
    gap = t.layout.stack_gap if gap is None else gap
    for (ty, th), it in zip(split(y, h, len(items), gap), items, strict=True):
        card(
            t,
            slide,
            x,
            ty,
            w,
            th,
            it.get("kind", "gray"),
            it["title"],
            it.get("body"),
            tfs=t.type.panel_title,
            bfs=t.type.panel_body,
            bullet=it.get("bullet", bullet),
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.12,
            pad_y=0.06,
        )


def edge_overlay(
    t: Theme,
    slide: Any,
    blocked: bool,
    color: RGBColor,
    mark: tuple[float, float],
    label: str | None,
    box: tuple[float, float, float, float],
    **text_kw: Any,
) -> None:
    """連線上的附加物：阻斷邊中點的「✕」徽章，與邊標籤（box 是標籤的 x, y, w, h）。"""
    if blocked:
        badge(t, slide, *mark, "✕", fill=t.alert, ink=t.white, d=0.22, fs=9.5)
    if label:
        text_box(t, slide, *box, label, size=t.type.label, color=color, bold=True, **text_kw)


# ---- 依 kind 取色 ----


def kind_line(t: Theme, kind: str | None) -> RGBColor:
    """語義 kind 的線色；其餘（含 dark）用墨色。"""
    return t.tones[kind].line if kind is not None and kind in t.tones else t.ink


def kind_head(t: Theme, kind: str | None) -> RGBColor:
    """語義 kind 的白底小字色；其餘用墨色。"""
    return t.tones[kind].text if kind is not None and kind in t.tones else t.ink


def badge_fill(t: Theme, kind: str | None) -> RGBColor:
    """序號徽章底色：語義卡片取線色，墨框與實心墨底用墨色（實心墨底上的徽章反白，否則數字隱形）。"""
    if kind == "solid_dark":
        return t.white
    base = (kind or "").removesuffix("_fill")
    return t.tones[base].line if base in t.tones else t.ink


def pill_kind(kind: str | None, tones: Sequence[str] = ("blue", "green", "amber", "red")) -> str:
    """徽章與時序膠囊的樣式：語義色用淡底，其餘用墨底。"""
    base = (kind or "").removesuffix("_fill")
    return f"{base}_fill" if base in tones else "solid_dark"


# ---- 表格儲存格框線 ----


def cell_border(t: Theme, cell: Any, color: RGBColor | None = None, width: int = 6350) -> None:
    """儲存格四邊細框線；框線元素須排在 tcPr 的最前面（填色之前）。"""
    color = color or t.rule
    tc_pr = cell._tc.get_or_add_tcPr()
    for i, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
        for old in tc_pr.findall(qn(tag)):
            tc_pr.remove(old)
        ln = tc_pr.makeelement(qn(tag), {"w": str(width)})
        solid = ln.makeelement(qn("a:solidFill"), {})
        solid.append(solid.makeelement(qn("a:srgbClr"), {"val": str(color)}))
        ln.append(solid)
        tc_pr.insert(i, ln)
