"""佈局引擎：把宣告式規格（deck_spec.SLIDES）轉成 PPTX。

每個原語簽章 (slide, y, **規格欄位) -> 佔用高度（英吋），build() 依序堆疊。
"""
import re

from pptx import Presentation
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

import theme as T

GAP = 0.25  # 區塊間距


def _runs(par, text, size, color, bold=False):
    """寫入一段文字；`**粗體**` 轉成粗體 run，粗體內的綠字改墨黑以保持可讀。"""
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        r = par.add_run()
        r.text = part
        r.font.name = T.FONT
        r.font.size = Pt(size)
        r.font.bold = bold or (i % 2 == 1)
        r.font.color.rgb = (T.INK if color == T.ACCENT_TEXT else color) if i % 2 == 1 else color


def _rect(slide, x, y, w, h, fill=None, line=None, width=0.75, dash=False):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(width)
        if dash:
            sh.line.dash_style = MSO_LINE.DASH
    sh.shadow.inherit = False
    return sh


def _text(slide, x, y, w, h, lines, size, color, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, wrap=True):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    for i, line in enumerate(lines if isinstance(lines, list) else [lines]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        _runs(p, line, size, color, bold)
    return tb


def _draw_card(slide, x, y, w, h, kind, title, body, tfs, bfs, bullet, valign):
    spec = T.CARDS[kind]
    sh = _rect(slide, x, y, w, h, fill=spec["fill"], line=spec["line"], width=1.5, dash=spec["dash"])
    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = valign
    tf.margin_left = tf.margin_right = Inches(0.14)
    tf.margin_top = tf.margin_bottom = Inches(0.10)
    items = body.split("\n") if isinstance(body, str) else list(body or [])
    if title:
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.LEFT
        p0.space_after = Pt(6 if items else 0)
        _runs(p0, title, tfs, spec["head"], bold=True)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if (i == 0 and not title) else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(4 if i < len(items) - 1 else 0)
        _runs(p, ("・" + item) if bullet else item, bfs, spec["ink"])


def cards(slide, y, items, h=2.80, tfs=16.5, bfs=13.5, bullet=True, valign=MSO_ANCHOR.MIDDLE):
    """水平語義卡片列，依數量等分寬度。item：{kind, title, body}。"""
    gap = 0.30
    cw = (T.W - gap * (len(items) - 1)) / len(items)
    for i, it in enumerate(items):
        _draw_card(slide, T.LM + i * (cw + gap), y, cw, h, it["kind"], it["title"], it.get("body"), tfs, bfs, bullet, valign)
    return h


def table(slide, y, rows, col_w=None, size=12.5, row_h=0.46):
    """首列墨黑底白字、奇偶列交錯。儲存格可寫 str，或 (str, "green"|"red") 做語義高亮。col_w 為各欄寬度比例。"""
    n_r, n_c = len(rows), len(rows[0])
    ratios = col_w or [1] * n_c
    gf = slide.shapes.add_table(n_r, n_c, Inches(T.LM), Inches(y), Inches(T.W), Inches(row_h * n_r))
    tbl = gf.table
    tbl.horz_banding = False
    for c, ratio in enumerate(ratios):
        tbl.columns[c].width = Inches(T.W * ratio / sum(ratios))
    for r, row in enumerate(rows):
        tbl.rows[r].height = Inches(row_h)
        for c, value in enumerate(row):
            text, tone = value if isinstance(value, tuple) else (value, None)
            cell = tbl.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = T.INK if r == 0 else (T.ROW_ALT if r % 2 == 0 else T.WHITE)
            cell.margin_left = cell.margin_right = Inches(0.12)
            cell.margin_top = cell.margin_bottom = Inches(0.05)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            color = T.WHITE if r == 0 else {"green": T.ACCENT_TEXT, "red": T.ALERT}.get(tone, T.INK)
            tf = cell.text_frame
            tf.word_wrap = True
            _runs(tf.paragraphs[0], text, size, color, bold=(r == 0 or tone is not None))
    return row_h * n_r


def steps(slide, y, items, h=1.9):
    """序號步驟列：頂部綠線、大號序號、標題與一行說明。item：{title, body}。"""
    gap = 0.30
    cw = (T.W - gap * (len(items) - 1)) / len(items)
    for i, it in enumerate(items):
        x = T.LM + i * (cw + gap)
        _rect(slide, x, y, cw, 0.04, fill=T.ACCENT)
        _text(slide, x, y + 0.12, cw, 0.6, f"{i + 1:02d}", 34, T.ACCENT_TEXT, bold=True)
        _text(slide, x, y + 0.80, cw, 0.4, it["title"], 16.5, T.INK, bold=True)
        _text(slide, x, y + 1.25, cw, 0.6, it.get("body", ""), 13.5, T.GRAY)
    return h


def columns(slide, y, cols, h=2.4):
    """推進計畫或結論：頂部細線、粗體標題、短條列。col：{title, items}。"""
    gap = 0.40
    cw = (T.W - gap * (len(cols) - 1)) / len(cols)
    for i, col in enumerate(cols):
        x = T.LM + i * (cw + gap)
        _rect(slide, x, y, cw, 0.03, fill=T.INK)
        _text(slide, x, y + 0.15, cw, 0.5, col["title"], 18, T.INK, bold=True)
        _text(slide, x, y + 0.75, cw, h - 0.75, ["・" + t for t in col["items"]], 14.5, T.GRAY)
    return h


def banner(slide, y, text, kind="red", h=0.80):
    """全寬核心問題或主張框。"""
    spec = T.CARDS[kind]
    sh = _rect(slide, T.LM, y, T.W, h, fill=spec["fill"], line=spec["line"], width=1.5, dash=spec["dash"])
    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    _runs(tf.paragraphs[0], text, 18, spec["head"], bold=True)
    return h


def note(slide, y, lines, size=14, bold=False):
    """底部細線分隔的單行總結。"""
    _rect(slide, T.LM, y, T.W, 0.01, fill=T.RULE)
    _text(slide, T.LM, y + 0.12, T.W, 0.50, " ".join(lines), size, T.INK if bold else T.GRAY, bold=bold)
    return 0.60


PRIMITIVES = {"cards": cards, "table": table, "steps": steps, "columns": columns, "banner": banner, "note": note}
PINNED_BOTTOM = {"note"}  # 釘在安全底線，不隨前面區塊堆疊


def _frame(slide, category, title, page):
    _text(slide, T.LM, 0.45, T.W, 0.30, category, 12, T.ACCENT_TEXT, bold=True, wrap=False)
    _text(slide, T.LM, 0.78, T.W, 0.70, title, 28, T.INK, bold=True, anchor=MSO_ANCHOR.MIDDLE, wrap=False)
    _rect(slide, T.LM, 7.00, T.W, 0.01, fill=T.RULE)
    _text(slide, T.RM - 1.0, 7.05, 1.0, 0.3, str(page), 11, T.MUTED, align=PP_ALIGN.RIGHT, wrap=False)


def build(slides, out):
    """slides：(分類標籤, 主標題, [(原語名, 欄位 dict), ...], 講稿備註) 的序列。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(T.SLIDE_W), Inches(T.SLIDE_H)
    for page, (category, title, blocks, notes) in enumerate(slides, 1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白版型
        _frame(slide, category, title, page)
        y = T.TOP
        for kind, fields in blocks:
            if kind in PINNED_BOTTOM:
                PRIMITIVES[kind](slide, T.BOTTOM - 0.45, **fields)
            else:
                y += PRIMITIVES[kind](slide, y, **fields) + GAP
        slide.notes_slide.notes_text_frame.text = notes
    prs.save(out)
