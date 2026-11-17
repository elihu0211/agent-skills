"""佈局與視覺圖表引擎：由宣告式規格直接產出 PPTX。

繪製原語在 `_draw.py`，圖表區塊（架構拓撲、跨泳道時序、量化長條、時間軸、論證版面…）在 `blocks.py`；
本檔只負責一頁一頁的版面配置（`Deck`）與由規格產出整份簡報（`render`）。
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import theme as T
from _draw import line, text_box
from blocks import BLOCKS, planned_height
from lxml import etree
from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches
from qmd_export import SpecError, author_of

L = T.LAYOUT

__all__ = ["BLOCKS", "Deck", "SpecError", "planned_height", "render"]

_TRANSITION = '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" spd="med"><p:fade/></p:transition>'
_OVERFLOW_TOLERANCE = 0.02  # 英吋（約 1.5 pt）：容許浮點與手調的微小誤差，再多就是規格寫太滿


class Deck:
    def __init__(self, short_title: str, assets: Path | None = None) -> None:
        """`assets` 是簡報目錄：規格裡的圖片路徑相對於它（省略則用目前目錄）。"""
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(L.slide_w), Inches(L.slide_h)
        self.blank = self.prs.slide_layouts[6]
        self.short = short_title
        self.assets = assets or Path.cwd()
        self.n = 0

    def _new(self) -> Any:
        self.n += 1
        s = self.prs.slides.add_slide(self.blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = T.BG
        s._element.append(etree.fromstring(_TRANSITION))
        return s

    def cover(self, title: str, subtitle: str, category: str, meta: str = "", notes: str = "") -> None:
        s = self._new()
        text_box(s, L.left, 0.6, 8, 0.3, category, size=T.TYPE.cover_category, color=T.ACCENT_TEXT, bold=True)
        text_box(s, L.left, 2.3, L.width, 1.6, title, size=T.TYPE.cover_title, color=T.INK, bold=True, line_spacing=1.05)
        line(s, L.left, 3.95, 1.5, color=T.ACCENT, weight=3)
        text_box(s, L.left, 4.25, L.width, 0.5, subtitle, size=T.TYPE.cover_subtitle, color=T.GRAY)
        line(s, L.left, 6.00, L.width)
        if meta:
            text_box(s, L.left, 6.15, L.width, 0.4, meta, size=T.TYPE.cover_meta, color=T.MUTED)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def slide(self, ref: str, title: str, blocks: Sequence[tuple[str, dict[str, Any]]], notes: str = "") -> None:
        s = self._new()
        text_box(s, L.left, 0.46, 9.5, 0.25, ref, size=T.TYPE.slide_ref, color=T.ACCENT_TEXT, bold=True)
        text_box(s, L.left, 0.70, L.width, 0.82, title, size=T.TYPE.slide_title, color=T.INK, bold=True, line_spacing=1.05)
        where = f"第 {self.n} 頁「{title}」"
        for kind, _ in blocks:
            if kind not in BLOCKS:
                raise SpecError(f"{where}：未知區塊 {kind}（可用：{', '.join(BLOCKS)}）")
        main = [b for b in blocks if b[0] != "note"]
        tail = [b for b in blocks if b[0] == "note"]
        tail_h = (L.note_h + L.gap) if tail else 0.0
        avail = L.bottom - L.top - tail_h

        # 計算固定高度區塊與彈性區塊配置
        fixed_total = 0.0
        flex_count = 0
        for kind, kw in main:
            if "h" in kw or kind == "banner":
                fixed_total += planned_height(kind, kw, avail)
            else:
                flex_count += 1
        rem = max(0.5, avail - fixed_total - L.gap * max(0, len(main) - 1))
        flex_share = rem / max(1, flex_count)

        y = L.top
        if len(main) == 1:
            actual_h = planned_height(main[0][0], main[0][1], avail)
            y += max(0.0, (avail - actual_h) / 2)

        for kind, kw in main:
            share = planned_height(kind, kw, avail) if ("h" in kw or kind == "banner") else flex_share
            draw_kw = {**kw, "assets": self.assets} if kind == "shots" else kw  # 圖片路徑相對於簡報目錄
            try:
                y += BLOCKS[kind](s, y, height=share, **draw_kw) + L.gap
            except SpecError as e:
                raise SpecError(f"{where}的 {kind} 區塊：{e}") from None
        if y - L.gap > L.top + avail + _OVERFLOW_TOLERANCE:
            raise SpecError(f"{where}：內容畫到 y={y - L.gap:.2f} in，超出可用範圍（到 {L.top + avail:.2f} in）；減少區塊或調小 h")

        for kind, kw in tail:
            BLOCKS[kind](s, L.bottom - L.note_h, **kw)

        line(s, L.left, L.footer_rule, L.width)
        text_box(s, L.left, L.footer_text, 8, 0.25, self.short, size=T.TYPE.footer, color=T.MUTED)
        text_box(s, L.right - 1.0, L.footer_text, 1.0, 0.25, str(self.n), size=T.TYPE.footer, color=T.MUTED, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def save(self, path: str) -> None:
        self.prs.save(path)


def render(spec: dict[str, Any], base_dir: Path | None = None) -> Deck:
    """由規格產出簡報。`base_dir` 是簡報目錄：規格裡的圖片路徑相對於它。"""
    d = Deck(spec["short_title"], Path(base_dir) if base_dir else None)
    cover = dict(spec["cover"])
    cover.setdefault("meta", author_of(spec))  # 簡報封面不印日期
    d.cover(**cover)
    for ref, title, blocks, *extra in spec["slides"]:
        d.slide(ref, title, blocks, notes=extra[0] if extra else "")
    return d
