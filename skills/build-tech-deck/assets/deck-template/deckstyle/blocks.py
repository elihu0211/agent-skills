"""圖表區塊：每個區塊把規格裡的一段資料畫成一組形狀，回傳實際佔用的高度（英吋）。

區塊的簽章是 `(slide, y, **規格欄位, height=可用高度)`；`BLOCKS` 把規格的區塊名稱對到函式，
`planned_height` 回答「在可用高度下這個區塊實際會畫多高」（Deck 用它配置固定與彈性區塊、單一區塊置中）。
新增一種區塊要同時改這裡（函式、`BLOCKS`、必要時 `planned_height`）、`spec.BLOCK_SCHEMA` 與匯出器 `outline.py`，
並在範本（`template/deck.yml`）加一頁示範；測試會檢查這幾處一致。
區塊內的局部尺寸（卡片內距、圖內間距）留在各函式，跨區塊共用的版面、字級與高度上限在設計參數（`design.yml`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import (
    XL_CHART_TYPE,
    XL_LABEL_POSITION,
    XL_LEGEND_POSITION,
    XL_MARKER_STYLE,
    XL_TICK_LABEL_POSITION,
)
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from .draw import (
    alt_text,
    badge,
    badge_fill,
    card,
    card_stack,
    cell_border,
    edge_overlay,
    kind_head,
    kind_line,
    line,
    pill,
    pill_kind,
    rect,
    runs,
    seg,
    split,
    text_box,
)
from .spec import SpecError, as_lines, check_table
from .theme import Theme

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}


def banner(
    t: Theme,
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
    card(t, slide, t.layout.left, y, t.layout.width, box_h, kind, title, body, tfs=tfs, bfs=bfs, valign=valign)
    return box_h


def cards(
    t: Theme,
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    height: float = 3.80,
    h: float | None = None,
    bullet: bool = True,
) -> float:
    n = len(items)
    box_h = h if h is not None else min(height, t.limits.card_max_h)
    tfs, bfs = (18.5, 14.5) if n <= 3 else (15.5, 12.5)
    if box_h < 2.2:
        tfs, bfs = (15.5, 12.5) if n <= 3 else (14.0, 11.5)
    for (x, cw), it in zip(split(t.layout.left, t.layout.width, n, 0.24), items, strict=True):
        card(
            t,
            slide,
            x,
            y,
            cw,
            box_h,
            it.get("kind", "gray"),
            it["title"],
            it.get("body"),
            tfs=tfs,
            bfs=bfs,
            bullet=it.get("bullet", bullet),
            valign=MSO_ANCHOR.MIDDLE,
        )
    return box_h


def flow(
    t: Theme,
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
    cap_h = t.limits.caption_h if caption else 0.0
    if caption:
        text_box(t, slide, t.layout.left, y, t.layout.width, 0.26, caption, size=13, color=t.gray, bold=True)
    n = len(items)
    gap = (0.68 if n <= 4 else 0.42) if edge_labels else 0.28
    box_h = h if h is not None else min(height - cap_h, t.limits.flow_max_h)
    by = y + cap_h
    tfs = 16.0 if n <= 4 else (14.5 if n == 5 else 13.5)
    bfs = 12.5 if n <= 4 else (11.5 if n == 5 else 11.0)
    for i, ((x, cw), it) in enumerate(zip(split(t.layout.left, t.layout.width, n, gap), items, strict=True)):
        card(
            t,
            slide,
            x,
            by,
            cw,
            box_h,
            it.get("kind", "gray"),
            it["title"],
            it.get("body"),
            tfs=tfs,
            bfs=bfs,
            bullet=False,
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.10,
        )
        if numbered:
            is_dark = it.get("kind") == "solid_dark"
            badge(
                t,
                slide,
                x + 0.04,
                by + 0.04,
                str(i + 1),
                fill=t.white if is_dark else t.ink,
                ink=t.ink if is_dark else t.white,
                line_color=t.ink,
                d=0.25,
                fs=t.type.label,
            )
        if i < n - 1:
            ay = by + box_h / 2
            seg(t, slide, x + cw + 0.04, ay, x + cw + gap - 0.04, ay)
            if edge_labels and i < len(edge_labels) and edge_labels[i]:
                text_box(
                    t,
                    slide,
                    x + cw + 0.02,
                    ay - 0.28,
                    gap - 0.04,
                    0.22,
                    edge_labels[i],
                    size=t.type.label,
                    color=t.accent_text,
                    bold=True,
                    align=PP_ALIGN.CENTER,
                )
    return cap_h + box_h


def swimlane(
    t: Theme,
    slide: Any,
    y: float,
    lanes: Sequence[dict[str, str]],
    steps: Sequence[dict[str, Any]],
    thesis: Sequence[dict[str, Any]] | None = None,
    height: float = 4.35,
) -> float:
    """跨泳道時序與控制流架構圖：奇偶交錯泳道 + 跨泳道折線箭頭 + 圓形序號徽章 + 下方論證卡片。"""
    nl = len(lanes)
    for k, st in enumerate(steps):
        if not 0 <= st["lane"] < nl:
            raise SpecError(
                f"步驟 {k + 1}「{st['title']}」的 lane={st['lane']} 超出泳道範圍 0–{nl - 1}（共 {nl} 條泳道）"
            )
    thesis_h = 1.12 if thesis else 0.0
    thesis_gap = 0.16 if thesis else 0.0
    lane_area_h = height - thesis_h - thesis_gap
    lh = lane_area_h / nl
    lab_w = 1.75

    # 1. 繪製泳道背景列與左側角色標題
    for i, ln_info in enumerate(lanes):
        ly = y + i * lh
        rect(
            t,
            slide,
            t.layout.left,
            ly,
            t.layout.width,
            lh,
            fill=t.row_alt if i % 2 == 0 else t.white,
            line_color=t.rule,
            weight=t.line_hair,
        )
        line(t, slide, t.layout.left + lab_w, ly, 0, color=t.rule, vertical=True, h=lh)  # 左側分隔線

        name = ln_info["name"]
        sub = ln_info.get("sub", "")
        text_box(
            t,
            slide,
            t.layout.left + 0.12,
            ly + 0.06,
            lab_w - 0.20,
            lh - 0.12,
            [f"**{name}**", sub] if sub else [f"**{name}**"],
            size=13.0,
            color=t.gray,
            anchor=MSO_ANCHOR.MIDDLE,
            space=2,
        )

    # 2. 計算每個步驟方塊的幾何座標
    ns = len(steps)
    gx = t.layout.left + lab_w + 0.12
    gw = t.layout.width - lab_w - 0.20
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
        edge_color = t.alert if is_blocked else (t.green if steps[k + 1].get("edge") == "green" else t.ink)
        is_dash = bool(steps[k + 1].get("dash", False) or is_blocked)
        if alane == blane:
            seg(t, slide, ax + bw + 0.02, ay_mid, bx - 0.03, ay_mid, color=edge_color, dash=is_dash)
        else:
            seg(t, slide, ax + bw, ay_mid, bx_mid, ay_mid, color=edge_color, dash=is_dash, arrow=False)
            y_end = by - 0.03 if blane > alane else by + bh + 0.03
            seg(t, slide, bx_mid, ay_mid, bx_mid, y_end, color=edge_color, dash=is_dash)

    # 4. 繪製步驟方塊與圓形序號徽章
    for k, st in enumerate(steps):
        sx, sy, _ = coords[k]
        kind = st.get("kind", "dark")
        card(
            t,
            slide,
            sx,
            sy,
            bw,
            bh,
            kind,
            st["title"],
            st.get("sub"),
            tfs=13.5,
            bfs=11.0,
            bullet=False,
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.08,
            pad_y=0.04,
        )
        is_solid = kind == "solid_dark"
        fill = badge_fill(t, kind)
        badge(
            t,
            slide,
            sx,
            sy,
            str(k + 1),
            fill=fill,
            ink=t.ink if is_solid else t.white,
            line_color=t.ink if is_solid else fill,
            d=0.25,
            fs=t.type.label,
        )

    # 5. 下方論證卡片列
    if thesis:
        ty = y + lane_area_h + thesis_gap
        for (tx, tcw), tc in zip(split(t.layout.left, t.layout.width, len(thesis), 0.20), thesis, strict=True):
            card(
                t,
                slide,
                tx,
                ty,
                tcw,
                thesis_h,
                tc.get("kind", "gray"),
                tc["title"],
                tc.get("body"),
                tfs=13.5,
                bfs=11.5,
                bullet=tc.get("bullet", False),
                valign=MSO_ANCHOR.MIDDLE,
                pad_x=0.10,
                pad_y=0.06,
            )

    return height


def arch_graph(
    t: Theme,
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
    side_w = t.layout.side_w if has_side else 0.0
    side_gap = t.layout.side_gap if has_side else 0.0
    graph_w = t.layout.width - side_w - side_gap

    hdr_h = 0.42 if col_headers else 0.0
    c_gap = 0.78 if (not has_side and cols == 3) else 0.68
    cw = (graph_w - c_gap * (cols - 1)) / cols
    for c_idx, h_text in enumerate(col_headers or []):
        text_box(
            t, slide, t.layout.left + c_idx * (cw + c_gap), y, cw, 0.28, h_text, size=12.5, color=t.muted, bold=True
        )

    gy = y + hdr_h
    gh = height - hdr_h
    r_gap = 0.34 if rows >= 3 else 0.42
    rh = (gh - r_gap * (rows - 1)) / rows

    def cell_rect(c: int, r: int, cs: int = 1, rs: int = 1) -> tuple[float, float, float, float]:
        rx = t.layout.left + c * (cw + c_gap)
        ry = gy + r * (rh + r_gap)
        rw = cs * cw + (cs - 1) * c_gap
        r_h = rs * rh + (rs - 1) * r_gap
        return rx, ry, rw, r_h

    # 1. 繪製背景區域容器（zones）
    for z in zones or []:
        zx, zy, zw, zh = cell_rect(z["col"], z["row"], z.get("col_span", 1), z.get("row_span", 1))
        pad = 0.10
        card(
            t,
            slide,
            zx - pad,
            zy - pad,
            zw + 2 * pad,
            zh + 2 * pad,
            z.get("kind", "gray"),
            z.get("title", ""),
            z.get("sub"),
            tfs=14.0,
            bfs=11.5,
            valign=MSO_ANCHOR.TOP,
            pad_x=0.12,
            pad_y=0.08,
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
        card(
            t,
            slide,
            nx,
            ny,
            nw,
            nh,
            nd.get("kind", "gray"),
            nd["title"],
            nd.get("sub"),
            tfs=nd.get("tfs", 14.5 if not has_side else 13.5),
            bfs=nd.get("bfs", 11.8 if not has_side else 11.2),
            bullet=nd.get("bullet", False),
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.10,
            pad_y=0.06,
        )
        if nd.get("badge"):
            b_str = str(nd["badge"])
            b_kind = nd.get("kind", "dark")
            if len(b_str) <= 2:
                badge(
                    t,
                    slide,
                    nx + 0.02,
                    ny + 0.02,
                    b_str,
                    fill=badge_fill(t, b_kind),
                    ink=t.ink if b_kind == "solid_dark" else t.white,
                    d=0.25,
                    fs=t.type.label,
                )
            else:
                pw = max(0.62, min(nw - 0.16, 0.16 + 0.11 * sum(1.35 if ord(c) > 127 else 0.72 for c in b_str)))
                pill(t, slide, nx + 0.06, ny - 0.11, pw, 0.22, b_str, kind=pill_kind(b_kind), fs=9.0)

    # 3. 繪製有向邊與邊標籤
    for ed in edges or []:
        for end in ("from", "to"):
            if ed[end] not in node_boxes:
                raise SpecError(
                    f"邊 {ed['from']}→{ed['to']} 的 {end} 不是節點 id：{ed[end]}（節點：{', '.join(node_boxes)}）"
                )
        ax, ay, aw, ah = node_boxes[ed["from"]]
        bx, by, bw, bh = node_boxes[ed["to"]]
        ekind = ed.get("kind", "solid")
        blocked = ekind == "blocked"
        ecolor = t.alert if blocked else (t.green if ekind == "green" else (t.muted if ekind == "dashed" else t.ink))
        edash = ekind in ("dashed", "blocked")
        label = ed.get("label")

        if abs((ay + ah / 2) - (by + bh / 2)) < 0.25:  # 水平連線
            my = (ay + ah / 2 + by + bh / 2) / 2
            x1, x2 = (ax + aw + 0.03, bx - 0.03) if bx > ax else (ax - 0.03, bx + bw + 0.03)
            seg(t, slide, x1, my, x2, my, color=ecolor, dash=edash)
            edge_overlay(
                t,
                slide,
                blocked,
                ecolor,
                ((x1 + x2) / 2, my),
                label,
                (min(x1, x2) - 0.22, my - (0.34 if blocked else 0.28), abs(x2 - x1) + 0.44, 0.22),
                align=PP_ALIGN.CENTER,
            )
        elif abs((ax + aw / 2) - (bx + bw / 2)) < 0.35:  # 垂直連線
            mx = (ax + aw / 2 + bx + bw / 2) / 2
            y1, y2 = (ay + ah + 0.03, by - 0.03) if by > ay else (ay - 0.03, by + bh + 0.03)
            seg(t, slide, mx, y1, mx, y2, color=ecolor, dash=edash)
            edge_overlay(
                t,
                slide,
                blocked,
                ecolor,
                (mx, (y1 + y2) / 2),
                label,
                (mx + (0.16 if blocked else 0.08), min(y1, y2), 1.80, abs(y2 - y1)),
                anchor=MSO_ANCHOR.MIDDLE,
            )
        else:  # L 型正交連線：由起點右側／左側水平連至終點中線，再垂直進入終點
            ay_m = ay + ah / 2
            bx_m = bx + bw / 2
            x_start = (ax + aw + 0.02) if bx_m > ax + aw / 2 else (ax - 0.02)
            y_end = (by - 0.03) if by > ay else (by + bh + 0.03)
            seg(t, slide, x_start, ay_m, bx_m, ay_m, color=ecolor, dash=edash, arrow=False)
            seg(t, slide, bx_m, ay_m, bx_m, y_end, color=ecolor, dash=edash)
            edge_overlay(
                t,
                slide,
                blocked,
                ecolor,
                (bx_m, (ay_m + y_end) / 2),
                label,
                (min(x_start, bx_m), ay_m - 0.25, abs(bx_m - x_start), 0.22),
                align=PP_ALIGN.CENTER,
            )

    # 4. 右側結構化論證面板（side_thesis）
    if side_thesis:
        card_stack(t, slide, t.layout.left + graph_w + side_gap, y, side_w, height, side_thesis, bullet=True)

    return height


def _bar_color(t: Theme, kind: str) -> Any:
    """長條色：語義 kind 取線色，dark 用墨色，其餘（含 gray）用次要灰。"""
    if kind in t.tones:
        return t.tones[kind].line
    return t.ink if kind == "dark" else t.muted


def bench_chart(
    t: Theme,
    slide: Any,
    y: float,
    groups: Sequence[dict[str, Any]],
    thesis: Sequence[dict[str, Any]],
    height: float = 4.35,
) -> float:
    """量化實測橫向長條圖（左）＋ 結構化 DSRM 論證面板（右）。"""
    left_w = 6.65
    gap = 0.30
    right_w = t.layout.width - left_w - gap
    rx = t.layout.left + left_w + gap

    for (gy, gh), grp in zip(split(y, height, len(groups), 0.18), groups, strict=True):
        # 繪製圖表外框容器
        rect(t, slide, t.layout.left, gy, left_w, gh, fill=t.white, line_color=t.rule)

        # 標題與出處副標
        text_box(
            t,
            slide,
            t.layout.left + 0.14,
            gy + 0.08,
            left_w - 0.28,
            0.28,
            grp["title"],
            size=13.5,
            color=t.ink,
            bold=True,
        )
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
                t,
                slide,
                t.layout.left + 0.14,
                by,
                lab_w,
                bh,
                b["label"],
                size=11.5,
                color=t.gray,
                bold=True,
                anchor=MSO_ANCHOR.MIDDLE,
            )
            # 軌道底條與比例實心長條
            tx = t.layout.left + 0.14 + lab_w
            rect(t, slide, tx, by + 0.02, track_w, bh - 0.04, fill=t.gray_fill)
            ratio = max(0.05, min(1.0, float(b["ratio"])))
            b_kind = b.get("kind", "gray")
            rect(t, slide, tx, by + 0.02, track_w * ratio, bh - 0.04, fill=_bar_color(t, b_kind))

            # 右側數值與改善幅度標籤
            text_box(
                t,
                slide,
                tx + track_w + 0.12,
                by,
                val_w,
                bh,
                b["value"],
                size=11.5,
                color=kind_head(t, b_kind),
                bold=True,
                anchor=MSO_ANCHOR.MIDDLE,
            )

    # 右側結構化 DSRM 論證面板
    card_stack(t, slide, rx, y, right_w, height, thesis, bullet=True)

    return height


def timeline_diagram(
    t: Theme,
    slide: Any,
    y: float,
    tracks: Sequence[dict[str, Any]],
    height: float = 4.35,
) -> float:
    """雙軌時序軸與狀態推進閘門圖：視覺化展示同步波次推進、兩步探針切換或優雅關閉時間窗。"""
    for ti, ((ty, th), tr) in enumerate(zip(split(y, height, len(tracks), 0.26), tracks, strict=True)):
        # 軌道背景框與標題
        rect(
            t,
            slide,
            t.layout.left,
            ty,
            t.layout.width,
            th,
            fill=t.row_alt if ti % 2 == 0 else t.white,
            line_color=t.rule,
        )
        text_box(
            t,
            slide,
            t.layout.left + 0.16,
            ty + 0.08,
            t.layout.width - 0.32,
            0.28,
            tr["title"],
            size=14.5,
            color=t.ink,
            bold=True,
        )

        phases = tr["phases"]
        py = ty + 0.42
        ph = th - 0.54
        p_gap = 0.34
        for pi, ((px, pw), ph_info) in enumerate(
            zip(split(t.layout.left + 0.18, t.layout.width - 0.36, len(phases), p_gap), phases, strict=True)
        ):
            # 頂部時序／波次膠囊標籤
            tag_h = 0.28
            pill(t, slide, px, py, pw, tag_h, ph_info["time"], kind=pill_kind(ph_info.get("kind")), fs=11.0)

            # 下方階段卡片
            card_y = py + tag_h + 0.06
            card_h = ph - tag_h - 0.06
            card(
                t,
                slide,
                px,
                card_y,
                pw,
                card_h,
                ph_info.get("kind", "white" if ti % 2 == 0 else "gray"),
                ph_info["title"],
                ph_info.get("body"),
                tfs=13.5,
                bfs=11.5,
                bullet=ph_info.get("bullet", False),
                valign=MSO_ANCHOR.MIDDLE,
                pad_x=0.10,
                pad_y=0.04,
            )

            # 階段間推進箭頭
            if pi < len(phases) - 1:
                ay = card_y + card_h / 2
                seg(t, slide, px + pw + 0.03, ay, px + pw + p_gap - 0.03, ay)

    return height


def note(t: Theme, slide: Any, y: float, lines: Sequence[str], size: float | None = None, bold: bool = False) -> float:
    """底部細線分隔重點總結列。"""
    size = t.type.note if size is None else size
    line(t, slide, t.layout.left, y, t.layout.width)
    tb = slide.shapes.add_textbox(
        Inches(t.layout.left), Inches(y + 0.08), Inches(t.layout.width), Inches(t.layout.note_h - 0.08)
    )
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.line_spacing = 1.15
    for l_text in lines:
        runs(t, p, l_text, size, t.ink if bold else t.gray, bold=bold)
    return t.layout.note_h


def _cell_text(cell: Any) -> str:
    return cell[0] if isinstance(cell, list) else str(cell)


def table(
    t: Theme,
    slide: Any,
    y: float,
    rows: list[list[str]],
    col_w: list[float],
    height: float = 4.20,
    highlight: set[int] | None = None,
    aligns: Sequence[str] | None = None,
    h: float | None = None,
) -> float:
    """現代專業細線表格：首列墨底白字，奇偶行白／淺灰交錯，細框線。

    儲存格可寫字串，或 `(字串, kind)` 做語義高亮（kind：green、red、blue、amber，字色隨語義、粗體）。
    `aligns` 每欄一個 left／center／right；`h` 固定整張表的高度（省略則依列數自動，單列至多 t.limits.row_max_h）。
    """
    check_table(rows, col_w)
    if h is not None:
        height = h
    nr, nc = len(rows), len(rows[0])
    row_h = min(t.limits.row_max_h, height / nr)
    size = 13.5 if row_h >= 0.56 else 12.5
    scale = t.layout.width / sum(col_w)
    h = row_h * nr
    gs = slide.shapes.add_table(nr, nc, Inches(t.layout.left), Inches(y), Inches(t.layout.width), Inches(h))
    alt_text(gs, "表格：" + "、".join(_cell_text(c) for c in rows[0]))
    tbl = gs.table
    tbl_pr = gs._element.graphic.graphicData.tbl.tblPr
    tbl_pr.set("bandRow", "0")
    tbl_pr.set("firstRow", "0")
    for j, w in enumerate(col_w):
        tbl.columns[j].width = Inches(w * scale)
    for i in range(nr):
        tbl.rows[i].height = Inches(row_h)
        for j in range(nc):
            c = tbl.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.10)
            c.margin_top = c.margin_bottom = Inches(0.04)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = _ALIGN[aligns[j]] if aligns else PP_ALIGN.LEFT
            p.line_spacing = 1.15
            head = i == 0
            hl = bool(highlight and i in highlight)
            text, tone = rows[i][j] if isinstance(rows[i][j], list) else (rows[i][j], None)
            text_color = t.white if head else kind_head(t, tone)
            runs(
                t,
                p,
                text,
                13.0 if head else size,
                text_color,
                bold=head or hl or tone is not None,
                keep=tone is not None,
            )
            c.fill.solid()
            if head:
                c.fill.fore_color.rgb = t.ink
            elif hl:
                c.fill.fore_color.rgb = t.gray_fill
            elif i % 2 == 1:
                c.fill.fore_color.rgb = t.row_alt
            else:
                c.fill.fore_color.rgb = t.white
            cell_border(t, c, color=t.ink if head else t.rule)
    return h


def steps(t: Theme, slide: Any, y: float, items: Sequence[dict[str, Any]], height: float = 3.40) -> float:
    """序號步驟列：頂部細線、大號序號綠字、下方說明。"""
    h = min(height, t.limits.steps_max_h)
    for i, ((x, cw), it) in enumerate(zip(split(t.layout.left, t.layout.width, len(items), 0.25), items, strict=True)):
        line(t, slide, x, y, cw, color=t.accent, weight=t.line_strong)
        text_box(t, slide, x, y + 0.15, cw, 0.70, str(it.get("num", i + 1)), size=38, color=t.accent_text, bold=True)
        text_box(t, slide, x, y + 0.92, cw, 0.45, it["title"], size=18.5, color=t.ink, bold=True)
        if body := as_lines(it.get("body")):
            text_box(t, slide, x, y + 1.50, cw, h - 1.50, body, size=14.0, color=t.gray, space=8)
    return h


def columns(t: Theme, slide: Any, y: float, cols: Sequence[dict[str, Any]], height: float = 3.60) -> float:
    """多欄對比框：頂部細線、大號綠/黑標題、短條列。"""
    n = len(cols)
    h = min(height, t.limits.columns_max_h)
    for (x, cw), col in zip(split(t.layout.left, t.layout.width, n, 0.35), cols, strict=True):
        line(t, slide, x, y, cw, color=kind_line(t, col.get("kind")), weight=2.0)
        text_box(
            t,
            slide,
            x,
            y + 0.16,
            cw,
            0.46,
            col["title"],
            size=18.5 if n >= 3 else 20.0,
            color=kind_head(t, col.get("kind")),
            bold=True,
        )
        text_box(
            t,
            slide,
            x,
            y + 0.72,
            cw,
            h - 0.72,
            as_lines(col.get("items")),
            size=13.8 if n >= 3 else 14.5,
            color=t.ink,
            bullet=True,
            space=8 if n >= 3 else 12,
        )
    return h


def _image_aspect(path: Path) -> float:
    """高／寬。圖片只收路徑，不內嵌進引擎；缺檔就在建置時停下，不留空框。"""
    from PIL import Image

    with Image.open(path) as im:
        w, h = im.size
    return h / w


def _asset(assets: Path, rel: str) -> Path:
    p = (assets / rel).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"簡報圖片不存在：{rel}（相對於 {assets}）")
    return p


def shots(
    t: Theme,
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    side: Sequence[dict[str, Any]] | None = None,
    side_w: float | None = None,
    cap_h: float | None = None,
    height: float = 4.35,
    *,
    assets: Path,
) -> float:
    """實際畫面截圖列：每張圖外加一圈細框，圖下一行「**標題**　說明」；可在右側放語義卡片。

    items：`{"image": 相對簡報目錄的路徑, "title": 標題, "body": 說明, "crop": 高／寬（選填）}`；多張圖等寬並排，
    依各自長寬比縮放；`crop` 只取畫面上緣、使高／寬等於該值（扁長版面用，不另存裁好的圖）。
    side：右側卡片（`kind`、`title`、`body`），與 arch_graph 的 side_thesis 同形。
    `assets` 是簡報目錄，圖片路徑相對於它（Deck 帶入，規格不寫）。
    """
    has_side = bool(side)
    side_w = t.layout.side_w if side_w is None else side_w
    gap_side = t.layout.side_gap if has_side else 0.0
    area_w = t.layout.width - (side_w + gap_side if has_side else 0.0)
    cap = cap_h if cap_h is not None else (0.78 if len(items) >= 3 else 0.56)
    used = 0.0
    for (ix, cw), it in zip(split(t.layout.left, area_w, len(items), 0.24), items, strict=True):
        path = _asset(assets, it["image"])
        full = _image_aspect(path)
        aspect = min(full, float(it["crop"])) if it.get("crop") else full  # crop：只取上緣、高／寬 = 此值
        iw = cw
        ih = iw * aspect
        if ih + cap > height:
            ih = height - cap
            iw = ih / aspect
        pic = slide.shapes.add_picture(str(path), Inches(ix), Inches(y), Inches(iw), Inches(ih))
        alt_text(pic, it.get("alt") or "：".join(x for x in (it["title"], it.get("body")) if x))
        if aspect < full:
            pic.crop_bottom = 1.0 - aspect / full
            pic.height = Inches(ih)
        rect(t, slide, ix, y, iw, ih, line_color=t.rule, weight=t.line_hair)
        label = f"**{it['title']}**　{it['body']}" if it.get("body") else f"**{it['title']}**"
        text_box(t, slide, ix, y + ih + 0.08, iw, cap - 0.08, label, size=12.0, color=t.gray)
        used = max(used, ih + cap)
    if has_side:
        card_stack(t, slide, t.layout.left + area_w + gap_side, y, side_w, used, side, bullet=False)
    return used


def layers(
    t: Theme,
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
    rx = t.layout.left + left_w + 0.55
    rw = t.layout.right - rx
    for i, tier in enumerate(tiers):
        ty = y + i * (th + gap)
        frac = 0.50 + 0.50 * (i / max(1, n - 1))
        pw = left_w * frac
        px = t.layout.left + (left_w - pw) / 2
        card(
            t,
            slide,
            px,
            ty,
            pw,
            th,
            tier.get("kind", "gray"),
            tier["name"],
            tier.get("sub"),
            tfs=20.0,
            bfs=12.5,
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.12,
            pad_y=0.04,
        )
        seg(
            t,
            slide,
            px + pw + 0.04,
            ty + th / 2,
            rx - 0.06,
            ty + th / 2,
            color=t.muted,
            weight=t.line_hair,
            dash=True,
            arrow=False,
        )
        card(
            t,
            slide,
            rx,
            ty,
            rw,
            th,
            tier.get("detail_kind", "white"),
            tier["title"],
            tier.get("body"),
            tfs=16.0,
            bfs=12.5,
            bullet=tier.get("bullet", False),
            valign=MSO_ANCHOR.MIDDLE,
            pad_x=0.14,
            pad_y=0.06,
        )
    return n * th + (n - 1) * gap


def kpi(
    t: Theme,
    slide: Any,
    y: float,
    items: Sequence[dict[str, Any]],
    height: float = 2.0,
    h: float | None = None,
) -> float:
    """大數字列：每項頂端一條語義色粗線，下面是大數字、白話標題與一行副說明。

    items：`{"value": 大數字, "label": 標題, "sub": 副說明（選填）, "kind": 語義色（選填，預設墨色）}`。
    項數越多數字越小（4 項縮到 85%、5 項以上縮到 70%），讓一列放得下。
    """
    n = len(items)
    box_h = h if h is not None else min(height, t.limits.kpi_max_h)
    vsize = t.type.kpi_value * (1.0 if n <= 3 else 0.85 if n == 4 else 0.70)
    for (x, cw), it in zip(split(t.layout.left, t.layout.width, n, 0.30), items, strict=True):
        kind = it.get("kind")
        line(t, slide, x, y, cw, color=kind_line(t, kind), weight=2.0)
        text_box(
            t,
            slide,
            x,
            y + 0.14,
            cw,
            vsize / 72 * 1.3,
            it["value"],
            size=vsize,
            color=kind_head(t, kind),
            bold=True,
            line_spacing=1.0,
        )
        ty = y + 0.14 + vsize / 72 * 1.3 + 0.10
        text_box(t, slide, x, ty, cw, 0.36, it["label"], size=16.0, color=t.ink, bold=True)
        if it.get("sub"):
            text_box(
                t,
                slide,
                x,
                ty + 0.40,
                cw,
                max(0.3, box_h - (ty - y) - 0.40),
                as_lines(it["sub"]),
                size=12.5,
                color=t.gray,
                space=4,
            )
    return box_h


_CHART_TYPES = {
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "pie": XL_CHART_TYPE.PIE,
}


_CHART_NAMES = {"column": "直條圖", "bar": "橫條圖", "line": "折線圖", "pie": "圓餅圖"}


def _series_color(t: Theme, it: dict[str, Any], k: int) -> Any:
    """系列色：指定語義 kind 取該色，否則依 SERIES_CYCLE 輪替。"""
    return kind_line(t, it["kind"]) if it.get("kind") else t.series_cycle[k % len(t.series_cycle)]


def chart(
    t: Theme,
    slide: Any,
    y: float,
    categories: Sequence[str],
    series: Sequence[dict[str, Any]],
    type: str = "column",
    title: str = "",
    fmt: str = "General",
    legend: bool | None = None,
    labels: bool = True,
    vmin: float | None = None,
    vmax: float | None = None,
    side: Sequence[dict[str, Any]] | None = None,
    side_w: float | None = None,
    height: float = 4.35,
    h: float | None = None,
) -> float:
    """原生圖表（可在 PowerPoint 裡編輯資料）：直條（column）、橫條（bar）、折線（line）、圓餅（pie）。

    series：`{"name": 系列名, "values": [數字…], "kind": 語義色（選填，省略則依色票輪替）}`，值的個數須等於類別數；
    圓餅只收一個系列，每個類別依色票輪替上色。`fmt` 是資料標籤與數值軸的數字格式（如 `0.0%`、`#,##0`）；
    `legend` 省略時，多系列或圓餅才顯示。`side` 與 arch_graph 的 side_thesis 同形，放在右側。
    """
    if type not in _CHART_TYPES:
        raise SpecError(f"chart 的 type 須為 {', '.join(_CHART_TYPES)}：{type!r}")
    for it in series:
        if len(it["values"]) != len(categories):
            raise SpecError(f"系列「{it['name']}」有 {len(it['values'])} 個值，但有 {len(categories)} 個類別")
    if type == "pie" and len(series) != 1:
        raise SpecError(f"圓餅圖只收一個系列，拿到 {len(series)} 個")
    if vmin is not None and vmax is not None and vmin >= vmax:
        raise SpecError(f"vmin（{vmin}）須小於 vmax（{vmax}）")
    box_h = h if h is not None else min(height, t.limits.chart_max_h)
    side_w = t.layout.side_w if side_w is None else side_w
    area_w = t.layout.width - ((side_w + t.layout.side_gap) if side else 0.0)
    top = y
    if title:
        text_box(t, slide, t.layout.left, y, area_w, 0.28, title, size=13.5, color=t.ink, bold=True)
        top += 0.34
    data = CategoryChartData()
    data.categories = list(categories)
    for it in series:
        data.add_series(it["name"], [float(v) for v in it["values"]])
    gf = slide.shapes.add_chart(
        _CHART_TYPES[type], Inches(t.layout.left), Inches(top), Inches(area_w), Inches(box_h - (top - y)), data
    )
    alt_text(
        gf,
        f"{title or '圖表'}（{_CHART_NAMES[type]}）：類別 {'、'.join(categories)}；系列 {'、'.join(i['name'] for i in series)}",
    )
    ch = gf.chart
    ch.font.size = Pt(12)  # 字型繼承主題
    ch.font.color.rgb = t.gray
    ch.has_title = False
    ch.has_legend = (len(series) > 1 or type == "pie") if legend is None else legend
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(12)
    plot = ch.plots[0]
    if type != "pie":
        va, ca = ch.value_axis, ch.category_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = t.rule
        va.major_gridlines.format.line.width = Pt(t.line_hair)
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(11)
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = fmt, False
        if vmin is not None:
            va.minimum_scale = vmin
        if vmax is not None:
            va.maximum_scale = vmax
        ca.format.line.color.rgb = t.rule
        ca.tick_labels.font.size = Pt(12)
        ca.has_major_gridlines = False
        ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        if type == "bar":
            ca.reverse_order = True
    if type in ("column", "bar"):
        plot.gap_width = 60
        if len(series) > 1:
            plot.overlap = -5
    for k, (it, s) in enumerate(zip(series, plot.series, strict=True)):
        color = _series_color(t, it, k)
        if type == "line":
            s.format.line.color.rgb = color
            s.format.line.width = Pt(2.25)
            s.smooth = False
            s.marker.style = XL_MARKER_STYLE.CIRCLE
            s.marker.size = 7
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = color
            s.marker.format.line.color.rgb = color
        elif type == "pie":
            for i in range(len(categories)):
                pt = s.points[i]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = t.series_cycle[i % len(t.series_cycle)]
                pt.format.line.color.rgb = t.white
        else:
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = color
        if labels:
            dl = s.data_labels
            dl.show_value = True
            dl.number_format, dl.number_format_is_linked = fmt, False
            dl.font.size = Pt(11)
            dl.font.color.rgb = t.ink
            dl.position = {
                "line": XL_LABEL_POSITION.ABOVE,
                "pie": XL_LABEL_POSITION.OUTSIDE_END,
            }.get(type, XL_LABEL_POSITION.OUTSIDE_END)
    if side:
        card_stack(t, slide, t.layout.left + area_w + t.layout.side_gap, y, side_w, box_h, side, bullet=False)
    return box_h


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
    "kpi": kpi,
    "chart": chart,
    "note": note,
}


def planned_height(t: Theme, kind: str, kw: dict[str, Any], share: float) -> float:
    """區塊在可用高度 share 下實際會畫多高（置中用）。"""
    if "h" in kw and kw["h"] is not None:
        return float(kw["h"]) + (t.limits.caption_h if kw.get("caption") else 0.0)
    if kind == "banner":
        return float(kw.get("h", 0.68))
    if kind == "flow":
        return min(share, t.limits.flow_max_h + (t.limits.caption_h if kw.get("caption") else 0.0))
    if kind == "cards":
        return min(share, t.limits.card_max_h)
    if kind == "steps":
        return min(share, t.limits.steps_max_h)
    if kind == "columns":
        return min(share, t.limits.columns_max_h)
    if kind == "kpi":
        return min(share, t.limits.kpi_max_h)
    if kind == "chart":
        return min(share, t.limits.chart_max_h)
    if kind == "table":
        nr = len(kw["rows"])  # 空表格由 table() 回報，這裡只防除以零
        return min(t.limits.row_max_h, share / max(1, nr)) * nr
    return share
