"""佈局與視覺圖表引擎：由宣告式規格（deck_spec.SPEC）直接產出 PPTX。

每個原語簽章 (slide, y, height=可用高度, **規格欄位) -> 佔用高度（英吋）；Deck.slide() 依序堆疊，
帶 h 的區塊固定高度，其餘均分剩餘高度，note 釘在安全底線。顏色、字型、圓角取自 theme.py（再取自 tokens.toml）。
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Sequence

from lxml import etree
from pptx import Presentation
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
import theme as T

GAP = 0.18
CONTENT_BOTTOM = 6.85  # 頁尾細線在 7.00；內容區到此為止
NOTE_H = 0.56  # 底部結論列高度
CARD_MAX_H = 4.20
ROW_MAX_H = 1.20
STEPS_MAX_H = 3.20
COLUMNS_MAX_H = 3.00


def inch(v: float) -> Inches:
    return Inches(v)


def _runs(par: Any, text: str, size: float, color: Any, bold: bool = False, keep: bool = False) -> None:
    """支援 **粗體** 標記解析：粗體文字凸顯，其餘保留指定色。"""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    for i, part in enumerate(parts):
        if not part:
            continue
        r = par.add_run()
        r.text = part
        r.font.name = T.FONT
        r.font.size = Pt(size)
        is_bold = bold or (i % 2 == 1)
        r.font.bold = is_bold
        if is_bold and not keep and color in (T.ACCENT_TEXT, T.GREEN_TEXT):
            r.font.color.rgb = T.INK  # 標題色卡片裡的粗體段落改墨色；keep=True（語義儲存格）保留語義色
        elif is_bold and color == T.DARK_SUB:
            r.font.color.rgb = T.WHITE
        else:
            r.font.color.rgb = color


def seg(
    slide: Any,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: Any = T.INK,
    weight: float = 1.5,
    dash: bool = False,
    arrow: bool = True,
) -> Any:
    """繪製由 (x1, y1) 指向 (x2, y2) 的直線或箭頭連線。"""
    c = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        Inches(x1),
        Inches(y1),
        Inches(x2),
        Inches(y2),
    )
    c.line.color.rgb = color
    c.line.width = Pt(weight)
    if dash:
        c.line.dash_style = MSO_LINE.DASH
    if arrow:
        ln = c.line._get_or_add_ln()
        for old in ln.findall(qn("a:tailEnd")):
            ln.remove(old)
        ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


def line(
    slide: Any,
    x: float,
    y: float,
    w: float,
    color: Any = T.RULE,
    weight: float = 0.75,
    vertical: bool = False,
    h: float = 0.0,
    arrow: bool = False,
) -> Any:
    return seg(
        slide,
        x,
        y,
        x + (0 if vertical else w),
        y + (h if vertical else 0),
        color=color,
        weight=weight,
        dash=False,
        arrow=arrow,
    )


def text_box(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    paras: str | Sequence[str],
    size: float = 14,
    color: Any = T.INK,
    bold: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
    bullet: bool = False,
    space: float = 4,
    line_spacing: float = 1.15,
) -> Any:
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    items = [paras] if isinstance(paras, str) else list(paras)
    for i, t in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space if i < len(items) - 1 else 0)
        p.line_spacing = line_spacing
        _runs(p, ("・" + t) if bullet else t, size, color, bold)
    return tb


def _rounded(slide: Any, x: float, y: float, w: float, h: float) -> Any:
    """圓角矩形：半徑取自設計規格（tokens.toml 的 geometry.radius_pt），與專論的 TikZ 節點一致。"""
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    radius_in = T.RADIUS_PT / 72.0
    sh.adjustments[0] = min(0.5, radius_in / max(0.01, min(w, h)))
    return sh


def _badge(
    slide: Any,
    cx: float,
    cy: float,
    text: str,
    fill: Any = T.INK,
    ink: Any = T.WHITE,
    line_color: Any = None,
    d: float = 0.28,
    fs: float = 10.5,
) -> Any:
    """繪製圓形序號或狀態徽章（置中於 cx, cy）。"""
    sh = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - d / 2),
        Inches(cy - d / 2),
        Inches(d),
        Inches(d),
    )
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line_color or fill
    sh.line.width = Pt(1.0)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    _runs(p, text, fs, ink, bold=True)
    return sh


def _pill(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    kind: str = "green_fill",
    fs: float = 11.5,
) -> Any:
    """繪製膠囊／直角狀態標籤。"""
    spec = T.CARDS.get(kind, T.CARDS["gray"])
    sh = _rounded(slide, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = spec["fill"]
    sh.line.color.rgb = spec["line"]
    sh.line.width = Pt(T.LINE_NORMAL)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.06)
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    _runs(p, text, fs, spec["head"], bold=True)
    return sh


def _draw_card(
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
) -> Any:
    """繪製單一語義矩形卡片：直角、細線、語義強調色。"""
    spec = T.CARDS.get(kind, T.CARDS["gray"])
    sh = _rounded(slide, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = spec["fill"]
    sh.line.color.rgb = spec["line"]
    sh.line.width = Pt(T.LINE_NORMAL if kind in ("gray", "white") else T.LINE_STRONG)
    if spec["dash"]:
        sh.line.dash_style = MSO_LINE.DASH
    sh.shadow.inherit = False

    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = valign
    tf.margin_left = tf.margin_right = Inches(pad_x)
    tf.margin_top = tf.margin_bottom = Inches(pad_y)

    items = body.split("\n") if isinstance(body, str) else (list(body) if body else [])
    if title:
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.LEFT
        p0.space_after = Pt(3 if items else 0)
        p0.line_spacing = 1.12
        _runs(p0, title, tfs, spec["head"], bold=True)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if (i == 0 and not title) else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(3 if i < len(items) - 1 else 0)
        p.line_spacing = 1.14
        _runs(p, ("・" + item) if bullet else item, bfs, spec["ink"], bold=False)
    return sh


def _badge_fill(kind: str | None) -> Any:
    """序號徽章底色：依卡片語義取線色，墨框與實心墨底用墨色。"""
    spec = T.CARDS.get(kind or "dark", T.CARDS["dark"])
    if kind == "solid_dark":
        return T.WHITE  # 墨底方塊上的徽章反白（數字用墨色），否則數字隱形
    return T.INK if kind in (None, "gray", "white", "dark") else spec["line"]


def _pill_kind(kind: str | None) -> str:
    """徽章與時序膠囊的樣式：語義色用淡底，其餘用墨底。"""
    base = (kind or "").replace("_fill", "")
    return f"{base}_fill" if base in ("blue", "green", "amber", "red") else "solid_dark"


def _kind_line(kind: str | None) -> Any:
    return {"green": T.GREEN, "red": T.ALERT, "blue": T.BLUE, "amber": T.AMBER}.get(kind or "", T.INK)


def _kind_head(kind: str | None) -> Any:
    return {"green": T.GREEN_TEXT, "red": T.ALERT_TEXT, "blue": T.BLUE_TEXT, "amber": T.AMBER_TEXT}.get(kind or "", T.INK)


def _cell_border(cell: Any, color: Any = T.RULE, width: int = 6350) -> None:
    """設定儲存格細框線。"""
    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("lnL", "lnR", "lnT", "lnB"):
        for old in tcPr.findall(f"{{{ns}}}{tag}"):
            tcPr.remove(old)
    els = []
    for tag in ("lnL", "lnR", "lnT", "lnB"):
        ln = etree.SubElement(tcPr, f"{{{ns}}}{tag}")
        ln.set("w", str(width))
        sf = etree.SubElement(ln, f"{{{ns}}}solidFill")
        etree.SubElement(sf, f"{{{ns}}}srgbClr").set("val", f"{color[0]:02X}{color[1]:02X}{color[2]:02X}")
        els.append(ln)
    for i, ln in enumerate(els):
        tcPr.remove(ln)
        tcPr.insert(i, ln)


# ---- 基礎佈局原語 ----

def banner(
    slide: Any,
    y: float,
    kind: str,
    title: str,
    body: str | Sequence[str] | None = None,
    h: float = 0.68,
    height: float = 0.68,
    tfs: float = 16.5,
    bfs: float = 13.5,
    valign: MSO_ANCHOR = MSO_ANCHOR.MIDDLE,
) -> float:
    box_h = min(h, height) if height else h
    _draw_card(slide, T.LM, y, T.W, box_h, kind, title, body, tfs=tfs, bfs=bfs, valign=valign)
    return box_h


def cards(
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    height: float = 3.80,
    h: float | None = None,
    bullet: bool = True,
) -> float:
    n = len(items)
    gap = 0.24
    cw = (T.W - gap * (n - 1)) / n
    box_h = h if h is not None else min(height, CARD_MAX_H)
    tfs, bfs = (18.5, 14.5) if n <= 3 else (15.5, 12.5)
    if box_h < 2.2:
        tfs, bfs = (15.5, 12.5) if n <= 3 else (14.0, 11.5)
    for i, it in enumerate(items):
        x = T.LM + i * (cw + gap)
        _draw_card(
            slide, x, y, cw, box_h, it["kind"], it["title"], it.get("body"),
            tfs=tfs, bfs=bfs, bullet=it.get("bullet", bullet), valign=MSO_ANCHOR.MIDDLE,
        )
    return box_h


def flow(
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    height: float = 1.80,
    h: float | None = None,
    caption: str = "",
    edge_labels: Sequence[str] | None = None,
    numbered: bool = False,
) -> float:
    """水平流程與架構管線圖：支援步驟節點、有向箭頭、邊標籤與編號徽章。"""
    cap_h = 0.30 if caption else 0.0
    if caption:
        text_box(slide, T.LM, y, T.W, 0.26, caption, size=13, color=T.GRAY, bold=True)
    n = len(items)
    gap = (0.68 if n <= 4 else 0.42) if edge_labels else 0.28
    cw = (T.W - gap * (n - 1)) / n
    box_h = h if h is not None else min(height - cap_h, 2.20)
    by = y + cap_h
    tfs = 16.0 if n <= 4 else (14.5 if n == 5 else 13.5)
    bfs = 12.5 if n <= 4 else (11.5 if n == 5 else 11.0)
    for i, it in enumerate(items):
        x = T.LM + i * (cw + gap)
        _draw_card(
            slide, x, by, cw, box_h, it.get("kind", "gray"), it["title"], it.get("body"),
            tfs=tfs, bfs=bfs, bullet=False, valign=MSO_ANCHOR.MIDDLE, pad_x=0.10,
        )
        if numbered:
            is_dark = it.get("kind") == "solid_dark"
            _badge(
                slide, x + 0.04, by + 0.04, str(i + 1),
                fill=T.WHITE if is_dark else T.INK,
                ink=T.INK if is_dark else T.WHITE,
                line_color=T.INK,
                d=0.25, fs=10,
            )
        if i < n - 1:
            ax1 = x + cw + 0.04
            ax2 = x + cw + gap - 0.04
            ay = by + box_h / 2
            seg(slide, ax1, ay, ax2, ay, color=T.INK, weight=1.5, arrow=True)
            if edge_labels and i < len(edge_labels) and edge_labels[i]:
                text_box(
                    slide, x + cw + 0.02, ay - 0.28, gap - 0.04, 0.22,
                    edge_labels[i], size=10.0, color=T.ACCENT_TEXT, bold=True, align=PP_ALIGN.CENTER,
                )
    return cap_h + box_h


def swimlane(
    slide: Any,
    y: float,
    lanes: Sequence[dict[str, str]],
    steps: Sequence[dict[str, Any]],
    thesis: Sequence[dict[str, Any]] | None = None,
    height: float = 4.35,
) -> float:
    """跨泳道時序與控制流架構圖：奇偶交錯泳道 + 跨泳道折線箭頭 + 圓形序號徽章 + 下方論證卡片。"""
    thesis_h = 1.12 if thesis else 0.0
    thesis_gap = 0.16 if thesis else 0.0
    lane_area_h = height - thesis_h - thesis_gap
    nl = len(lanes)
    lh = lane_area_h / nl
    lab_w = 1.75

    # 1. 繪製泳道背景列與左側角色標題
    for i, ln_info in enumerate(lanes):
        ly = y + i * lh
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(T.LM), Inches(ly), Inches(T.W), Inches(lh))
        sh.fill.solid()
        sh.fill.fore_color.rgb = T.ROW_ALT if i % 2 == 0 else T.WHITE
        sh.line.color.rgb = T.RULE
        sh.line.width = Pt(0.75)
        sh.shadow.inherit = False

        # 左側分隔線
        line(slide, T.LM + lab_w, ly, 0, color=T.RULE, weight=0.75, vertical=True, h=lh)

        name = ln_info["name"]
        sub = ln_info.get("sub", "")
        lines = [f"**{name}**", sub] if sub else [f"**{name}**"]
        text_box(
            slide, T.LM + 0.12, ly + 0.06, lab_w - 0.20, lh - 0.12,
            lines, size=13.0, color=T.GRAY, anchor=MSO_ANCHOR.MIDDLE, space=2,
        )

    # 2. 計算每個步驟方塊的幾何座標
    ns = len(steps)
    gx = T.LM + lab_w + 0.12
    gw = T.W - lab_w - 0.20
    pitch = gw / ns
    bw = min(1.72, pitch - 0.16)
    bh = min(0.78, lh - 0.14)

    coords = []
    for k, st in enumerate(steps):
        lane_idx = st["lane"]
        sx = gx + k * pitch + (pitch - bw) / 2
        sy = y + lane_idx * lh + (lh - bh) / 2
        coords.append((sx, sy, lane_idx))

    # 3. 先畫跨泳道折線（水平段無箭頭、垂直段帶箭頭），再畫方塊蓋住端點
    for k in range(ns - 1):
        ax, ay, alane = coords[k]
        bx, by, blane = coords[k + 1]
        ay_mid = ay + bh / 2
        bx_mid = bx + bw / 2
        is_blocked = steps[k + 1].get("edge") == "blocked"
        edge_color = T.ALERT if is_blocked else (T.GREEN if steps[k + 1].get("edge") == "green" else T.INK)
        is_dash = bool(steps[k + 1].get("dash", False) or is_blocked)
        if alane == blane:
            seg(slide, ax + bw + 0.02, ay_mid, bx - 0.03, ay_mid, color=edge_color, weight=1.5, dash=is_dash, arrow=True)
        else:
            seg(slide, ax + bw, ay_mid, bx_mid, ay_mid, color=edge_color, weight=1.5, dash=is_dash, arrow=False)
            if blane > alane:
                seg(slide, bx_mid, ay_mid, bx_mid, by - 0.03, color=edge_color, weight=1.5, dash=is_dash, arrow=True)
            else:
                seg(slide, bx_mid, ay_mid, bx_mid, by + bh + 0.03, color=edge_color, weight=1.5, dash=is_dash, arrow=True)

    # 4. 繪製步驟方塊與圓形序號徽章
    for k, st in enumerate(steps):
        sx, sy, _ = coords[k]
        kind = st.get("kind", "dark")
        _draw_card(
            slide, sx, sy, bw, bh, kind, st["title"], st.get("sub"),
            tfs=13.5, bfs=11.0, bullet=False, valign=MSO_ANCHOR.MIDDLE, pad_x=0.08, pad_y=0.04,
        )
        is_solid = kind == "solid_dark"
        badge_fill = _badge_fill(kind)
        badge_ink = T.INK if is_solid else T.WHITE
        _badge(slide, sx, sy, str(k + 1), fill=badge_fill, ink=badge_ink, line_color=T.INK if is_solid else badge_fill, d=0.25, fs=10)

    # 5. 下方論證卡片列
    if thesis:
        ty = y + lane_area_h + thesis_gap
        nt = len(thesis)
        tgap = 0.20
        tcw = (T.W - tgap * (nt - 1)) / nt
        for i, tc in enumerate(thesis):
            tx = T.LM + i * (tcw + tgap)
            _draw_card(
                slide, tx, ty, tcw, thesis_h, tc.get("kind", "gray"), tc["title"], tc.get("body"),
                tfs=13.5, bfs=11.5, bullet=tc.get("bullet", False), valign=MSO_ANCHOR.MIDDLE, pad_x=0.10, pad_y=0.06,
            )

    return height


def arch_graph(
    slide: Any,
    y: float,
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]] | None = None,
    zones: Sequence[dict[str, Any]] | None = None,
    col_headers: Sequence[str] | None = None,
    side_thesis: Sequence[dict[str, Any]] | None = None,
    cols: int = 3,
    rows: int = 3,
    height: float = 4.35,
) -> float:
    """分區容器與有向系統拓撲圖：支援背景區域容器、網格節點、有向／阻斷邊標籤與右側結構化論證面板。"""
    has_side = bool(side_thesis)
    side_w = 3.85 if has_side else 0.0
    side_gap = 0.28 if has_side else 0.0
    graph_w = T.W - side_w - side_gap

    hdr_h = 0.42 if col_headers else 0.0
    c_gap = 0.78 if (not has_side and cols == 3) else 0.68
    if col_headers:
        cw_hdr = (graph_w - c_gap * (cols - 1)) / cols
        for c_idx, h_text in enumerate(col_headers):
            hx = T.LM + c_idx * (cw_hdr + c_gap)
            text_box(slide, hx, y, cw_hdr, 0.28, h_text, size=12.5, color=T.MUTED, bold=True)

    gy = y + hdr_h
    gh = height - hdr_h
    r_gap = 0.34 if rows >= 3 else 0.42
    cw = (graph_w - c_gap * (cols - 1)) / cols
    rh = (gh - r_gap * (rows - 1)) / rows

    def cell_rect(c: int, r: int, cs: int = 1, rs: int = 1) -> tuple[float, float, float, float]:
        rx = T.LM + c * (cw + c_gap)
        ry = gy + r * (rh + r_gap)
        rw = cs * cw + (cs - 1) * c_gap
        r_h = rs * rh + (rs - 1) * r_gap
        return rx, ry, rw, r_h

    # 1. 繪製背景區域容器（zones）
    for z in zones or []:
        zx, zy, zw, zh = cell_rect(z["col"], z["row"], z.get("col_span", 1), z.get("row_span", 1))
        pad = 0.10
        z_kind = z.get("kind", "gray")
        _draw_card(
            slide, zx - pad, zy - pad, zw + 2 * pad, zh + 2 * pad,
            z_kind, z.get("title", ""), z.get("sub"),
            tfs=14.0, bfs=11.5, valign=MSO_ANCHOR.TOP, pad_x=0.12, pad_y=0.08,
        )

    # 2. 紀錄所有節點座標並繪製節點
    node_boxes: dict[str, tuple[float, float, float, float]] = {}
    for nd in nodes:
        nx, ny, nw, nh = cell_rect(nd["col"], nd["row"], nd.get("col_span", 1), nd.get("row_span", 1))
        if nd.get("inset"):
            nx += 0.08
            nw -= 0.16
            ny += 0.06
            nh -= 0.12
        node_boxes[nd["id"]] = (nx, ny, nw, nh)
        _draw_card(
            slide, nx, ny, nw, nh, nd.get("kind", "gray"), nd["title"], nd.get("sub"),
            tfs=nd.get("tfs", 14.5 if not has_side else 13.5),
            bfs=nd.get("bfs", 11.8 if not has_side else 11.2),
            bullet=nd.get("bullet", False),
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.10, pad_y=0.06,
        )
        if nd.get("badge"):
            b_str = str(nd["badge"])
            is_solid = nd.get("kind") == "solid_dark"
            b_kind = nd.get("kind", "dark")
            if len(b_str) <= 2:
                bfill = _badge_fill(b_kind)
                _badge(slide, nx + 0.02, ny + 0.02, b_str, fill=bfill, ink=T.INK if is_solid else T.WHITE, d=0.25, fs=10)
            else:
                pill_kind = _pill_kind(b_kind)
                pw = max(0.62, min(nw - 0.16, 0.16 + 0.11 * sum(1.35 if ord(c) > 127 else 0.72 for c in b_str)))
                _pill(slide, nx + 0.06, ny - 0.11, pw, 0.22, b_str, kind=pill_kind, fs=9.0)

    # 3. 繪製有向邊與邊標籤
    for ed in edges or []:
        ax, ay, aw, ah = node_boxes[ed["from"]]
        bx, by, bw, bh = node_boxes[ed["to"]]
        ekind = ed.get("kind", "solid")
        ecolor = T.ALERT if ekind == "blocked" else (T.GREEN if ekind == "green" else (T.MUTED if ekind == "dashed" else T.INK))
        edash = ekind in ("dashed", "blocked")

        # 判斷水平連線或垂直連線
        if abs((ay + ah / 2) - (by + bh / 2)) < 0.25:
            my = (ay + ah / 2 + by + bh / 2) / 2
            if bx > ax:
                x1, x2 = ax + aw + 0.03, bx - 0.03
            else:
                x1, x2 = ax - 0.03, bx + bw + 0.03
            seg(slide, x1, my, x2, my, color=ecolor, weight=1.5, dash=edash, arrow=True)
            mid_x = (x1 + x2) / 2
            if ekind == "blocked":
                _badge(slide, mid_x, my, "✕", fill=T.ALERT, ink=T.WHITE, d=0.22, fs=9.5)
            if ed.get("label"):
                ly_off = my - 0.34 if ekind == "blocked" else my - 0.28
                text_box(
                    slide, min(x1, x2) - 0.22, ly_off, abs(x2 - x1) + 0.44, 0.22,
                    ed["label"], size=10.0, color=ecolor, bold=True, align=PP_ALIGN.CENTER,
                )
        elif abs((ax + aw / 2) - (bx + bw / 2)) < 0.35:
            mx = (ax + aw / 2 + bx + bw / 2) / 2
            if by > ay:
                y1, y2 = ay + ah + 0.03, by - 0.03
            else:
                y1, y2 = ay - 0.03, by + bh + 0.03
            seg(slide, mx, y1, mx, y2, color=ecolor, weight=1.5, dash=edash, arrow=True)
            mid_y = (y1 + y2) / 2
            if ekind == "blocked":
                _badge(slide, mx, mid_y, "✕", fill=T.ALERT, ink=T.WHITE, d=0.22, fs=9.5)
            if ed.get("label"):
                lx_off = mx + 0.16 if ekind == "blocked" else mx + 0.08
                text_box(
                    slide, lx_off, min(y1, y2), 1.80, abs(y2 - y1),
                    ed["label"], size=10.0, color=ecolor, bold=True, anchor=MSO_ANCHOR.MIDDLE,
                )
        else:
            # L 型正交連線：由起點右側／左側水平連至終點中線，再垂直進入終點
            ay_m = ay + ah / 2
            bx_m = bx + bw / 2
            x_start = (ax + aw + 0.02) if bx_m > ax + aw / 2 else (ax - 0.02)
            y_end = (by - 0.03) if by > ay else (by + bh + 0.03)
            seg(slide, x_start, ay_m, bx_m, ay_m, color=ecolor, weight=1.5, dash=edash, arrow=False)
            seg(slide, bx_m, ay_m, bx_m, y_end, color=ecolor, weight=1.5, dash=edash, arrow=True)
            if ekind == "blocked":
                _badge(slide, bx_m, (ay_m + y_end) / 2, "✕", fill=T.ALERT, ink=T.WHITE, d=0.22, fs=9.5)
            if ed.get("label"):
                text_box(
                    slide, min(x_start, bx_m), ay_m - 0.25, abs(bx_m - x_start), 0.22,
                    ed["label"], size=10.0, color=ecolor, bold=True, align=PP_ALIGN.CENTER,
                )

    # 4. 右側結構化論證面板（side_thesis）
    if side_thesis:
        sx = T.LM + graph_w + side_gap
        nt = len(side_thesis)
        t_gap = 0.16
        th = (height - t_gap * (nt - 1)) / nt
        for i, tc in enumerate(side_thesis):
            ty = y + i * (th + t_gap)
            _draw_card(
                slide, sx, ty, side_w, th, tc.get("kind", "gray"), tc["title"], tc.get("body"),
                tfs=14.0, bfs=11.8, bullet=tc.get("bullet", True), valign=MSO_ANCHOR.MIDDLE, pad_x=0.12, pad_y=0.06,
            )

    return height


def bench_chart(
    slide: Any,
    y: float,
    groups: Sequence[dict[str, Any]],
    thesis: Sequence[dict[str, Any]],
    height: float = 4.35,
) -> float:
    """量化實測橫向長條圖（左）＋ 結構化論證面板（右）。"""
    left_w = 6.65
    gap = 0.30
    right_w = T.W - left_w - gap
    rx = T.LM + left_w + gap

    ng = len(groups)
    g_gap = 0.18
    gh = (height - g_gap * (ng - 1)) / ng

    for gi, grp in enumerate(groups):
        gy = y + gi * (gh + g_gap)
        # 繪製圖表外框容器
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(T.LM), Inches(gy), Inches(left_w), Inches(gh))
        sh.fill.solid()
        sh.fill.fore_color.rgb = T.WHITE
        sh.line.color.rgb = T.RULE
        sh.line.width = Pt(1.0)
        sh.shadow.inherit = False

        # 標題與出處副標
        text_box(slide, T.LM + 0.14, gy + 0.08, left_w - 0.28, 0.28, grp["title"], size=13.5, color=T.INK, bold=True)
        bars = grp["bars"]
        nb = len(bars)
        avail_h = gh - 0.42
        bh = min(0.30, (avail_h - 0.08 * (nb - 1)) / nb)
        bar_gap = (avail_h - bh * nb) / max(1, nb)

        lab_w = 1.50
        track_w = 2.25
        val_w = left_w - 0.28 - lab_w - track_w - 0.12

        for bi, b in enumerate(bars):
            by = gy + 0.38 + bi * (bh + bar_gap)
            # 左側項目名
            text_box(
                slide, T.LM + 0.14, by, lab_w, bh,
                b["label"], size=11.5, color=T.GRAY, bold=True, anchor=MSO_ANCHOR.MIDDLE,
            )
            # 軌道底條
            tx = T.LM + 0.14 + lab_w
            tr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(tx), Inches(by + 0.02), Inches(track_w), Inches(bh - 0.04))
            tr.fill.solid()
            tr.fill.fore_color.rgb = T.GRAY_FILL
            tr.line.fill.background()
            tr.shadow.inherit = False

            # 比例實心長條
            ratio = max(0.05, min(1.0, float(b["ratio"])))
            b_kind = b.get("kind", "gray")
            bar_color = T.GREEN if b_kind == "green" else (T.ALERT if b_kind == "red" else (T.BLUE if b_kind == "blue" else (T.AMBER if b_kind == "amber" else (T.INK if b_kind == "dark" else T.MUTED))))
            fg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(tx), Inches(by + 0.02), Inches(track_w * ratio), Inches(bh - 0.04))
            fg.fill.solid()
            fg.fill.fore_color.rgb = bar_color
            fg.line.fill.background()
            fg.shadow.inherit = False

            # 右側數值與改善幅度標籤
            val_color = T.GREEN_TEXT if b_kind == "green" else (T.ALERT_TEXT if b_kind == "red" else (T.BLUE_TEXT if b_kind == "blue" else (T.AMBER_TEXT if b_kind == "amber" else T.INK)))
            text_box(
                slide, tx + track_w + 0.12, by, val_w, bh,
                b["value"], size=11.5, color=val_color, bold=True, anchor=MSO_ANCHOR.MIDDLE,
            )

    # 右側結構化論證面板
    nt = len(thesis)
    t_gap = 0.16
    th = (height - t_gap * (nt - 1)) / nt
    for ti, tc in enumerate(thesis):
        ty = y + ti * (th + t_gap)
        _draw_card(
            slide, rx, ty, right_w, th, tc.get("kind", "gray"), tc["title"], tc.get("body"),
            tfs=14.0, bfs=11.8, bullet=tc.get("bullet", True), valign=MSO_ANCHOR.MIDDLE, pad_x=0.12, pad_y=0.06,
        )

    return height


def timeline_diagram(
    slide: Any,
    y: float,
    tracks: Sequence[dict[str, Any]],
    height: float = 4.35,
) -> float:
    """雙軌時序軸與狀態推進閘門圖：視覺化展示同步波次推進、兩步探針切換或優雅關閉時間窗。"""
    nt = len(tracks)
    t_gap = 0.26
    th = (height - t_gap * (nt - 1)) / nt

    for ti, tr in enumerate(tracks):
        ty = y + ti * (th + t_gap)
        # 軌道背景框
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(T.LM), Inches(ty), Inches(T.W), Inches(th))
        bg.fill.solid()
        bg.fill.fore_color.rgb = T.ROW_ALT if ti % 2 == 0 else T.WHITE
        bg.line.color.rgb = T.RULE
        bg.line.width = Pt(1.0)
        bg.shadow.inherit = False

        # 軌道標題與論點說明
        text_box(slide, T.LM + 0.16, ty + 0.08, T.W - 0.32, 0.28, tr["title"], size=14.5, color=T.INK, bold=True)

        phases = tr["phases"]
        np = len(phases)
        px0 = T.LM + 0.18
        pw_total = T.W - 0.36
        p_gap = 0.34
        pw = (pw_total - p_gap * (np - 1)) / np
        py = ty + 0.42
        ph = th - 0.54

        for pi, ph_info in enumerate(phases):
            px = px0 + pi * (pw + p_gap)
            # 頂部時序／波次膠囊標籤
            tag_h = 0.28
            tag_kind = _pill_kind(ph_info.get("kind"))
            _pill(slide, px, py, pw, tag_h, ph_info["time"], kind=tag_kind, fs=11.0)

            # 下方階段卡片
            card_y = py + tag_h + 0.06
            card_h = ph - tag_h - 0.06
            _draw_card(
                slide, px, card_y, pw, card_h, ph_info.get("kind", "white" if ti % 2 == 0 else "gray"),
                ph_info["title"], ph_info.get("body"),
                tfs=13.5, bfs=11.5, bullet=ph_info.get("bullet", False), valign=MSO_ANCHOR.MIDDLE, pad_x=0.10, pad_y=0.04,
            )

            # 階段間推進箭頭
            if pi < np - 1:
                ay = card_y + card_h / 2
                seg(slide, px + pw + 0.03, ay, px + pw + p_gap - 0.03, ay, color=T.INK, weight=1.5, arrow=True)

    return height


def note(slide: Any, y: float, lines: Sequence[str], size: float = 14.5, bold: bool = False) -> float:
    """底部細線分隔重點總結列。"""
    line(slide, T.LM, y, T.W, color=T.RULE, weight=0.75)
    tb = slide.shapes.add_textbox(Inches(T.LM), Inches(y + 0.08), Inches(T.W), Inches(NOTE_H - 0.08))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.line_spacing = 1.15
    for l_text in lines:
        _runs(p, l_text, size, T.INK if bold else T.GRAY, bold=bold)
    return NOTE_H


def table(
    slide: Any,
    y: float,
    rows: list[list[str]],
    col_w: list[float],
    height: float = 4.20,
    highlight: set[int] | None = None,
    aligns: list[PP_ALIGN] | None = None,
    marks: dict[tuple[int, int], Any] | None = None,
    h: float | None = None,
) -> float:
    """現代專業細線表格：首列墨底白字，奇偶行白／淺灰交錯，細框線。

    儲存格可寫字串，或 `(字串, kind)` 做語義高亮（kind：green、red、blue、amber，字色隨語義、粗體）。
    `h` 固定整張表的高度（省略則依列數自動，單列至多 ROW_MAX_H）。
    """
    if h is not None:
        height = h
    nr, nc = len(rows), len(rows[0])
    row_h = min(ROW_MAX_H, height / nr)
    size = 13.5 if row_h >= 0.56 else 12.5
    scale = T.W / sum(col_w)
    col_w = [w * scale for w in col_w]
    h = row_h * nr
    gs = slide.shapes.add_table(nr, nc, Inches(T.LM), Inches(y), Inches(T.W), Inches(h))
    t = gs.table
    tblPr = gs._element.graphic.graphicData.tbl.tblPr
    tblPr.set("bandRow", "0")
    tblPr.set("firstRow", "0")
    for j, cw in enumerate(col_w):
        t.columns[j].width = Inches(cw)
    for i in range(nr):
        t.rows[i].height = Inches(row_h)
        for j in range(nc):
            c = t.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.10)
            c.margin_top = c.margin_bottom = Inches(0.04)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = aligns[j] if aligns else PP_ALIGN.LEFT
            p.line_spacing = 1.15
            head = i == 0
            hl = bool(highlight and i in highlight)
            text, tone = rows[i][j] if isinstance(rows[i][j], tuple) else (rows[i][j], None)
            text_color = T.WHITE if head else (marks or {}).get((i, j), _kind_head(tone))
            _runs(p, text, 13.0 if head else size, text_color, bold=head or hl or tone is not None, keep=tone is not None)
            c.fill.solid()
            if head:
                c.fill.fore_color.rgb = T.INK
            elif hl:
                c.fill.fore_color.rgb = T.GRAY_FILL
            elif i % 2 == 1:
                c.fill.fore_color.rgb = T.ROW_ALT
            else:
                c.fill.fore_color.rgb = T.WHITE
            _cell_border(c, color=T.INK if head else T.RULE)
    return h


def steps(slide: Any, y: float, items: Sequence[dict[str, Any]], height: float = 3.40) -> float:
    """序號步驟列：頂部細線、大號序號綠字、下方說明。"""
    n = len(items)
    gap = 0.25
    cw = (T.W - gap * (n - 1)) / n
    h = min(height, STEPS_MAX_H)
    for i, it in enumerate(items):
        x = T.LM + i * (cw + gap)
        line(slide, x, y, cw, color=T.ACCENT, weight=T.LINE_STRONG)
        text_box(slide, x, y + 0.15, cw, 0.70, str(it.get("num", i + 1)), size=38, color=T.ACCENT_TEXT, bold=True)
        text_box(slide, x, y + 0.92, cw, 0.45, it["title"], size=18.5, color=T.INK, bold=True)
        body = it.get("body", [])
        if body:
            lines = [body] if isinstance(body, str) else list(body)
            text_box(slide, x, y + 1.50, cw, h - 1.50, lines, size=14.0, color=T.GRAY, space=8)
    return h


def columns(slide: Any, y: float, cols: Sequence[dict[str, Any]], height: float = 3.60) -> float:
    """多欄對比框：頂部細線、大號綠/黑標題、短條列。"""
    n = len(cols)
    gap = 0.35
    cw = (T.W - gap * (n - 1)) / n
    h = min(height, COLUMNS_MAX_H)
    for i, col in enumerate(cols):
        x = T.LM + i * (cw + gap)
        top_color = _kind_line(col.get("kind"))
        line(slide, x, y, cw, color=top_color, weight=2.0)
        head_color = _kind_head(col.get("kind"))
        hfs = 18.5 if n >= 3 else 20.0
        bfs = 13.8 if n >= 3 else 14.5
        text_box(slide, x, y + 0.16, cw, 0.46, col["title"], size=hfs, color=head_color, bold=True)
        items = col.get("items", [])
        text_box(slide, x, y + 0.72, cw, h - 0.72, items, size=bfs, color=T.INK, bullet=True, space=8 if n >= 3 else 12)
    return h


# ---- 圖片與分層原語 ----

_ASSET_ROOT: Path | None = None  # 規格裡的圖片路徑相對於簡報目錄；render() 設定


def _image_aspect(path: Path) -> float:
    """高／寬。圖片只收路徑，不內嵌進引擎；缺檔就在建置時停下，不留空框。"""
    from PIL import Image

    with Image.open(path) as im:
        w, h = im.size
    return h / w


def _asset(rel: str) -> Path:
    root = _ASSET_ROOT or Path.cwd()
    p = (root / rel).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"簡報圖片不存在：{rel}（相對於 {root}）")
    return p


def shots(
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    side: Sequence[dict[str, Any]] | None = None,
    side_w: float = 3.85,
    cap_h: float | None = None,
    height: float = 4.35,
) -> float:
    """實際畫面截圖列：每張圖外加一圈細框，圖下一行「**標題**　說明」；可在右側放語義卡片。

    items：`{"image": 相對簡報目錄的路徑, "title": 標題, "body": 說明, "crop": 高／寬（選填）}`；多張圖等寬並排，
    依各自長寬比縮放；`crop` 只取畫面上緣、使高／寬等於該值（扁長版面用，不另存裁好的圖）。
    side：右側卡片（`kind`、`title`、`body`），與 arch_graph 的 side_thesis 同形。
    """
    has_side = bool(side)
    gap_side = 0.28 if has_side else 0.0
    area_w = T.W - (side_w + gap_side if has_side else 0.0)
    n = len(items)
    gap = 0.24
    cw = (area_w - gap * (n - 1)) / n
    cap = cap_h if cap_h is not None else (0.78 if n >= 3 else 0.56)
    used = 0.0
    for i, it in enumerate(items):
        full = _image_aspect(_asset(it["image"]))
        aspect = min(full, float(it["crop"])) if it.get("crop") else full  # crop：只取上緣、高／寬 = 此值
        iw = cw
        ih = iw * aspect
        if ih + cap > height:
            ih = height - cap
            iw = ih / aspect
        ix = T.LM + i * (cw + gap)
        pic = slide.shapes.add_picture(str(_asset(it["image"])), Inches(ix), Inches(y), Inches(iw), Inches(ih))
        if aspect < full:
            pic.crop_bottom = 1.0 - aspect / full
            pic.height = Inches(ih)
        frame = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(ix), Inches(y), Inches(iw), Inches(ih))
        frame.fill.background()
        frame.line.color.rgb = T.RULE
        frame.line.width = Pt(T.LINE_HAIR)
        frame.shadow.inherit = False
        label = f"**{it['title']}**　{it['body']}" if it.get("body") else f"**{it['title']}**"
        text_box(slide, ix, y + ih + 0.08, iw, cap - 0.08, label, size=12.0, color=T.GRAY)
        used = max(used, ih + cap)
    if has_side:
        sx = T.LM + area_w + gap_side
        nt = len(side)
        t_gap = 0.16
        th = (used - t_gap * (nt - 1)) / nt
        for i, tc in enumerate(side):
            _draw_card(
                slide, sx, y + i * (th + t_gap), side_w, th, tc.get("kind", "gray"), tc["title"], tc.get("body"),
                tfs=14.0, bfs=11.8, bullet=tc.get("bullet", False), valign=MSO_ANCHOR.MIDDLE, pad_x=0.12, pad_y=0.06,
            )
    return used


def layers(
    slide: Any,
    y: float,
    tiers: Sequence[dict[str, Any]],
    left_w: float = 4.6,
    height: float = 4.35,
) -> float:
    """分層金字塔：左側由窄到寬疊放的層（名稱與副名），右側各層的對應說明，以細虛線相連。"""
    n = len(tiers)
    gap = 0.10
    th = min(1.30, (height - gap * (n - 1)) / n)
    rx = T.LM + left_w + 0.55
    rw = T.RM - rx
    for i, t in enumerate(tiers):
        ty = y + i * (th + gap)
        frac = 0.50 + 0.50 * (i / max(1, n - 1))
        pw = left_w * frac
        px = T.LM + (left_w - pw) / 2
        kind = t.get("kind", "gray")
        _draw_card(
            slide, px, ty, pw, th, kind, t["name"], t.get("sub"),
            tfs=20.0, bfs=12.5, valign=MSO_ANCHOR.MIDDLE, pad_x=0.12, pad_y=0.04,
        )
        seg(slide, px + pw + 0.04, ty + th / 2, rx - 0.06, ty + th / 2, color=T.MUTED, weight=T.LINE_HAIR, dash=True, arrow=False)
        _draw_card(
            slide, rx, ty, rw, th, t.get("detail_kind", "white"), t["title"], t.get("body"),
            tfs=16.0, bfs=12.5, bullet=t.get("bullet", False), valign=MSO_ANCHOR.MIDDLE, pad_x=0.14, pad_y=0.06,
        )
    return n * th + (n - 1) * gap


BLOCKS = {
    "banner": banner,
    "cards": cards,
    "flow": flow,
    "swimlane": swimlane,
    "arch_graph": arch_graph,
    "bench_chart": bench_chart,
    "timeline_diagram": timeline_diagram,
    "table": table,
    "steps": steps,
    "columns": columns,
    "shots": shots,
    "layers": layers,
    "note": note,
}


def planned_height(kind: str, kw: dict[str, Any], share: float) -> float:
    """區塊在可用高度 share 下實際會畫多高（置中用）。"""
    if "h" in kw and kw["h"] is not None:
        return float(kw["h"]) + (0.30 if kw.get("caption") else 0.0)
    if kind == "banner":
        return float(kw.get("h", 0.68))
    if kind == "flow":
        return min(share, 2.20 + (0.30 if kw.get("caption") else 0.0))
    if kind == "cards":
        return min(share, CARD_MAX_H)
    if kind == "steps":
        return min(share, STEPS_MAX_H)
    if kind == "columns":
        return min(share, COLUMNS_MAX_H)
    if kind == "table":
        nr = len(kw["rows"])
        return min(ROW_MAX_H, share / nr) * nr
    return share


# ---- Presentation 主物件 ----

class Deck:
    def __init__(self, short_title: str) -> None:
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.blank = self.prs.slide_layouts[6]
        self.short = short_title
        self.n = 0

    def _new(self) -> Any:
        self.n += 1
        s = self.prs.slides.add_slide(self.blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = T.BG
        trans = etree.fromstring(
            '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" spd="med"><p:fade/></p:transition>'
        )
        s._element.append(trans)
        return s

    def cover(self, title: str, subtitle: str, category: str, meta: str = "", notes: str = "") -> None:
        s = self._new()
        text_box(s, T.LM, 0.6, 8, 0.3, category, size=12, color=T.ACCENT_TEXT, bold=True)
        text_box(s, T.LM, 2.3, T.W, 1.6, title, size=40, color=T.INK, bold=True, line_spacing=1.05)
        line(s, T.LM, 3.95, 1.5, color=T.ACCENT, weight=3)
        text_box(s, T.LM, 4.25, T.W, 0.5, subtitle, size=19, color=T.GRAY)
        line(s, T.LM, 6.00, T.W, color=T.RULE, weight=0.75)
        if meta:
            text_box(s, T.LM, 6.15, T.W, 0.4, meta, size=13.5, color=T.MUTED)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def slide(self, ref: str, title: str, blocks: Sequence[tuple[str, dict[str, Any]]], notes: str = "") -> None:
        s = self._new()
        text_box(s, T.LM, 0.46, 9.5, 0.25, ref, size=11, color=T.ACCENT_TEXT, bold=True)
        text_box(s, T.LM, 0.70, T.W, 0.82, title, size=25.5, color=T.INK, bold=True, line_spacing=1.05)
        main = [b for b in blocks if b[0] != "note"]
        tail = [b for b in blocks if b[0] == "note"]
        tail_h = (NOTE_H + GAP) if tail else 0.0
        avail = CONTENT_BOTTOM - T.TOP - tail_h

        # 計算固定高度區塊與彈性區塊配置
        fixed_total = 0.0
        flex_count = 0
        for kind, kw in main:
            if "h" in kw or kind == "banner":
                fixed_total += planned_height(kind, kw, avail)
            else:
                flex_count += 1
        rem = max(0.5, avail - fixed_total - GAP * max(0, len(main) - 1))
        flex_share = rem / max(1, flex_count)

        y = T.TOP
        if len(main) == 1:
            actual_h = planned_height(main[0][0], main[0][1], avail)
            y += max(0.0, (avail - actual_h) / 2)

        for kind, kw in main:
            share = planned_height(kind, kw, avail) if ("h" in kw or kind == "banner") else flex_share
            y += BLOCKS[kind](s, y, height=share, **kw) + GAP

        for kind, kw in tail:
            BLOCKS[kind](s, CONTENT_BOTTOM - NOTE_H, **kw)

        line(s, T.LM, 7.00, T.W, color=T.RULE, weight=0.75)
        text_box(s, T.LM, 7.08, 8, 0.25, self.short, size=10.5, color=T.MUTED)
        text_box(s, T.RM - 1.0, 7.08, 1.0, 0.25, str(self.n), size=10.5, color=T.MUTED, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def save(self, path: str) -> None:
        self.prs.save(path)


DEFAULTS = Path(__file__).with_name("defaults.toml")


def author_of(spec: dict[str, Any]) -> str:
    """封面的作者：規格有寫就用規格的（空字串＝沒有），沒寫用 `defaults.toml`，連它也沒有就是沒有。"""
    if "author" in spec:
        value = spec["author"]
    elif DEFAULTS.is_file():
        with DEFAULTS.open("rb") as f:
            value = tomllib.load(f).get("author", "")
    else:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"作者欄要是字串（空字串代表沒有）：{value!r}")
    return value


def render(spec: dict[str, Any], base_dir: Path | None = None) -> Deck:
    """由規格產出簡報。`base_dir` 是簡報目錄：規格裡的圖片路徑相對於它。"""
    global _ASSET_ROOT
    _ASSET_ROOT = Path(base_dir) if base_dir else None
    d = Deck(spec["short_title"])
    cover = dict(spec["cover"])
    cover.setdefault("meta", author_of(spec))  # 簡報封面不印日期
    d.cover(**cover)
    for s_info in spec["slides"]:
        ref, title, blocks, *extra = s_info
        notes = extra[0] if extra else ""
        d.slide(ref, title, blocks, notes=notes)
    return d


PRIMITIVES = BLOCKS  # 原語名稱 → 函式（lint 測試與擴充守則用）


def build(spec: dict[str, Any], out: str, base_dir: Path | None = None) -> int:
    """由規格寫出 PPTX，回傳頁數。base_dir 是 deck_spec.py 所在目錄（shots 的圖片路徑相對於它）。"""
    deck = render(spec, base_dir)
    deck.save(out)
    return deck.n
