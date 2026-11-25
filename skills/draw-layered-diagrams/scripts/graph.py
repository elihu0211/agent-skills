"""節點圖模式：層帶裡的節點照格線擺放，連線以直角折線接在節點邊上。

位置與走線由規格宣告，引擎不自動排版；擺不乾淨（線穿過方塊、標籤壓到東西、兩條線疊在一起）就逐條列出並停下。
無法避免的交叉在橫線上畫跳線弧，讀者才分得出兩條線沒有相接。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from xml.sax.saxutils import escape

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
GROUP_PAD, GROUP_TITLE_H, GROUP_TITLE_SIZE = 16, 48, 22
# 分隔線多占的高度；靠左對齊時文字離框的距離
DIVIDER_H, TEXT_INSET = 14, 28
# 側欄寬、側欄和層帶的間距（雙向箭頭要放得下）、層內標題版型的左右內距
RAIL_W, RAIL_GAP, OPEN_INSET = 260, 64, 26
# 條列面板：膠囊標題列高、每個條目的基本與最大行距
PANEL_HEAD_H, PANEL_ITEM_H, PANEL_ITEM_MAX, PANEL_TAIL = 82, 80, 96, 6
PANEL_PILL_SIZE, PANEL_HEAD_SIZE, PANEL_DETAIL_SIZE = 20, 18, 16
# 大型方向箭頭：身寬、頭寬、頭高
BLOCK_SHAFT, BLOCK_HEAD_W, BLOCK_HEAD_H = 32, 64, 46
ROW_GAP, BAND_PAD, BAND_GAP, BAND_MIN_H = 52, 24, 52, 132
NAME_SIZE, EN_SIZE, NOTE_SIZE = 28, 20, 17
SIDES = ("top", "bottom", "left", "right")
EDGE_INK, EDGE_PILL_LINE = "#2F3A4C", "#CBD2DC"
# 線寬、箭頭長、箭頭半寬
WEIGHTS = {"normal": (2.4, 13, 7), "thick": (6.0, 20, 11)}
PILL_SIZE, PILL_LINE_H, PILL_PAD = 18, 24, 26
CORNER, HOP = 10, 9
DEPTH = 46

TOP_KEYS = {"title", "subtitle", "footer", "width", "grid", "labels", "rails", "bands", "edges"}
BAND_KEYS = {"id", "color", "name", "title_align", "en", "note", "dashed", "rows", "groups", "pad", "row_gap", "gap"}
NODE_KEYS = {"id", "at", "text", "color", "dashed", "strong", "accent", "accent_color", "callout", "divider", "fill", "align", "title_lines", "bullets", "block"}
EDGE_KEYS = {
    "from", "to", "label", "label_color", "style", "weight", "arrow", "color", "channel", "depth", "label_at", "shift"
}
GROUP_KEYS = {"id", "title", "wraps", "color", "dashed"}
RAIL_KEYS = {"id", "side", "bands", "color", "text", "title_lines"}


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


def _valid_id(v) -> bool:
    return is_text(v) and not any(ch in v for ch in ".@ ")


def _bullets(raw, where: str, issues: list[Issue]) -> list[tuple] | None:
    """條列面板的條目：[重點]、[重點, 說明] 或 [重點, 說明, 說明的色票]。"""
    ok = isinstance(raw, list) and 1 <= len(raw) <= 6
    out = []
    for item in raw if ok else []:
        parts = [item] if isinstance(item, str) else item
        good = isinstance(parts, list) and 1 <= len(parts) <= 3 and all(is_text(s) for s in parts)
        if not good or (len(parts) == 3 and parts[2] not in PALETTE):
            ok = False
            break
        out.append((parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else None))
    if not ok:
        issues.append(Issue("schema", where, "要是 1–6 個條目：[重點, 說明?, 色票?]"))
        return None
    return out


def _rail(raw, where: str, count: int, issues: list[Issue]) -> dict | None:
    if not isinstance(raw, dict):
        issues.append(Issue("schema", where, "側欄要是對照表：{id, side, bands, text}"))
        return None
    _unknown(raw, RAIL_KEYS, where, issues)
    text = _lines(raw.get("text"), 8)
    span = raw.get("bands")
    title_lines = raw.get("title_lines", 1)
    color = raw.get("color", "gray")
    ok = True
    for good, key, message in (
        (_valid_id(raw.get("id")), "id", "必填：不含空白、「.」與「@」的字串"),
        (raw.get("side") in ("left", "right"), "side", "只有：left, right"),
        (
            isinstance(span, list) and len(span) == 2 and all(isinstance(n, int) for n in span)
            and 1 <= span[0] <= span[1] <= count,
            "bands", f"要是 [起始層, 結束層]，層從 1 起、最多 {count}",
        ),
        (text is not None, "text", "必填：1–8 行字串"),
        (isinstance(title_lines, int) and 1 <= title_lines <= len(text or [""]), "title_lines", "要是 1 到行數之間的整數"),
        (color in PALETTE, "color", f"色票只有：{', '.join(PALETTE)}"),
    ):
        if not good:
            issues.append(Issue("schema", f"{where}.{key}", message))
            ok = False
    if not ok:
        return None
    return {"id": raw["id"], "side": raw["side"], "bands": span, "color": color, "text": text, "title_lines": title_lines}


def _node(raw, where: str, grid: int, band_color: str, band_dashed: bool, issues: list[Issue]) -> dict | None:
    if not isinstance(raw, dict):
        issues.append(Issue("schema", where, "節點要是對照表：{id, at, text}"))
        return None
    _unknown(raw, NODE_KEYS, where, issues)
    ok = True
    if not _valid_id(raw.get("id")):
        issues.append(Issue("schema", f"{where}.id", "必填：不含空白、「.」與「@」的字串"))
        ok = False
    at = raw.get("at")
    if not (isinstance(at, list) and len(at) == 2 and _num(at[0], 1, grid + 1) and _num(at[1], 1, grid)):
        issues.append(Issue("schema", f"{where}.at", f"必填：[起始欄, 欄寬]，格線共 {grid} 欄、從 1 起"))
        ok = False
    elif at[0] + at[1] > grid + 1:
        issues.append(Issue("schema", f"{where}.at", f"超出格線：起始欄加欄寬最多 {grid + 1}"))
        ok = False
    block = raw.get("block")
    if block is not None:
        color = raw.get("color", band_color)
        if block not in ("down", "up"):
            issues.append(Issue("schema", f"{where}.block", "只有：down, up"))
            ok = False
        if "text" in raw or "bullets" in raw:
            issues.append(Issue("schema", f"{where}.block", "大型箭頭不放文字；說明寫在旁邊的節點"))
            ok = False
        if color not in PALETTE:
            issues.append(Issue("schema", f"{where}.color", f"色票只有：{', '.join(PALETTE)}"))
            ok = False
        return {"id": raw["id"], "at": raw["at"], "block": block, "color": color, "text": []} if ok else None
    bullets = _bullets(raw["bullets"], f"{where}.bullets", issues) if "bullets" in raw else []
    ok = ok and bullets is not None
    text = _lines(raw.get("text"), 1 if "bullets" in raw else MAX_LINES)
    if text is None:
        rule = "條列面板的 text 只放一行標題" if "bullets" in raw else f"必填：1–{MAX_LINES} 行字串，第一行是標題"
        issues.append(Issue("schema", f"{where}.text", rule))
        ok = False
    title_lines = raw.get("title_lines", 1)
    if not (isinstance(title_lines, int) and 1 <= title_lines <= max(1, len(text or []))):
        issues.append(Issue("schema", f"{where}.title_lines", "要是 1 到行數之間的整數"))
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
    align_choices = ("left", "right") if "bullets" in raw else ("center", "left")
    for key, allowed in (("fill", ("white", "tint")), ("align", align_choices)):
        if key in raw and raw[key] not in allowed:
            issues.append(Issue("schema", f"{where}.{key}", f"只有：{', '.join(allowed)}"))
            ok = False
    if "accent_color" in raw and raw["accent_color"] not in PALETTE:
        issues.append(Issue("schema", f"{where}.accent_color", f"色票只有：{', '.join(PALETTE)}"))
        ok = False
    divider = raw.get("divider")
    if divider is not None and not (isinstance(divider, int) and text and 1 <= divider < len(text)):
        issues.append(Issue("schema", f"{where}.divider", "要是行號：分隔線畫在這一行下面（不能是最後一行）"))
        ok = False
    if not ok:
        return None
    return {
        "id": raw["id"],
        "at": at,
        "text": text,
        "block": None,
        "bullets": bullets or [],
        "title_lines": title_lines,
        "color": color,
        "dashed": bool(raw.get("dashed", band_dashed)),
        "strong": bool(raw.get("strong", False)),
        "accent": accent,
        "callout": bool(raw.get("callout", False)),
        "divider": divider,
        "fill": raw.get("fill", "tint" if raw.get("callout") else "white"),
        "align": raw.get("align", "left" if bullets else "center"),
        "accent_color": raw.get("accent_color", color),
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

    labels = spec.get("labels", "side")
    if labels not in ("side", "top"):
        issues.append(Issue("schema", "labels", "只有：side（左側層名面板）, top（層名寫在層內上方）"))
        labels = "side"

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
        if name is None and (labels == "side" or "name" in band):
            issues.append(Issue("schema", f"{where}.name", "必填：層名（字串或 2 行清單）"))
        if band.get("title_align", "left") not in ("left", "center"):
            issues.append(Issue("schema", f"{where}.title_align", "只有：left, center"))
        if "title_align" in band and labels != "top":
            issues.append(Issue("schema", f"{where}.title_align", "只在 labels: top 時有效"))
        band_id = band.get("id")
        if band_id is not None:
            if not _valid_id(band_id) or band_id in ids:
                issues.append(Issue("schema", f"{where}.id", "要是全圖唯一、不含空白、「.」與「@」的字串"))
            else:
                ids.add(band_id)
        en = _lines(band["en"], 2) if "en" in band else []
        if en is None:
            issues.append(Issue("schema", f"{where}.en", "要是字串或 2 行清單"))
        if "note" in band and not is_text(band["note"]):
            issues.append(Issue("schema", f"{where}.note", "要是非空字串"))
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
                "id": band_id,
                "color": color,
                "name": name or ([""] if labels == "side" else []),
                "title_align": band.get("title_align", "left"),
                "en": en or [],
                "note": band.get("note", ""),
                "dashed": band.get("dashed") is True,
                "rows": rows,
                "groups": groups,
                "pad": pad,
                "row_gap": band.get("row_gap", ROW_GAP),
                "gap": band.get("gap", BAND_GAP),
            }
        )

    rails = []
    raw_rails = spec.get("rails", [])
    if not isinstance(raw_rails, list):
        issues.append(Issue("schema", "rails", "要是側欄清單"))
        raw_rails = []
    for i, raw_rail in enumerate(raw_rails, 1):
        rail = _rail(raw_rail, f"rails[{i}]", len(bands), issues)
        if rail:
            if rail["id"] in ids:
                issues.append(Issue("schema", f"rails[{i}].id", f"id 重複：{rail['id']}"))
            ids.add(rail["id"])
            rails.append(rail)

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
        "labels": labels,
        "rails": rails,
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
    if node["block"]:
        return 0  # 箭頭跟著同列其他節點的高度
    if node["bullets"]:
        return PANEL_HEAD_H + PANEL_ITEM_H * len(node["bullets"]) + PANEL_TAIL
    count = len(node["text"])
    extra = DIVIDER_H if node["divider"] else 0
    if node["callout"]:
        return count * CALLOUT_LINE_H + CALLOUT_PAD + extra
    return {1: 68, 2: 88}.get(count, 110 + (count - 3) * EXTRA_LINE_H) + extra


def _line_ys(node: dict) -> list[float]:
    """各行相對於內容頂端的基線；分隔線以下的行往下讓出 DIVIDER_H。"""
    count = len(node["text"])
    if node["callout"]:
        ys = [CALLOUT_PAD / 2 + k * CALLOUT_LINE_H + 19 for k in range(count)]
    else:
        ys = list(NODE_LINE_Y.get(count) or NODE_LINE_Y[3] + tuple(
            NODE_LINE_Y[3][-1] + EXTRA_LINE_H * n for n in range(1, count - 2)
        ))
    return [y + DIVIDER_H if node["divider"] and k >= node["divider"] else y for k, y in enumerate(ys)]


def _text_at(c: Canvas, x: float, y: float, s: str, size: int, weight: int, color: str, where: str, room: float,
             anchor: str) -> None:
    """靠左或靠右對齊的一行字。"""
    c.check(where, s, size, weight >= 600, room)
    c.parts.append(
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{color}" '
        f'text-anchor="{anchor}">{escape(s)}</text>'
    )


def draw_panel(c: Canvas, node: dict, box: Box) -> None:
    """條列面板：膠囊標題加數個「● 重點／說明」條目，整體靠左或靠右。"""
    _, label_fill, soft, ink, _ = PALETTE[node["color"]]
    c.rect(box.x, box.y, box.w, box.h, 18, "#FFFFFF", soft, 3)
    right = node["align"] == "right"
    edge = box.x + box.w - 22 if right else box.x + 22
    title, name = node["text"][0], node["id"]
    pill_w = min(box.w - 36, width(title, PANEL_PILL_SIZE, True) + 52)
    c.check(name, title, PANEL_PILL_SIZE, True, box.w - 36 - 30)
    px = box.x + box.w - 18 - pill_w if right else box.x + 18
    c.rect(px, box.y + 18, pill_w, 44, 22, label_fill, ink, 2)
    c.text(px + pill_w / 2, box.y + 47, title, PANEL_PILL_SIZE, ink, 800)
    pitch = min(PANEL_ITEM_MAX, (box.h - PANEL_HEAD_H - PANEL_TAIL) / len(node["bullets"]))
    anchor, room = "end" if right else "start", box.w - 44
    for k, (head, detail, tone) in enumerate(node["bullets"]):
        top = box.y + PANEL_HEAD_H + k * pitch
        _text_at(c, edge, top + 28, f"● {head}", PANEL_HEAD_SIZE, 800, INK, name, room, anchor)
        if detail:
            color = PALETTE[tone][3] if tone else MUTE
            _text_at(c, edge, top + 57, detail, PANEL_DETAIL_SIZE, 700 if tone else 600, color, name, room, anchor)


def draw_block(c: Canvas, node: dict, box: Box) -> None:
    """大型方向箭頭：表達一整段資料流的方向。"""
    label_fill, ink = PALETTE[node["color"]][1], PALETTE[node["color"]][3]
    cx, top, bottom = box.cx, box.y, box.y + box.h
    s, h, d = BLOCK_SHAFT / 2, BLOCK_HEAD_W / 2, BLOCK_HEAD_H
    if node["block"] == "down":
        points = [(cx - s, top), (cx + s, top), (cx + s, bottom - d), (cx + h, bottom - d), (cx, bottom),
                  (cx - h, bottom - d), (cx - s, bottom - d)]
    else:
        points = [(cx, top), (cx + h, top + d), (cx + s, top + d), (cx + s, bottom), (cx - s, bottom),
                  (cx - s, top + d), (cx - h, top + d)]
    path = " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    c.parts.append(f'<path d="M{path} Z" fill="{label_fill}" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>')


def draw_rail(c: Canvas, rail: dict, box: Box) -> None:
    """跨多層的側欄：淡色直欄，中央一張白卡寫它是誰。"""
    fill, _, soft, _, line = PALETTE[rail["color"]]
    c.rect(box.x, box.y, box.w, box.h, 18, fill, line, 2.5)
    sizes = [(TITLE_STYLE, 36) if k < rail["title_lines"] else (DETAIL_STYLE, 30) for k in range(len(rail["text"]))]
    card_h = sum(step for _, step in sizes) + 44
    cx, cy, cw = box.x + 20, box.cy - card_h / 2, box.w - 40
    c.rect(cx, cy, cw, card_h, 14, "#FFFFFF", soft, 2)
    y = cy + 22
    for k, (s, ((size, weight), step)) in enumerate(zip(rail["text"], sizes, strict=True)):
        if k == rail["title_lines"]:
            y += 6
        c.text(box.cx, y + step * 0.72, s, size, INK if k < rail["title_lines"] else MUTE, weight, rail["id"], cw - 14)
        y += step


def draw_node(c: Canvas, node: dict, box: Box) -> None:
    if node["block"]:
        draw_block(c, node, box)
        return
    if node["bullets"]:
        draw_panel(c, node, box)
        return
    fill, _, soft, ink, line = PALETTE[node["color"]]
    strong_ink = PALETTE[node["accent_color"]][3]
    dash = "8 6" if node["dashed"] else None
    background = fill if node["fill"] == "tint" else "#FFFFFF"
    if node["callout"]:
        c.rect(box.x, box.y, box.w, box.h, 14, background, soft, 2, dash)
    else:
        stroke = ink if node["strong"] else line
        c.rect(box.x, box.y, box.w, box.h, 12, background, stroke, 3.2 if node["strong"] else 2.5, dash)
    offset = box.y + (box.h - node_height(node)) / 2
    ys = _line_ys(node)
    if node["divider"]:
        # 分隔線置中於上下兩行之間
        gap_y = offset + (ys[node["divider"] - 1] + ys[node["divider"]]) / 2 - 5
        c.parts.append(
            f'<line x1="{box.x + 36:.1f}" y1="{gap_y:.1f}" x2="{box.x + box.w - 36:.1f}" y2="{gap_y:.1f}" '
            f'stroke="{soft}" stroke-width="1.5"/>'
        )
    left = node["align"] == "left"
    for k, (s, ly) in enumerate(zip(node["text"], ys, strict=True)):
        accented = k + 1 in node["accent"]
        if node["callout"]:
            (size, weight), color = (DETAIL_STYLE[0], 700), strong_ink if accented else INK
        elif k < node["title_lines"]:
            (size, weight), color = TITLE_STYLE, strong_ink if accented else INK
        elif accented:
            (size, weight), color = ACCENT_STYLE, strong_ink
        else:
            (size, weight), color = DETAIL_STYLE, MUTE
        if left:
            c.check(node["id"], s, size, True, box.w - TEXT_INSET - 14)
            c.parts.append(
                f'<text x="{box.x + TEXT_INSET:.1f}" y="{offset + ly:.1f}" font-size="{size}" '
                f'font-weight="{weight}" fill="{color}">{escape(s)}</text>'
            )
        else:
            c.text(box.cx, offset + ly, s, size, color, weight, node["id"], box.w - 20)


def group_box(group: dict, boxes: dict[str, Box]) -> Box:
    inner = [boxes[name] for name in group["wraps"]]
    left, right = min(b.x for b in inner), max(b.x + b.w for b in inner)
    top, bottom = min(b.y for b in inner), max(b.y + b.h for b in inner)
    return Box(left - GROUP_PAD, top - GROUP_TITLE_H, right - left + 2 * GROUP_PAD, bottom - top + GROUP_TITLE_H + GROUP_PAD)


def draw_group(c: Canvas, group: dict, box: Box) -> None:
    line = PALETTE[group["color"]][4]
    c.rect(box.x, box.y, box.w, box.h, 14, "#FFFFFF", line, 3, "8 6" if group["dashed"] else None)
    c.text(box.cx, box.y + 31, group["title"], GROUP_TITLE_SIZE, INK, 800, group["id"], box.w - 20)


def _label_lines(band: dict) -> list[tuple[str, int, str, int, int]]:
    """層名面板的各行：文字、字級、顏色、字重、行高。"""
    ink = PALETTE[band["color"]][3]
    lines = [(s, NAME_SIZE, ink, 800, 38) for s in band["name"]]
    for k, s in enumerate(band["en"]):
        lines.append((s, EN_SIZE, ink, 700, 34 if k == len(band["en"]) - 1 else 27))
    if band["note"]:
        lines.append((band["note"], NOTE_SIZE, MUTE, 600, 30))
    return lines


def header_lines(band: dict) -> list[tuple[str, int, int, float]]:
    """層內標題版型的各行：文字、字級、字重、相對層頂的基線。"""
    lines = [(s, NAME_SIZE - 2, 800, 40 + 34 * k) for k, s in enumerate(band["name"])]
    start = 40 + 34 * len(band["name"]) + 2
    return lines + [(s, EN_SIZE - 1, 700, start + 28 * k) for k, s in enumerate(band["en"])]


def header_box(band: dict, x0: float, x1: float, y: float) -> Box:
    lines = header_lines(band)
    w = max(width(s, size, True) for s, size, _, _ in lines)
    left = (x0 + x1 - w) / 2 if band["title_align"] == "center" else x0 + OPEN_INSET + 4
    return Box(left, y + 12, w, lines[-1][3] - 4)


def draw_open_band(c: Canvas, band: dict, x0: float, x1: float, y: float, height: float) -> None:
    """層內標題版型的層框：沒有左側面板，有層名的層用較深的框線。"""
    fill, _, soft, ink, line = PALETTE[band["color"]]
    c.rect(x0, y, x1 - x0, height, 18, fill, line if band["name"] else soft, 2.5 if band["name"] else 2,
           "10 7" if band["dashed"] else None)
    center = band["title_align"] == "center"
    x = (x0 + x1) / 2 if center else x0 + OPEN_INSET + 4
    for s, size, weight, ly in header_lines(band):
        _text_at(c, x, y + ly, s, size, weight, ink, "header", x1 - x0 - 2 * OPEN_INSET, "middle" if center else "start")


def render(m: dict) -> tuple[str, list[Issue], tuple[int, int]]:
    c = Canvas()
    w = m["width"]
    sides = {rail["side"] for rail in m["rails"]}
    x0 = MARGIN + (RAIL_W + RAIL_GAP if "left" in sides else 0)
    x1 = w - MARGIN - (RAIL_W + RAIL_GAP if "right" in sides else 0)
    open_style = m["labels"] == "top"
    cx0 = x0 + (OPEN_INSET if open_style else LABEL_W + LABEL_GAP)
    unit = (x1 - (OPEN_INSET if open_style else LABEL_GAP) - cx0) / m["grid"]
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
        if open_style:
            label_height = header_lines(band)[-1][3] + 24 if band["name"] else 0
        else:
            label_height = sum(line[4] for line in _label_lines(band)) + 24
        height = max(0 if open_style else BAND_MIN_H, content + top + bottom, label_height)
        if open_style and band["name"]:
            boxes[f"header:{i}"] = header_box(band, x0, x1, y)
        ry = y + top + (height - content - top - bottom) / 2
        for row, row_h in zip(band["rows"], heights, strict=True):
            for node in row:
                col, span = node["at"]
                # 旁註照自己的行數取高，不跟著同列的方塊拉高
                height_here = node_height(node) if not node["block"] and node["callout"] else row_h
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

    # 層框不是障礙物，只當連線的接點
    frame_ports = {band["id"]: Box(x0, top, x1 - x0, height) for top, height, band, _ in frames if band["id"]}
    for rail in m["rails"]:
        first, last = frames[rail["bands"][0] - 1], frames[rail["bands"][1] - 1]
        rx = MARGIN if rail["side"] == "left" else w - MARGIN - RAIL_W
        boxes[rail["id"]] = Box(rx, first[0], RAIL_W, last[0] + last[1] - first[0])

    for top, height, band, i in frames:
        if open_style:
            draw_open_band(c, band, x0, x1, top, height)
            continue
        draw_band_frame(c, x0, x1, top, height, band["color"], band["dashed"])
        lines = _label_lines(band)
        ly = top + (height - sum(line[4] for line in lines)) / 2
        for s, size, color, weight, line_h in lines:
            c.text(x0 + LABEL_W / 2, ly + line_h * 0.72, s, size, color, weight, f"bands[{i}].label", LABEL_W - 16)
            ly += line_h

    paths = [route(e, {**boxes, **frame_ports}) for e in m["edges"]]
    pills = [pill_box(e, p) if e["label"] else None for e, p in zip(m["edges"], paths, strict=True)]
    h = draw_footer(c, w, bottom_edge, m["footer"])
    area = Box(0, HEAD_Y, w, bottom_edge + 14 - HEAD_Y)
    c.issues.extend(lint(m, boxes, members, paths, pills, -1e9 if open_style else x0 + LABEL_W, area))

    for group, box in groups:
        draw_group(c, group, box)
    for rail in m["rails"]:
        draw_rail(c, rail, boxes[rail["id"]])
    # 虛線先畫：虛線匯進實線主幹時，共用段看到的是實線
    drawn = zip(m["edges"], paths, crossings(m["edges"], paths), strict=True)
    for edge, points, hops in sorted(drawn, key=lambda item: not item[0]["dashed"]):
        draw_edge(c, edge, points, hops)
    for name, node in nodes.items():
        draw_node(c, node, boxes[name])
    for edge, pill in zip(m["edges"], pills, strict=True):
        if pill:
            draw_pill(c, edge, pill)
    return wrap_svg(c, w, h, m["title"]), c.issues, (w, h)
