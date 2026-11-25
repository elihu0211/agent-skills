"""節點圖模式：層帶裡的節點照格線擺放，連線以直角折線接在節點邊上。

位置與走線由規格宣告，引擎不自動排版；擺不乾淨（線穿過方塊、標籤壓到東西、兩條線疊在一起）就逐條列出並停下。
無法避免的交叉在橫線上畫跳線弧，讀者才分得出兩條線沒有相接。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from base import (
    HEAD_Y,
    INK,
    LABEL_GAP,
    LABEL_W,
    MARGIN,
    MUTE,
    PALETTE,
    Canvas,
    Issue,
    draw_band_frame,
    draw_footer,
    draw_title,
    is_text,
    width,
    wrap_svg,
)

GRID = 48
MAX_LINES, EXTRA_LINE_H = 6, 27
NODE_LINE_Y = {1: (42,), 2: (37, 66), 3: (36, 66, 93)}
# 節點內各行的字級與字重：標題、說明（灰）、accent 時最後一行改用節點色加粗
TITLE_STYLE, DETAIL_STYLE, ACCENT_STYLE = (22, 800), (17, 600), (17, 800)
# 旁註：每一行同字級，不分標題
CALLOUT_LINE_H, CALLOUT_PAD = 27, 22
GROUP_PAD, GROUP_TITLE_H, GROUP_TITLE_SIZE = 16, 48, 21
ROW_GAP, BAND_PAD, BAND_GAP, BAND_MIN_H = 52, 24, 52, 132
NAME_SIZE, EN_SIZE, NOTE_SIZE = 28, 20, 17
SIDES = ("top", "bottom", "left", "right")
EDGE_INK, EDGE_PILL_LINE = "#2F3A4C", "#CBD2DC"
# 線寬、箭頭長、箭頭半寬
WEIGHTS = {"normal": (2.4, 13, 7), "thick": (6.0, 20, 11)}
PILL_SIZE, PILL_LINE_H, PILL_PAD = 18, 24, 26
CORNER, HOP = 10, 9
DEPTH = 46

TOP_KEYS = {"title", "subtitle", "footer", "width", "grid", "bands", "edges"}
BAND_KEYS = {"color", "name", "en", "note", "dashed", "rows", "groups", "pad", "row_gap", "gap"}
NODE_KEYS = {"id", "at", "text", "color", "dashed", "strong", "accent", "callout"}
EDGE_KEYS = {
    "from", "to", "label", "label_color", "style", "weight", "arrow", "color", "channel", "depth", "label_at", "shift"
}
GROUP_KEYS = {"id", "title", "wraps", "color", "dashed"}


def is_graph(spec) -> bool:
    if not isinstance(spec, dict):
        return False
    bands = spec.get("bands")
    return "edges" in spec or (isinstance(bands, list) and any(isinstance(b, dict) and "rows" in b for b in bands))


# ---------- 規格 ----------


def _num(v, low: float, high: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and low <= v <= high


def _unknown(raw: dict, known: set[str], where: str, issues: list[Issue]) -> None:
    for key in raw.keys() - known:
        issues.append(Issue("schema", f"{where}.{key}", f"不認得的鍵；可用：{', '.join(sorted(known))}"))


def _lines(v, most: int) -> list[str] | None:
    """字串或 1–most 行的字串清單。"""
    lines = [v] if isinstance(v, str) else v
    if isinstance(lines, list) and 1 <= len(lines) <= most and all(is_text(s) for s in lines):
        return [s.strip() for s in lines]
    return None


def _node(raw, where: str, grid: int, band_color: str, band_dashed: bool, issues: list[Issue]) -> dict | None:
    if not isinstance(raw, dict):
        issues.append(Issue("schema", where, "節點要是對照表：{id, at, text}"))
        return None
    _unknown(raw, NODE_KEYS, where, issues)
    ok = True
    if not is_text(raw.get("id")) or any(ch in raw.get("id", "") for ch in ".@ "):
        issues.append(Issue("schema", f"{where}.id", "必填：不含空白、「.」與「@」的字串"))
        ok = False
    at = raw.get("at")
    if not (isinstance(at, list) and len(at) == 2 and _num(at[0], 1, grid + 1) and _num(at[1], 1, grid)):
        issues.append(Issue("schema", f"{where}.at", f"必填：[起始欄, 欄寬]，格線共 {grid} 欄、從 1 起"))
        ok = False
    elif at[0] + at[1] > grid + 1:
        issues.append(Issue("schema", f"{where}.at", f"超出格線：起始欄加欄寬最多 {grid + 1}"))
        ok = False
    text = _lines(raw.get("text"), MAX_LINES)
    if text is None:
        issues.append(Issue("schema", f"{where}.text", f"必填：1–{MAX_LINES} 行字串，第一行是標題"))
        ok = False
    accent = raw.get("accent", False)
    if accent is True:
        accent = [len(text or [])]
    elif accent is False:
        accent = []
    elif not isinstance(accent, list):
        accent = [accent]
    if text and not all(isinstance(n, int) and 1 <= n <= len(text) for n in accent):
        issues.append(Issue("schema", f"{where}.accent", "要是 true、行號或行號清單（從 1 起，不超過行數）"))
        ok = False
    color = raw.get("color", band_color)
    if color not in PALETTE:
        issues.append(Issue("schema", f"{where}.color", f"色票只有：{', '.join(PALETTE)}"))
        ok = False
    for key in ("dashed", "strong", "callout"):
        if key in raw and not isinstance(raw[key], bool):
            issues.append(Issue("schema", f"{where}.{key}", "要是 true 或 false"))
    if not ok:
        return None
    return {
        "id": raw["id"],
        "at": at,
        "text": text,
        "color": color,
        "dashed": bool(raw.get("dashed", band_dashed)),
        "strong": bool(raw.get("strong", False)),
        "accent": accent,
        "callout": bool(raw.get("callout", False)),
    }


def _group(raw, where: str, members_here: set[str], band_color: str, issues: list[Issue]) -> dict | None:
    if not isinstance(raw, dict):
        issues.append(Issue("schema", where, "群組要是對照表：{id, title, wraps}"))
        return None
    _unknown(raw, GROUP_KEYS, where, issues)
    wraps = raw.get("wraps")
    color = raw.get("color", band_color)
    if not is_text(raw.get("id")) or not is_text(raw.get("title")):
        issues.append(Issue("schema", where, "群組要有 id 與 title"))
    elif not isinstance(wraps, list) or not wraps or not all(w in members_here for w in wraps):
        issues.append(Issue("schema", f"{where}.wraps", "要是同一層裡的節點 id 清單"))
    elif color not in PALETTE:
        issues.append(Issue("schema", f"{where}.color", f"色票只有：{', '.join(PALETTE)}"))
    else:
        return {"id": raw["id"], "title": raw["title"], "wraps": wraps, "color": color,
                "dashed": raw.get("dashed") is True}
    return None


def _port(v, where: str, ids: set[str], issues: list[Issue]) -> tuple[str, str | None, float | None] | None:
    """解析「節點」、「節點.邊」或「節點.邊@位置」。"""
    if not is_text(v):
        issues.append(Issue("schema", where, "必填：節點 id，可接 .top／.bottom／.left／.right 與 @0–1"))
        return None
    head, _, frac = v.partition("@")
    node, _, side = head.partition(".")
    t = None
    if frac:
        try:
            t = float(frac)
        except ValueError:
            t = -1.0
    if node not in ids:
        issues.append(Issue("schema", where, f"沒有這個節點：{node}"))
    elif side and side not in SIDES:
        issues.append(Issue("schema", where, f"邊只有：{', '.join(SIDES)}"))
    elif t is not None and (not side or not 0 <= t <= 1):
        issues.append(Issue("schema", where, "@ 後面是 0–1 的位置，且要先寫是哪一邊"))
    else:
        return node, side or None, t
    return None


def _edge(raw, where: str, ids: set[str], issues: list[Issue]) -> dict | None:
    if not isinstance(raw, dict):
        issues.append(Issue("schema", where, "每條連線要是對照表：{from, to}"))
        return None
    _unknown(raw, EDGE_KEYS, where, issues)
    start = _port(raw.get("from"), f"{where}.from", ids, issues)
    end = _port(raw.get("to"), f"{where}.to", ids, issues)
    ok = start is not None and end is not None
    if ok and start[0] == end[0]:
        issues.append(Issue("schema", f"{where}.to", "起點和終點不能是同一個節點"))
        ok = False
    choices = {"style": ("solid", "dashed"), "weight": tuple(WEIGHTS), "arrow": ("end", "both", "none")}
    for key, allowed in choices.items():
        if raw.get(key, allowed[0]) not in allowed:
            issues.append(Issue("schema", f"{where}.{key}", f"只有：{', '.join(allowed)}"))
            ok = False
    for key in ("color", "label_color"):
        if key in raw and raw[key] not in PALETTE:
            issues.append(Issue("schema", f"{where}.{key}", f"色票只有：{', '.join(PALETTE)}"))
            ok = False
    for key, low, high in (("channel", 0, 1), ("label_at", 0, 1), ("depth", 16, 400)):
        if key in raw and not _num(raw[key], low, high):
            issues.append(Issue("schema", f"{where}.{key}", f"要是 {low}–{high} 的數字"))
            ok = False
    shift = raw.get("shift", [0, 0])
    if not (isinstance(shift, list) and len(shift) == 2 and all(_num(v, -600, 600) for v in shift)):
        issues.append(Issue("schema", f"{where}.shift", "要是 [橫移, 縱移]（像素）"))
        ok = False
    label = None
    if "label" in raw:
        label = _lines(raw["label"], 3)
        if label is None:
            issues.append(Issue("schema", f"{where}.label", "要是字串或 1–3 行字串清單"))
            ok = False
    if not ok:
        return None
    return {
        "from": start,
        "to": end,
        "label": label,
        "dashed": raw.get("style") == "dashed",
        "weight": raw.get("weight", "normal"),
        "arrow": raw.get("arrow", "end"),
        "color": raw.get("color"),
        "label_color": raw.get("label_color", raw.get("color")),
        "channel": raw.get("channel", 0.5),
        "depth": raw.get("depth", DEPTH),
        "label_at": raw.get("label_at"),
        "shift": shift,
        "where": where,
    }


def validate(spec: dict) -> tuple[dict, list[Issue]]:
    issues: list[Issue] = []
    _unknown(spec, TOP_KEYS, "(root)", issues)
    if not is_text(spec.get("title")):
        issues.append(Issue("schema", "title", "必填：圖的標題"))
    for key in ("subtitle", "footer"):
        if key in spec and not is_text(spec[key]):
            issues.append(Issue("schema", key, "要是非空字串"))
    w = spec.get("width", 2200)
    if not isinstance(w, int) or not 1200 <= w <= 4000:
        issues.append(Issue("schema", "width", "要是 1200–4000 的整數（畫布寬，像素；PNG 再乘倍率）"))
        w = 2200
    grid = spec.get("grid", GRID)
    if not isinstance(grid, int) or not 6 <= grid <= 96:
        issues.append(Issue("schema", "grid", "要是 6–96 的整數"))
        grid = GRID

    bands, ids = [], set()
    raw_bands = spec.get("bands")
    if not isinstance(raw_bands, list) or not raw_bands:
        issues.append(Issue("schema", "bands", "必填：至少一層"))
        raw_bands = []
    for i, band in enumerate(raw_bands, 1):
        where = f"bands[{i}]"
        if not isinstance(band, dict):
            issues.append(Issue("schema", where, "每層要是對照表"))
            continue
        _unknown(band, BAND_KEYS, where, issues)
        color = band.get("color")
        if color not in PALETTE:
            issues.append(Issue("schema", f"{where}.color", f"必填，色票只有：{', '.join(PALETTE)}"))
            color = "gray"
        name = _lines(band.get("name"), 2)
        if name is None:
            issues.append(Issue("schema", f"{where}.name", "必填：層名（字串或 2 行清單）"))
        for key in ("en", "note"):
            if key in band and not is_text(band[key]):
                issues.append(Issue("schema", f"{where}.{key}", "要是非空字串"))
        pad = band.get("pad", [BAND_PAD, BAND_PAD])
        if not (isinstance(pad, list) and len(pad) == 2 and all(_num(v, 8, 400) for v in pad)):
            issues.append(Issue("schema", f"{where}.pad", "要是 [上留白, 下留白]（8–400 像素）"))
            pad = [BAND_PAD, BAND_PAD]
        for key in ("row_gap", "gap"):
            if key in band and not _num(band[key], 8, 400):
                issues.append(Issue("schema", f"{where}.{key}", "要是 8–400 的數字"))
        rows = []
        raw_rows = band.get("rows")
        if not isinstance(raw_rows, list) or not raw_rows:
            issues.append(Issue("schema", f"{where}.rows", "節點圖模式的每一層都要有 rows"))
            raw_rows = []
        for r, raw_row in enumerate(raw_rows, 1):
            if not isinstance(raw_row, list) or not raw_row:
                issues.append(Issue("schema", f"{where}.rows[{r}]", "每一列是節點清單"))
                continue
            row = []
            for j, raw_node in enumerate(raw_row, 1):
                at_where = f"{where}.rows[{r}][{j}]"
                node = _node(raw_node, at_where, grid, color, band.get("dashed") is True, issues)
                if node is None:
                    continue
                if node["id"] in ids:
                    issues.append(Issue("schema", f"{at_where}.id", f"id 重複：{node['id']}"))
                ids.add(node["id"])
                row.append(node)
            rows.append(row)
        groups = []
        members_here = {n["id"] for row in rows for n in row}
        raw_groups = band.get("groups", [])
        if not isinstance(raw_groups, list):
            issues.append(Issue("schema", f"{where}.groups", "要是群組清單"))
            raw_groups = []
        for j, raw_group in enumerate(raw_groups, 1):
            group = _group(raw_group, f"{where}.groups[{j}]", members_here, color, issues)
            if group:
                if group["id"] in ids:
                    issues.append(Issue("schema", f"{where}.groups[{j}].id", f"id 重複：{group['id']}"))
                ids.add(group["id"])
                groups.append(group)
        bands.append(
            {
                "color": color,
                "name": name or [""],
                "en": band.get("en", ""),
                "note": band.get("note", ""),
                "dashed": band.get("dashed") is True,
                "rows": rows,
                "groups": groups,
                "pad": pad,
                "row_gap": band.get("row_gap", ROW_GAP),
                "gap": band.get("gap", BAND_GAP),
            }
        )

    raw_edges = spec.get("edges", [])
    if not isinstance(raw_edges, list):
        issues.append(Issue("schema", "edges", "要是連線清單"))
        raw_edges = []
    edges = [_edge(e, f"edges[{i}]", ids, issues) for i, e in enumerate(raw_edges, 1)]
    model = {
        "title": spec.get("title", ""),
        "subtitle": spec.get("subtitle", ""),
        "footer": spec.get("footer", ""),
        "width": w,
        "grid": grid,
        "bands": bands,
        "edges": [e for e in edges if e],
    }
    return model, issues


# ---------- 幾何 ----------


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def hits(self, other: Box, gap: float = 0.0) -> bool:
        return (
            self.x < other.x + other.w + gap
            and other.x < self.x + self.w + gap
            and self.y < other.y + other.h + gap
            and other.y < self.y + self.h + gap
        )

    def crossed_by(self, p, q, gap: float) -> bool:
        """水平或垂直線段是否進到「外擴 gap」的方框內部（gap 為負代表內縮）。"""
        left, right = self.x - gap, self.x + self.w + gap
        top, bottom = self.y - gap, self.y + self.h + gap
        (ax, ay), (bx, by) = p, q
        return min(ax, bx) < right and max(ax, bx) > left and min(ay, by) < bottom and max(ay, by) > top

    def port(self, side: str, t: float) -> tuple[float, float]:
        if side in ("top", "bottom"):
            return self.x + self.w * t, self.y if side == "top" else self.y + self.h
        return self.x if side == "left" else self.x + self.w, self.y + self.h * t


def _auto_sides(a: Box, b: Box) -> tuple[str, str]:
    # 上下有重疊、左右分開就是左右相接；群組外框因為有標題，中心不會和同列節點同高
    level = min(a.y + a.h, b.y + b.h) - max(a.y, b.y) > min(a.h, b.h) / 2
    if level and (a.x + a.w < b.x or b.x + b.w < a.x):
        return ("right", "left") if a.cx < b.cx else ("left", "right")
    return ("bottom", "top") if a.cy < b.cy else ("top", "bottom")


def route(edge: dict, boxes: dict[str, Box]) -> list[tuple[float, float]]:
    """回傳折線頂點。相對的兩邊走一或三段，相鄰的兩邊轉一次彎，同一邊繞成ㄩ字形。"""
    (a_id, a_side, a_t), (b_id, b_side, b_t) = edge["from"], edge["to"]
    a, b = boxes[a_id], boxes[b_id]
    auto_a, auto_b = _auto_sides(a, b)
    a_side, b_side = a_side or auto_a, b_side or auto_b
    vertical_a, vertical_b = a_side in ("top", "bottom"), b_side in ("top", "bottom")
    start = a.port(a_side, 0.5 if a_t is None else a_t)
    end = b.port(b_side, 0.5 if b_t is None else b_t)

    if vertical_a == vertical_b and a_side != b_side:
        # 能拉直就拉直：沒指定位置的那一端移到另一端正對面
        axis = 0 if vertical_a else 1
        lo_a, len_a = (a.x, a.w) if vertical_a else (a.y, a.h)
        lo_b, len_b = (b.x, b.w) if vertical_a else (b.y, b.h)
        inset = 18
        target = None
        if a_t is None and b_t is None:
            low, high = max(lo_a, lo_b) + inset, min(lo_a + len_a, lo_b + len_b) - inset
            if low <= high:
                target = (max(lo_a, lo_b) + min(lo_a + len_a, lo_b + len_b)) / 2
        elif a_t is None and lo_a + inset <= end[axis] <= lo_a + len_a - inset:
            target = end[axis]
        elif b_t is None and lo_b + inset <= start[axis] <= lo_b + len_b - inset:
            target = start[axis]
        if target is not None:
            start = (target, start[1]) if vertical_a else (start[0], target)
            end = (target, end[1]) if vertical_a else (end[0], target)
        if abs(start[axis] - end[axis]) < 0.5:
            return [start, end]
        if vertical_a:
            mid = start[1] + (end[1] - start[1]) * edge["channel"]
            return [start, (start[0], mid), (end[0], mid), end]
        mid = start[0] + (end[0] - start[0]) * edge["channel"]
        return [start, (mid, start[1]), (mid, end[1]), end]

    if a_side == b_side:
        sign = 1 if a_side in ("bottom", "right") else -1
        axis = 1 if vertical_a else 0
        far = (max if sign == 1 else min)(start[axis], end[axis]) + sign * edge["depth"]
        if vertical_a:
            return [start, (start[0], far), (end[0], far), end]
        return [start, (far, start[1]), (far, end[1]), end]

    corner = (start[0], end[1]) if vertical_a else (end[0], start[1])
    return [start, corner, end]


def _segments(points):
    return list(pairwise(points))


def _length(p, q) -> float:
    return abs(p[0] - q[0]) + abs(p[1] - q[1])


def _horizontal(p, q) -> bool:
    return abs(p[1] - q[1]) < 0.5


def pill_box(edge: dict, points) -> Box:
    """標籤框：預設放在最長那一段的中點，label_at 改用整條線的比例位置，shift 再微調。"""
    segs = _segments(points)
    if edge["label_at"] is None:
        p, q = max(segs, key=lambda s: _length(*s))
        x, y = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    else:
        left = edge["label_at"] * sum(_length(*s) for s in segs)
        for p, q in segs:
            size = _length(p, q)
            if left <= size or (p, q) == segs[-1]:
                f = left / size if size else 0
                x, y = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
                break
            left -= size
    w = max(width(s, PILL_SIZE, True) for s in edge["label"]) + PILL_PAD
    h = len(edge["label"]) * PILL_LINE_H + 10
    return Box(x + edge["shift"][0] - w / 2, y + edge["shift"][1] - h / 2, w, h)


def _same_port(a: dict, pa, b: dict, pb) -> bool:
    """兩條線從同一點出發或進到同一點：分岔與匯流，允許共用線段。"""
    ends_a, ends_b = (pa[0], pa[-1]), (pb[0], pb[-1])
    return any(_length(p, q) < 1 for p in ends_a for q in ends_b)


def _overlap_length(p, q, r, s) -> float:
    """兩條平行線段幾乎重疊時的重疊長度。"""
    for axis, other in ((0, 1), (1, 0)):
        if abs(p[other] - q[other]) < 0.5 and abs(r[other] - s[other]) < 0.5 and abs(p[other] - r[other]) < 6:
            return min(max(p[axis], q[axis]), max(r[axis], s[axis])) - max(min(p[axis], q[axis]), min(r[axis], s[axis]))
    return 0.0


def lint(
    m: dict, boxes: dict[str, Box], members: dict, paths: list, pills: list, panel_right: float, area: Box
) -> list[Issue]:
    """版面守門：任何一條不過就不出圖。members 是「群組 id → 成員 id」，群組和自己的成員不算重疊；
    area 是層帶區域，連線與標籤不能跑出去。"""
    issues: list[Issue] = []
    names = list(boxes)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if b not in members.get(a, ()) and a not in members.get(b, ()) and boxes[a].hits(boxes[b], 8):
                issues.append(Issue("layout", a, f"節點和 {b} 重疊或間距不到 8px：調整 at"))
    for edge, points in zip(m["edges"], paths, strict=True):
        where, ends = edge["where"], (edge["from"][0], edge["to"][0])
        for p, q in _segments(points):
            for name, box in boxes.items():
                # 連到群組成員的線本來就要穿過群組外框
                if name not in ends and set(ends) & set(members.get(name, ())):
                    continue
                if box.crossed_by(p, q, -2 if name in ends else 5):
                    issues.append(Issue("layout", where, f"連線穿過或貼到節點 {name}：改接別邊，或調 @、channel、depth"))
            if min(p[0], q[0]) < panel_right + 4:
                issues.append(Issue("layout", where, "連線進到左側層名面板"))
            if min(p[1], q[1]) < area.y or max(p[1], q[1]) > area.y + area.h:
                issues.append(Issue("layout", where, "連線跑出層帶區域（會壓到標題或結論）：加大首末層的 pad，或調小 depth"))
        _, head, _ = WEIGHTS[edge["weight"]]
        tips = ([points[-2:]] if edge["arrow"] != "none" else []) + (
            [points[1::-1]] if edge["arrow"] == "both" else []
        )
        if any(_length(p, q) < head + 5 for p, q in tips):
            issues.append(Issue("layout", where, "箭頭前的線段太短：加大間距、depth，或調 channel"))
    for i, (ea, pa) in enumerate(zip(m["edges"], paths, strict=True)):
        for eb, pb in list(zip(m["edges"], paths, strict=True))[i + 1 :]:
            if _same_port(ea, pa, eb, pb):
                continue
            if any(_overlap_length(p, q, r, s) > 6 for p, q in _segments(pa) for r, s in _segments(pb)):
                issues.append(Issue("layout", eb["where"], f"和 {ea['where']} 有一段疊在一起：錯開 @、channel 或 depth"))
    labelled = [(i, pill) for i, pill in enumerate(pills) if pill]
    for n, (i, pill) in enumerate(labelled):
        where, text = m["edges"][i]["where"], "／".join(m["edges"][i]["label"])
        for name, box in boxes.items():
            if pill.hits(box, 3):
                issues.append(Issue("layout", where, f"標籤「{text}」壓到節點 {name}：改 label_at、shift，或拆成多行"))
        if pill.x < panel_right + 4 or pill.x + pill.w > area.w or pill.y < area.y or pill.y + pill.h > area.y + area.h:
            issues.append(Issue("layout", where, f"標籤「{text}」超出可用範圍"))
        for j, other in labelled[n + 1 :]:
            if pill.hits(other, 4):
                issues.append(Issue("layout", where, f"標籤「{text}」和 {m['edges'][j]['where']} 的標籤重疊"))
        for j, points in enumerate(paths):
            if j == i or _same_port(m["edges"][i], paths[i], m["edges"][j], points):
                continue
            if any(pill.crossed_by(p, q, 2) for p, q in _segments(points)):
                issues.append(Issue("layout", where, f"標籤「{text}」壓到 {m['edges'][j]['where']} 的線"))
    return issues


def crossings(edges: list, paths: list) -> list[list[tuple[float, float]]]:
    """每條線的橫段上，要畫跳線弧的點。"""
    hops: list[list[tuple[float, float]]] = [[] for _ in paths]
    for i, pa in enumerate(paths):
        for p, q in _segments(pa):
            if not _horizontal(p, q):
                continue
            for j, pb in enumerate(paths):
                if i == j or _same_port(edges[i], pa, edges[j], pb):
                    continue
                for r, s in _segments(pb):
                    if _horizontal(r, s):
                        continue
                    x, y = r[0], p[1]
                    if min(p[0], q[0]) + HOP + 2 < x < max(p[0], q[0]) - HOP - 2 and min(r[1], s[1]) < y < max(r[1], s[1]):
                        hops[i].append((x, y))
    return hops


# ---------- 繪圖 ----------


def _unit(p, q) -> tuple[float, float]:
    size = _length(p, q) or 1
    return (q[0] - p[0]) / size, (q[1] - p[1]) / size


def path_data(points, hops) -> str:
    """圓角折線；橫段上的 hops 畫成向上拱的半圓。"""
    d = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for k, (p, q) in enumerate(_segments(points)):
        ux, uy = _unit(p, q)
        if _horizontal(p, q):
            for x, y in sorted((h for h in hops if abs(h[1] - p[1]) < 0.5), reverse=ux < 0):
                if min(p[0], q[0]) < x < max(p[0], q[0]):
                    sweep = 1 if ux > 0 else 0
                    d.append(f"L{x - ux * HOP:.1f},{y:.1f} A{HOP},{HOP} 0 0 {sweep} {x + ux * HOP:.1f},{y:.1f}")
        if k + 2 < len(points):
            after = points[k + 2]
            radius = min(CORNER, _length(p, q) / 2, _length(q, after) / 2)
            vx, vy = _unit(q, after)
            d.append(f"L{q[0] - ux * radius:.1f},{q[1] - uy * radius:.1f}")
            d.append(f"Q{q[0]:.1f},{q[1]:.1f} {q[0] + vx * radius:.1f},{q[1] + vy * radius:.1f}")
        else:
            d.append(f"L{q[0]:.1f},{q[1]:.1f}")
    return " ".join(d)


def _arrow_head(c: Canvas, tail, tip, color: str, weight: str) -> None:
    _, size, half = WEIGHTS[weight]
    ux, uy = _unit(tail, tip)
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    c.parts.append(
        f'<path d="M{bx - uy * half:.1f},{by + ux * half:.1f} L{tip[0]:.1f},{tip[1]:.1f} '
        f'L{bx + uy * half:.1f},{by - ux * half:.1f} Z" fill="{color}"/>'
    )


def draw_edge(c: Canvas, edge: dict, points, hops) -> None:
    color = PALETTE[edge["color"]][3] if edge["color"] else EDGE_INK
    stroke, size, _ = WEIGHTS[edge["weight"]]
    shaft = list(points)
    # 線身縮到箭頭底部，粗線的方頭才不會從箭尖冒出來
    heads = []
    if edge["arrow"] != "none":
        heads.append((points[-2], points[-1]))
        ux, uy = _unit(points[-2], points[-1])
        shaft[-1] = (points[-1][0] - ux * (size - 2), points[-1][1] - uy * (size - 2))
    if edge["arrow"] == "both":
        heads.append((points[1], points[0]))
        ux, uy = _unit(points[1], points[0])
        shaft[0] = (points[0][0] - ux * (size - 2), points[0][1] - uy * (size - 2))
    dash = ""
    if edge["dashed"]:
        dash = ' stroke-dasharray="9 6"'
        # 虛線從終點起算，匯流到同一點的線在共用段上節奏才會對齊，不會疊成一條實線
        shaft.reverse()
    c.parts.append(
        f'<path d="{path_data(shaft, hops)}" fill="none" stroke="{color}" stroke-width="{stroke}"{dash}/>'
    )
    for tail, tip in heads:
        _arrow_head(c, tail, tip, color, edge["weight"])


def draw_pill(c: Canvas, edge: dict, box: Box) -> None:
    tone = edge["label_color"]
    ink = PALETTE[tone][3] if tone else EDGE_INK
    line = PALETTE[tone][2] if tone else EDGE_PILL_LINE
    c.rect(box.x, box.y, box.w, box.h, min(17, box.h / 2), "#FFFFFF", line)
    for k, s in enumerate(edge["label"]):
        c.text(box.cx, box.y + 23 + k * PILL_LINE_H, s, PILL_SIZE, ink, 700)


def node_height(node: dict) -> int:
    count = len(node["text"])
    if node["callout"]:
        return count * CALLOUT_LINE_H + CALLOUT_PAD
    return {1: 68, 2: 88}.get(count, 110 + (count - 3) * EXTRA_LINE_H)


def draw_node(c: Canvas, node: dict, box: Box) -> None:
    fill, _, soft, ink, line = PALETTE[node["color"]]
    count, dash = len(node["text"]), "8 6" if node["dashed"] else None
    if node["callout"]:
        c.rect(box.x, box.y, box.w, box.h, 14, fill, soft, 2, dash)
        top = box.y + (box.h - count * CALLOUT_LINE_H) / 2
        for k, s in enumerate(node["text"]):
            color = ink if k + 1 in node["accent"] else INK
            c.text(box.cx, top + k * CALLOUT_LINE_H + 19, s, DETAIL_STYLE[0], color, 700, node["id"], box.w - 20)
        return
    stroke = ink if node["strong"] else line
    c.rect(box.x, box.y, box.w, box.h, 12, "#FFFFFF", stroke, 3.2 if node["strong"] else 2.5, dash)
    ys = NODE_LINE_Y.get(count) or tuple(NODE_LINE_Y[3]) + tuple(
        NODE_LINE_Y[3][-1] + EXTRA_LINE_H * n for n in range(1, count - 2)
    )
    offset = (box.h - node_height(node)) / 2
    for k, (s, ly) in enumerate(zip(node["text"], ys, strict=True)):
        if k == 0:
            (size, weight), color = TITLE_STYLE, INK
        elif k + 1 in node["accent"]:
            (size, weight), color = ACCENT_STYLE, ink
        else:
            (size, weight), color = DETAIL_STYLE, MUTE
        c.text(box.cx, box.y + offset + ly, s, size, color, weight, node["id"], box.w - 20)


def group_box(group: dict, boxes: dict[str, Box]) -> Box:
    inner = [boxes[name] for name in group["wraps"]]
    left, right = min(b.x for b in inner), max(b.x + b.w for b in inner)
    top, bottom = min(b.y for b in inner), max(b.y + b.h for b in inner)
    return Box(left - GROUP_PAD, top - GROUP_TITLE_H, right - left + 2 * GROUP_PAD, bottom - top + GROUP_TITLE_H + GROUP_PAD)


def draw_group(c: Canvas, group: dict, box: Box) -> None:
    ink, line = PALETTE[group["color"]][3], PALETTE[group["color"]][4]
    c.rect(box.x, box.y, box.w, box.h, 14, "#FFFFFF", line, 3, "8 6" if group["dashed"] else None)
    c.text(box.cx, box.y + 31, group["title"], GROUP_TITLE_SIZE, ink, 800, group["id"], box.w - 20)


def _label_lines(band: dict) -> list[tuple[str, int, str, int, int]]:
    """層名面板的各行：文字、字級、顏色、字重、行高。"""
    ink = PALETTE[band["color"]][3]
    lines = [(s, NAME_SIZE, ink, 800, 38) for s in band["name"]]
    if band["en"]:
        lines.append((band["en"], EN_SIZE, ink, 700, 34))
    if band["note"]:
        lines.append((band["note"], NOTE_SIZE, MUTE, 600, 30))
    return lines


def render(m: dict) -> tuple[str, list[Issue], tuple[int, int]]:
    c = Canvas()
    w = m["width"]
    x0, x1 = MARGIN, w - MARGIN
    cx0 = x0 + LABEL_W + LABEL_GAP
    unit = (x1 - LABEL_GAP - cx0) / m["grid"]
    draw_title(c, w, m)

    boxes: dict[str, Box] = {}
    nodes: dict[str, dict] = {}
    members: dict[str, tuple] = {}
    groups = []
    frames = []
    y = HEAD_Y
    for i, band in enumerate(m["bands"], 1):
        heights = [max(node_height(n) for n in row) if row else 0 for row in band["rows"]]
        content = sum(heights) + band["row_gap"] * max(0, len(heights) - 1)
        top, bottom = band["pad"]
        height = max(BAND_MIN_H, content + top + bottom, sum(line[4] for line in _label_lines(band)) + 24)
        ry = y + top + (height - content - top - bottom) / 2
        for row, row_h in zip(band["rows"], heights, strict=True):
            for node in row:
                col, span = node["at"]
                # 旁註照自己的行數取高，不跟著同列的方塊拉高
                height_here = node_height(node) if node["callout"] else row_h
                boxes[node["id"]] = Box(cx0 + (col - 1) * unit, ry + (row_h - height_here) / 2, span * unit, height_here)
                nodes[node["id"]] = node
            ry += row_h + band["row_gap"]
        for group in band["groups"]:
            boxes[group["id"]] = group_box(group, boxes)
            members[group["id"]] = tuple(group["wraps"])
            groups.append((group, boxes[group["id"]]))
        frames.append((y, height, band, i))
        y += height + (band["gap"] if i < len(m["bands"]) else 0)
    bottom_edge = y

    for top, height, band, i in frames:
        draw_band_frame(c, x0, x1, top, height, band["color"], band["dashed"])
        lines = _label_lines(band)
        ly = top + (height - sum(line[4] for line in lines)) / 2
        for s, size, color, weight, line_h in lines:
            c.text(x0 + LABEL_W / 2, ly + line_h * 0.72, s, size, color, weight, f"bands[{i}].label", LABEL_W - 16)
            ly += line_h

    paths = [route(e, boxes) for e in m["edges"]]
    pills = [pill_box(e, p) if e["label"] else None for e, p in zip(m["edges"], paths, strict=True)]
    h = draw_footer(c, w, bottom_edge, m["footer"])
    area = Box(0, HEAD_Y, w, bottom_edge + 14 - HEAD_Y)
    c.issues.extend(lint(m, boxes, members, paths, pills, x0 + LABEL_W, area))

    for group, box in groups:
        draw_group(c, group, box)
    for edge, points, hops in zip(m["edges"], paths, crossings(m["edges"], paths), strict=True):
        draw_edge(c, edge, points, hops)
    for name, node in nodes.items():
        draw_node(c, node, boxes[name])
    for edge, pill in zip(m["edges"], pills, strict=True):
        if pill:
            draw_pill(c, edge, pill)
    return wrap_svg(c, w, h, m["title"]), c.issues, (w, h)
