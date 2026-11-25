"""兩種繪圖模式共用的基礎：色票與字型、估字寬、SVG 畫布、標題與結論。系列圖的一致風格由這裡界定。"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

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

MARGIN, LABEL_W, LABEL_GAP = 30, 300, 20
HEAD_Y = 165
# 方塊內各行（標題、重點、補充）的字級與字重
LINE_STYLE = ((22, 800), (18, 700), (16, 500))


@dataclass
class Issue:
    rule: str  # schema｜overflow｜layout
    where: str
    message: str


def is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


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


def draw_title(c: Canvas, w: int, m: dict) -> None:
    c.text(w / 2, 78, m["title"], 50, INK, 800, "title", w - 60, ' letter-spacing="3"')
    if m["subtitle"]:
        c.text(w / 2, 128, m["subtitle"], 23, SUBTLE, 600, "subtitle", w - 60, ' letter-spacing="1"')


def draw_footer(c: Canvas, w: int, bottom: float, footer: str) -> int:
    """畫結論列並回傳畫布高。"""
    if not footer:
        return int(bottom + 40)
    text = footer if footer.startswith("★") else f"★ {footer}"
    c.text(w / 2, bottom + 62, text, 27, INK, 800, "footer", w - 60, ' letter-spacing="1"')
    return int(bottom + 100)


def draw_band_frame(c: Canvas, x0: float, x1: float, y: float, height: float, color: str, dashed: bool) -> None:
    """淡色層帶加左側較深的層名面板。"""
    fill, label_fill, border = PALETTE[color][:3]
    dash = "10 7" if dashed else None
    c.rect(x0, y, x1 - x0, height, 18, fill, border, 2, dash)
    c.parts.append(
        f'<path d="M{x0 + 18},{y} H{x0 + LABEL_W} V{y + height} H{x0 + 18} '
        f'a18,18 0 0 1 -18,-18 V{y + 18} a18,18 0 0 1 18,-18 Z" fill="{label_fill}"/>'
    )
    line_dash = ' stroke-dasharray="10 7"' if dash else ""
    c.parts.append(
        f'<line x1="{x0 + LABEL_W}" y1="{y + 2}" x2="{x0 + LABEL_W}" y2="{y + height - 2}" '
        f'stroke="{border}" stroke-width="2"{line_dash}/>'
    )
    c.rect(x0, y, x1 - x0, height, 18, "none", border, 2, dash)


def wrap_svg(c: Canvas, w: int, h: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'font-family="{FONT}"><title>{escape(title)}</title>'
        f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>' + "".join(c.parts) + "</svg>"
    )
