#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""把宣告式 YAML 規格畫成「淡色層帶＋白色圓角方塊」風格的分層圖，直接輸出兩倍解析度 PNG。

規格寫法見 ../references/spec.md。兩種模式：層帶模式（本檔，每層一列等寬方塊、層間說明框）與節點圖模式
（graph.py，規格含 rows 或 edges：節點照格線擺放、節點之間有連線）。先在記憶體組 SVG，再以 headless Chrome
截圖成 PNG；規格有誤、文字溢出或版面不乾淨，就逐條列出並停下，不輸出有問題的圖。

用法：
  uv run draw.py SPEC.yml                  輸出與 SPEC 同名的 .png
  uv run draw.py --check DIR               驗目錄下的每一份規格（可混著給多個檔案與目錄；不加 --check 就全部重畫）
  uv run draw.py --check --verify-png DIR  另驗每份規格旁的 PNG 是目前的規格與引擎畫出來的（守門用）
  uv run draw.py SPEC.yml -o OUT.png       指定輸出路徑
  uv run draw.py SPEC.yml --check [--json] 只驗規格與文字寬度，不需要 Chrome
  uv run draw.py SPEC.yml --svg OUT.svg    另存中間 SVG（除錯用）

結束碼：0 成功｜1 規格有誤、文字溢出、版面不乾淨或 PNG 過期｜2 執行環境問題（讀不到檔、找不到 Chrome、截圖失敗）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import graph
import yaml
from base import (
    HEAD_Y,
    INK,
    LABEL_GAP,
    LABEL_W,
    LINE_STYLE,
    MARGIN,
    MUTE,
    PALETTE,
    Canvas,
    Issue,
    draw_band_frame,
    draw_footer,
    draw_title,
    width,
    wrap_svg,
)
from base import (
    is_text as _str,
)

ARROWS = ("none", "down", "up", "both")

COL_GAP = 34
ROW_H, ROW_GAP, BOX_H, BOX_GAP = 132, 16, 104, 14
BRIDGE_GAP = 40  # 層間說明框另外占用的高度
ARROW_ROOM = 24  # 說明框帶箭頭時再加的高度
HEAD_H = 70
# 方塊內各行（標題、重點、補充）的基線與字級；行數少時整組垂直置中
LINE_Y = {1: (60,), 2: (45, 77), 3: (35, 65, 91)}
# 左側層名面板各行（層名、英文、附註）相對層帶頂端的基線
LABEL_Y = {1: (75,), 2: (58, 92), 3: (46, 80, 112)}


# ---------- 規格 ----------


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
    draw_title(c, g.w, m)
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
    ink, box_line = PALETTE[band["color"]][3:]
    dash = "10 7" if band["dashed"] else None
    x0 = g.x0
    draw_band_frame(c, x0, g.x1, y, ROW_H, band["color"], band["dashed"])
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
    h = draw_footer(c, g.w, bottom, m["footer"])
    return wrap_svg(c, g.w, h, m["title"]), c.issues, (g.w, h)


# ---------- 內容指紋 ----------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 指紋放在 PNG 的 tEXt 區塊，開頭是關鍵字與分隔用的 NUL
FINGERPRINT_KEY = b"draw-layered-diagrams\0"


def page_html(svg: str) -> str:
    return f'<html><body style="margin:0;background:#FFFFFF">{svg}</body></html>'


def fingerprint(svg: str) -> str:
    """圖的內容指紋：送進 Chrome 的整頁。只由規格與引擎決定，和哪台機器、哪個倍率截圖無關。"""
    return hashlib.sha256(page_html(svg).encode("utf-8")).hexdigest()


def stamp(png: bytes, digest: str) -> bytes:
    """在 IHDR 之後插入帶指紋的 tEXt 區塊。"""
    data = FINGERPRINT_KEY + digest.encode("ascii")
    chunk = struct.pack(">I", len(data)) + b"tEXt" + data + struct.pack(">I", zlib.crc32(b"tEXt" + data))
    after_ihdr = len(PNG_SIGNATURE) + 25  # 長度 4＋型別 4＋資料 13＋CRC 4
    return png[:after_ihdr] + chunk + png[after_ihdr:]


def read_fingerprint(png: bytes) -> str | None:
    at = len(PNG_SIGNATURE)
    while at + 12 <= len(png):
        (length,) = struct.unpack(">I", png[at : at + 4])
        kind, data = png[at + 4 : at + 8], png[at + 8 : at + 8 + length]
        if kind == b"tEXt" and data.startswith(FINGERPRINT_KEY):
            return data[len(FINGERPRINT_KEY) :].decode("ascii", "replace")
        at += 12 + length
    return None


def stale_reason(out: Path, digest: str) -> str | None:
    """out 不是由這份指紋畫出來的原因；是最新的回傳 None。"""
    if not out.is_file():
        return "沒有這張 PNG"
    png = out.read_bytes()
    if not png.startswith(PNG_SIGNATURE):
        return "不是 PNG"
    found = read_fingerprint(png)
    if found is None:
        return "沒有內容指紋（舊版引擎畫的，或被其他工具改寫過）"
    return None if found == digest else "不是由目前的規格與引擎畫出"


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
        page.write_text(page_html(svg), encoding="utf-8")
        # 先截到暫存檔：Chrome 沒寫出圖卻回 0 時，舊 PNG 不能蓋上新指紋被當成最新
        shot = Path(tmp) / "shot.png"
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--force-device-scale-factor={scale}",
            f"--screenshot={shot}",
            f"--window-size={w},{h}",
        ]
        if platform.system() == "Linux":
            cmd.append("--no-sandbox")
        result = subprocess.run([*cmd, page.as_uri()], check=False, capture_output=True, text=True)
        if result.returncode != 0 or not shot.is_file():
            raise RuntimeError(f"Chrome 截圖失敗（結束碼 {result.returncode}）：{result.stderr.strip()[-500:]}")
        out.write_bytes(stamp(shot.read_bytes(), fingerprint(svg)))


# ---------- 命令列 ----------


def is_spec(path: Path) -> bool:
    """分層圖規格＝頂層有 bands 鍵的 YAML。解析不了的檔案看有沒有頂格的 bands:，寫壞的規格才不會被當成別的檔案略過。"""
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (ValueError, yaml.YAMLError):
        return re.search(rb"^bands\s*:", raw, re.MULTILINE) is not None
    return isinstance(data, dict) and "bands" in data


def find_specs(root: Path) -> list[Path]:
    """目錄下的規格。隱藏目錄（版控、虛擬環境、裝在裡面的技能範例）與 node_modules 不看，也不跟著符號連結走。"""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "node_modules")
        candidates = (Path(folder) / name for name in sorted(files) if name.endswith((".yml", ".yaml")))
        found += [path for path in candidates if path.is_file() and is_spec(path)]
    return found


def run(path: Path, args: argparse.Namespace, many: bool) -> int:
    """處理一份規格，回傳結束碼；many 時每行訊息都帶檔名。"""
    prefix = f"{path}：" if many else ""

    def report(ok: bool, issues: list[Issue], size=None, output=None) -> None:
        if args.json:
            result = {"spec": str(path), "ok": ok, "issues": [asdict(i) for i in issues]}
            print(json.dumps({**result, "size": size, "output": output}, ensure_ascii=False))
            return
        for i in issues:
            print(f"✗ [{i.rule}] {prefix}{i.where}：{i.message}", file=sys.stderr)

    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        print(f"✗ {prefix}讀不到規格檔：{e}", file=sys.stderr)
        return 2
    except yaml.YAMLError as e:
        report(False, [Issue("schema", str(path), f"YAML 語法錯誤：{e}")])
        return 1

    mode = graph if graph.is_graph(spec) else None
    model, issues = (mode.validate if mode else validate)(spec)
    if issues:
        report(False, issues)
        return 1
    svg, issues, size = (mode.render if mode else render)(model)
    if issues:
        report(False, issues, list(size))
        return 1
    if args.svg:
        args.svg.write_text(svg, encoding="utf-8")
    if args.check:
        passed = "規格與文字寬度通過"
        if args.verify_png:
            png = args.output or path.with_suffix(".png")
            if reason := stale_reason(png, fingerprint(svg)):
                report(False, [Issue("png", png.name, f"{reason}：去掉 --check 重畫，PNG 與規格一起提交")], list(size))
                return 1
            passed += "，PNG 是最新的"
        report(True, [], list(size))
        if not args.json:
            print(f"✓ {prefix}{passed}（畫布 {size[0]}×{size[1]}）")
        return 0
    out = args.output or path.with_suffix(".png")
    try:
        to_png(svg, size, args.scale, out)
    except (RuntimeError, OSError) as e:
        print(f"✗ {prefix}{e}", file=sys.stderr)
        return 2
    report(True, [], [size[0] * args.scale, size[1] * args.scale], str(out))
    if not args.json:
        print(f"✓ 輸出 {out}（{size[0] * args.scale}×{size[1] * args.scale}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把 YAML 規格畫成淡色層帶風格的分層圖，直接輸出兩倍解析度 PNG。",
        epilog="結束碼：0 成功｜1 規格有誤、文字溢出、版面不乾淨或 PNG 過期｜2 執行環境問題。",
    )
    ap.add_argument("paths", type=Path, nargs="+", metavar="PATH",
                    help="YAML 規格檔或目錄；目錄會遞迴找頂層有 bands 的 .yml／.yaml（寫法見 references/spec.md）")
    ap.add_argument("-o", "--output", type=Path, help="輸出 PNG（預設與規格同名、副檔名 .png；只能配一個規格檔）")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2, 3), help="PNG 倍率（預設 2）")
    ap.add_argument("--svg", type=Path, help="另存中間 SVG（除錯用；只能配一個規格檔）")
    ap.add_argument("--check", action="store_true", help="只驗規格與文字寬度，不輸出 PNG、不需要 Chrome")
    ap.add_argument("--verify-png", action="store_true",
                    help="配 --check：另驗 PNG（預設與規格同名）是目前的規格與引擎畫出來的，不需要 Chrome")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出結果，每份規格一行（spec、ok、issues、size、output）")
    args = ap.parse_args(argv)

    many = len(args.paths) > 1 or args.paths[0].is_dir()
    if many and (args.output or args.svg):
        ap.error("-o 與 --svg 只能配一個規格檔")
    if args.verify_png and not args.check:
        ap.error("--verify-png 要配 --check")
    specs = [spec for path in args.paths for spec in (find_specs(path) if path.is_dir() else [path])]
    if not specs:
        print("沒有找到分層圖規格（頂層有 bands 的 .yml／.yaml）", file=sys.stderr)
    return max((run(spec, args, many) for spec in specs), default=0)


if __name__ == "__main__":
    sys.exit(main())
