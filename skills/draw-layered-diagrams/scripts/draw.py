#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""把宣告式 YAML 規格畫成「淡色層帶＋白色圓角方塊」風格的分層圖，直接輸出兩倍解析度 PNG。

規格寫法見 ../references/spec.md。先在記憶體組 SVG，再以 headless Chrome 截圖成 PNG；
規格有誤或任何文字估寬超出它的方塊，就逐條列出並停下，不輸出溢字的圖。

用法：
  uv run draw.py SPEC.yml                  輸出與 SPEC 同名的 .png
  uv run draw.py SPEC.yml -o OUT.png       指定輸出路徑
  uv run draw.py SPEC.yml --check [--json] 只驗規格與文字寬度，不需要 Chrome
  uv run draw.py SPEC.yml --svg OUT.svg    另存中間 SVG（除錯用）

結束碼：0 成功｜1 規格有誤或文字溢出｜2 執行環境問題（讀不到檔、找不到 Chrome、截圖失敗）。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

FONT = "'PingFang TC','Noto Sans TC','Microsoft JhengHei','Heiti TC',sans-serif"
INK, MUTE, SUBTLE = "#1B2433", "#5B6577", "#4A5568"

# 色票：層帶底色、標籤面板底色、層帶框線、層名字色、方塊框線
PALETTE = {
    "rose": ("#FDF3F5", "#F7E3E8", "#EBA3B1", "#C2334A", "#E58A9C"),
    "blue": ("#EFF5FE", "#E1ECFC", "#AECBF2", "#1D5FC4", "#8DB4EE"),
    "purple": ("#F6F1FD", "#ECE2FB", "#CDB2F0", "#7438BF", "#B58BE6"),
    "teal": ("#ECF8F8", "#DBF1F2", "#A0D8DB", "#0F7780", "#7CC7CC"),
    "yellow": ("#FFF9E7", "#FDF0C7", "#F1D48A", "#946300", "#E8C25E"),
    "orange": ("#FFF5EC", "#FDE7D3", "#F4C29A", "#B9520B", "#EFA673"),
    "green": ("#EBF8F1", "#D7F2E3", "#9EDBBA", "#11804A", "#79CC9E"),
    "gray": ("#F2F4F7", "#E4E8EE", "#CBD2DC", "#3D4A5C", "#AEB8C6"),
}
ARROWS = ("none", "down", "up", "both")

MARGIN, LABEL_W, LABEL_GAP, COL_GAP = 30, 300, 20, 34
ROW_H, ROW_GAP, BOX_H, BOX_GAP = 132, 16, 104, 14
BRIDGE_GAP = 40  # 層間說明框另外占用的高度
ARROW_ROOM = 24  # 說明框帶箭頭時再加的高度
HEAD_Y, HEAD_H = 165, 70
# 方塊內各行（標題、重點、補充）的基線與字級；行數少時整組垂直置中
LINE_Y = {1: (60,), 2: (45, 77), 3: (35, 65, 91)}
LINE_STYLE = ((22, 800), (18, 700), (16, 500))
# 左側層名面板各行（層名、英文、附註）相對層帶頂端的基線
LABEL_Y = {1: (75,), 2: (58, 92), 3: (46, 80, 112)}


@dataclass
class Issue:
    rule: str  # schema｜overflow
    where: str
    message: str


def width(text: str, size: float, bold: bool = False) -> float:
    """估字串顯示寬：中日文與全形符號一字寬，英數依大小寫與粗細折算（偏保守，寧可多報溢出）。"""
    total = 0.0
    for ch in text:
        if ord(ch) >= 0x2E80:
            total += size
        elif ch.isupper():
            total += size * (0.70 if bold else 0.66)
        elif ch in " il.,:;|!'":
            total += size * 0.30
        else:
            total += size * (0.60 if bold else 0.56)
    return total


# ---------- 規格 ----------


def _str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _boxes(raw, where: str, issues: list[Issue]) -> list[list[str]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 4:
        issues.append(Issue("schema", where, "要是 1–4 個方塊的清單"))
        return []
    out = []
    for i, box in enumerate(raw, 1):
        lines = [box] if isinstance(box, str) else box
        if not isinstance(lines, list) or not 1 <= len(lines) <= 3 or not all(_str(s) for s in lines):
            issues.append(Issue("schema", f"{where}[{i}]", "方塊是 1–3 行字串：[標題, 重點, 補充]"))
            continue
        out.append([s.strip() for s in lines])
    return out


def validate(spec) -> tuple[dict, list[Issue]]:
    """檢查規格並正規化成繪圖用的結構；有問題就回傳 Issue，不猜使用者的意思。"""
    issues: list[Issue] = []
    if not isinstance(spec, dict):
        return {}, [Issue("schema", "(root)", "規格頂層要是對照表（mapping）")]
    known = {"title", "subtitle", "footer", "width", "label", "columns", "bands"}
    for key in spec.keys() - known:
        issues.append(Issue("schema", key, f"不認得的鍵；可用：{', '.join(sorted(known))}"))
    if not _str(spec.get("title")):
        issues.append(Issue("schema", "title", "必填：圖的標題"))
    for key in ("subtitle", "footer", "label"):
        if key in spec and not _str(spec[key]):
            issues.append(Issue("schema", key, "要是非空字串"))
    w = spec.get("width", 2000)
    if not isinstance(w, int) or not 1200 <= w <= 4000:
        issues.append(Issue("schema", "width", "要是 1200–4000 的整數（畫布寬，像素；PNG 再乘倍率）"))

    columns = []
    if "columns" in spec:
        raw = spec["columns"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 3:
            issues.append(Issue("schema", "columns", "要是 1–3 欄的清單"))
        else:
            for i, col in enumerate(raw, 1):
                where = f"columns[{i}]"
                if not isinstance(col, dict) or not _str(col.get("title")):
                    issues.append(Issue("schema", where, "每欄要有 title"))
                    continue
                color = col.get("color", "blue")
                if color not in PALETTE:
                    issues.append(Issue("schema", f"{where}.color", f"色票只有：{', '.join(PALETTE)}"))
                if "note" in col and not _str(col["note"]):
                    issues.append(Issue("schema", f"{where}.note", "要是非空字串"))
                columns.append({"title": col["title"], "note": col.get("note", ""), "color": color})

    bands = []
    raw_bands = spec.get("bands")
    if not isinstance(raw_bands, list) or not raw_bands:
        issues.append(Issue("schema", "bands", "必填：至少一層"))
        raw_bands = []
    band_keys = {"color", "name", "en", "note", "dashed", "cells", "boxes", "bridge"}
    for i, band in enumerate(raw_bands, 1):
        where = f"bands[{i}]"
        if not isinstance(band, dict):
            issues.append(Issue("schema", where, "每層要是對照表"))
            continue
        for key in band.keys() - band_keys:
            issues.append(Issue("schema", f"{where}.{key}", f"不認得的鍵；可用：{', '.join(sorted(band_keys))}"))
        if band.get("color") not in PALETTE:
            issues.append(Issue("schema", f"{where}.color", f"必填，色票只有：{', '.join(PALETTE)}"))
        if not _str(band.get("name")):
            issues.append(Issue("schema", f"{where}.name", "必填：層名"))
        for key in ("en", "note"):
            if key in band and not _str(band[key]):
                issues.append(Issue("schema", f"{where}.{key}", "要是非空字串"))
        if "dashed" in band and not isinstance(band["dashed"], bool):
            issues.append(Issue("schema", f"{where}.dashed", "要是 true 或 false"))
        if columns:
            cells = band.get("cells")
            if "boxes" in band or not isinstance(cells, list) or len(cells) != len(columns):
                issues.append(Issue("schema", f"{where}.cells", f"有 columns 時用 cells，且要剛好 {len(columns)} 格"))
                cells = []
            parsed = [_boxes(c, f"{where}.cells[{j}]", issues) for j, c in enumerate(cells, 1)]
        else:
            if "cells" in band:
                issues.append(Issue("schema", f"{where}.cells", "沒有 columns 時改用 boxes"))
            parsed = [_boxes(band.get("boxes"), f"{where}.boxes", issues)]
        bridge = None
        if "bridge" in band:
            b = band["bridge"]
            b = {"text": b} if isinstance(b, str) else b
            if not isinstance(b, dict) or not _str(b.get("text")):
                issues.append(Issue("schema", f"{where}.bridge", "要有 text（或直接寫字串）"))
            elif b.get("arrow", "none") not in ARROWS:
                issues.append(Issue("schema", f"{where}.bridge.arrow", f"只有：{', '.join(ARROWS)}"))
            elif i == len(raw_bands):
                issues.append(Issue("schema", f"{where}.bridge", "最後一層之後沒有下一層，不能放層間說明框"))
            else:
                bridge = {"text": b["text"], "arrow": b.get("arrow", "none")}
        bands.append(
            {
                "color": band.get("color", "gray"),
                "name": band.get("name", ""),
                "en": band.get("en", ""),
                "note": band.get("note", ""),
                "dashed": band.get("dashed", False),
                "cells": parsed,
                "bridge": bridge,
            }
        )
    model = {
        "title": spec.get("title", ""),
        "subtitle": spec.get("subtitle", ""),
        "footer": spec.get("footer", ""),
        "width": w if isinstance(w, int) else 2000,
        "label": spec.get("label", "分層"),
        "columns": columns,
        "bands": bands,
    }
    return model, issues


# ---------- 繪圖 ----------


class Canvas:
    """累積 SVG 片段，順手記下估寬超出可用空間的字串。"""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.issues: list[Issue] = []

    def check(self, where: str, s: str, size: float, bold: bool, room: float) -> None:
        need = width(s, size, bold)
        if need > room:
            self.issues.append(Issue("overflow", where, f"「{s}」估 {need:.0f}px，可用 {room:.0f}px：縮短字句"))

    def text(self, x, y, s, size, fill, weight=400, where=None, room=None, extra=""):
        if room is not None:
            self.check(where or s, s, size, weight >= 600, room)
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="middle"{extra}>{escape(s)}</text>'
        )

    def rect(self, x, y, w, h, r, fill, stroke, sw=2.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )


@dataclass
class Grid:
    w: int
    x0: float
    x1: float
    cx0: float
    col_w: float
    n_cols: int

    @classmethod
    def of(cls, w: int, n_cols: int) -> Grid:
        x0, x1 = MARGIN, w - MARGIN
        cx0, cx1 = x0 + LABEL_W + LABEL_GAP, x1 - LABEL_GAP
        return cls(w, x0, x1, cx0, (cx1 - cx0 - COL_GAP * (n_cols - 1)) / n_cols, n_cols)

    def col_x(self, i: int) -> float:
        return self.cx0 + i * (self.col_w + COL_GAP)


def draw_header(c: Canvas, g: Grid, m: dict) -> float:
    c.text(g.w / 2, 78, m["title"], 50, INK, 800, "title", g.w - 60, ' letter-spacing="3"')
    if m["subtitle"]:
        c.text(g.w / 2, 128, m["subtitle"], 23, SUBTLE, 600, "subtitle", g.w - 60, ' letter-spacing="1"')
    if not m["columns"]:
        return HEAD_Y
    y = HEAD_Y
    c.rect(g.x0, y, LABEL_W, HEAD_H, 16, "#FFFFFF", PALETTE["gray"][2])
    c.text(g.x0 + LABEL_W / 2, y + 44, m["label"], 26, INK, 800, "label", LABEL_W - 20)
    for i, col in enumerate(m["columns"]):
        cx, color = g.col_x(i), PALETTE[col["color"]][3]
        c.rect(cx, y, g.col_w, HEAD_H, 16, "#FFFFFF", color, 2.5)
        need = width(col["title"], 27, True) + (8 + width(col["note"], 21, True) if col["note"] else 0)
        if need > g.col_w - 20:
            c.issues.append(Issue("overflow", f"columns[{i + 1}]", f"欄標題估 {need:.0f}px，可用 {g.col_w - 20:.0f}px"))
        note = (
            f'<tspan font-size="21" font-weight="700" fill="{color}" dx="8">{escape(col["note"])}</tspan>'
            if col["note"]
            else ""
        )
        c.parts.append(
            f'<text x="{cx + g.col_w / 2:.1f}" y="{y + 45:.1f}" text-anchor="middle">'
            f'<tspan font-size="27" font-weight="800" fill="{INK}">{escape(col["title"])}</tspan>{note}</text>'
        )
    return y + HEAD_H + 22


def draw_band(c: Canvas, g: Grid, y: float, band: dict, idx: int) -> None:
    fill, label_fill, border, ink, box_line = PALETTE[band["color"]]
    dash = "10 7" if band["dashed"] else None
    x0, x1 = g.x0, g.x1
    c.rect(x0, y, x1 - x0, ROW_H, 18, fill, border, 2, dash)
    c.parts.append(
        f'<path d="M{x0 + 18},{y} H{x0 + LABEL_W} V{y + ROW_H} H{x0 + 18} '
        f'a18,18 0 0 1 -18,-18 V{y + 18} a18,18 0 0 1 18,-18 Z" fill="{label_fill}"/>'
    )
    line_dash = ' stroke-dasharray="10 7"' if dash else ""
    c.parts.append(
        f'<line x1="{x0 + LABEL_W}" y1="{y + 2}" x2="{x0 + LABEL_W}" y2="{y + ROW_H - 2}" '
        f'stroke="{border}" stroke-width="2"{line_dash}/>'
    )
    c.rect(x0, y, x1 - x0, ROW_H, 18, "none", border, 2, dash)
    lx, where = x0 + LABEL_W / 2, f"bands[{idx}]"
    label = [(band["name"], 29, ink, 800), (band["en"], 20, ink, 700), (band["note"], 17, MUTE, 600)]
    label = [t for t in label if t[0]]
    for (s, size, color, weight), ly in zip(label, LABEL_Y[len(label)], strict=True):
        c.text(lx, y + ly, s, size, color, weight, f"{where}.label", LABEL_W - 20)
    for col, boxes in enumerate(band["cells"]):
        if not boxes:
            continue
        cx = g.col_x(col)
        bw = (g.col_w - BOX_GAP * (len(boxes) - 1)) / len(boxes)
        by = y + (ROW_H - BOX_H) / 2
        for j, lines in enumerate(boxes):
            bx = cx + j * (bw + BOX_GAP)
            c.rect(bx, by, bw, BOX_H, 12, "#FFFFFF", box_line, 2.5, "8 6" if dash else None)
            colors = (INK, ink, MUTE)
            for k, (s, ly) in enumerate(zip(lines, LINE_Y[len(lines)], strict=True)):
                size, weight = LINE_STYLE[k]
                c.text(bx + bw / 2, by + ly, s, size, colors[k], weight, f"{where}.box", bw - 20)


def bridge_gap(band: dict) -> float:
    """有箭頭的說明框上下各多留空間，箭頭才不會被層帶框線吃掉。"""
    return BRIDGE_GAP + (ARROW_ROOM if band["bridge"]["arrow"] != "none" else 0)


def draw_bridge(c: Canvas, g: Grid, top: float, band: dict) -> None:
    """層間說明框：置於兩層間隙正中，虛線貫穿，可加方向箭頭（尖端頂到層帶邊緣）。"""
    border, ink = PALETTE[band["color"]][2], PALETTE[band["color"]][3]
    text, arrow = band["bridge"]["text"], band["bridge"]["arrow"]
    span = ROW_GAP + bridge_gap(band)
    bottom, mid, cx = top + span, top + span / 2, g.w / 2
    c.parts.append(
        f'<line x1="{cx}" y1="{top}" x2="{cx}" y2="{bottom}" stroke="{border}" stroke-width="2" '
        f'stroke-dasharray="6 5"/>'
    )
    for tip, sign in ((bottom, 1), (top, -1)):
        if arrow == "both" or (arrow == "down" and sign == 1) or (arrow == "up" and sign == -1):
            c.parts.append(
                f'<path d="M{cx - 8},{tip - 13 * sign} L{cx},{tip} L{cx + 8},{tip - 13 * sign} Z" fill="{ink}"/>'
            )
    pw = width(text, 19, True) + 56
    c.check("bridge", text, 19, True, g.w - 2 * MARGIN - 40)
    c.rect(cx - pw / 2, mid - 19, pw, 38, 19, "#FFFFFF", border)
    c.text(cx, mid + 7, text, 19, ink, 700)


def render(m: dict) -> tuple[str, list[Issue], tuple[int, int]]:
    g = Grid.of(m["width"], max(1, len(m["columns"])))
    c = Canvas()
    y = draw_header(c, g, m)
    for i, band in enumerate(m["bands"], 1):
        draw_band(c, g, y, band, i)
        y += ROW_H + ROW_GAP
        if band["bridge"]:
            draw_bridge(c, g, y - ROW_GAP, band)
            y += bridge_gap(band)
    bottom = y - ROW_GAP
    if m["footer"]:
        footer = m["footer"] if m["footer"].startswith("★") else f"★ {m['footer']}"
        c.text(g.w / 2, bottom + 62, footer, 27, INK, 800, "footer", g.w - 60, ' letter-spacing="1"')
        h = int(bottom + 100)
    else:
        h = int(bottom + 40)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {g.w} {h}" width="{g.w}" height="{h}" '
        f'font-family="{FONT}"><title>{escape(m["title"])}</title>'
        f'<rect width="{g.w}" height="{h}" fill="#FFFFFF"/>' + "".join(c.parts) + "</svg>"
    )
    return svg, c.issues, (g.w, h)


# ---------- 輸出 ----------


def find_chrome() -> str | None:
    if env := os.environ.get("CHROME"):
        return env
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac).exists():
        return mac
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if found := shutil.which(name):
            return found
    return None


def to_png(svg: str, size: tuple[int, int], scale: int, out: Path) -> None:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("找不到 Chrome／Chromium；安裝後重跑，或以環境變數 CHROME 指定執行檔")
    w, h = size
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(f'<html><body style="margin:0;background:#FFFFFF">{svg}</body></html>', encoding="utf-8")
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--force-device-scale-factor={scale}",
            f"--screenshot={out}",
            f"--window-size={w},{h}",
        ]
        if platform.system() == "Linux":
            cmd.append("--no-sandbox")
        result = subprocess.run([*cmd, page.as_uri()], check=False, capture_output=True, text=True)
        if result.returncode != 0 or not out.is_file():
            raise RuntimeError(f"Chrome 截圖失敗（結束碼 {result.returncode}）：{result.stderr.strip()[-500:]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把 YAML 規格畫成淡色層帶風格的分層圖，直接輸出兩倍解析度 PNG。",
        epilog="結束碼：0 成功｜1 規格有誤或文字溢出｜2 執行環境問題。",
    )
    ap.add_argument("spec", type=Path, help="YAML 規格檔（寫法見 references/spec.md）")
    ap.add_argument("-o", "--output", type=Path, help="輸出 PNG（預設與規格同名、副檔名 .png）")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2, 3), help="PNG 倍率（預設 2）")
    ap.add_argument("--svg", type=Path, help="另存中間 SVG（除錯用）")
    ap.add_argument("--check", action="store_true", help="只驗規格與文字寬度，不輸出 PNG、不需要 Chrome")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出結果（ok、issues、size、output）")
    args = ap.parse_args(argv)

    def report(ok: bool, issues: list[Issue], size=None, output=None) -> None:
        if args.json:
            print(json.dumps({"ok": ok, "issues": [asdict(i) for i in issues], "size": size, "output": output},
                             ensure_ascii=False))
            return
        for i in issues:
            print(f"✗ [{i.rule}] {i.where}：{i.message}", file=sys.stderr)

    try:
        spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        print(f"✗ 讀不到規格檔：{e}", file=sys.stderr)
        return 2
    except yaml.YAMLError as e:
        report(False, [Issue("schema", str(args.spec), f"YAML 語法錯誤：{e}")])
        return 1

    model, issues = validate(spec)
    if issues:
        report(False, issues)
        return 1
    svg, issues, size = render(model)
    if issues:
        report(False, issues, list(size))
        return 1
    if args.svg:
        args.svg.write_text(svg, encoding="utf-8")
    if args.check:
        report(True, [], list(size))
        if not args.json:
            print(f"✓ 規格與文字寬度通過（畫布 {size[0]}×{size[1]}）")
        return 0
    out = args.output or args.spec.with_suffix(".png")
    try:
        to_png(svg, size, args.scale, out)
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    report(True, [], [size[0] * args.scale, size[1] * args.scale], str(out))
    if not args.json:
        print(f"✓ 輸出 {out}（{size[0] * args.scale}×{size[1] * args.scale}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
