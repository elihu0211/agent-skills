"""佈局與視覺圖表引擎：由宣告式規格直接產出 PPTX。

繪製原語在 `_draw.py`，圖表區塊（架構拓撲、跨泳道時序、量化長條、時間軸、論證版面…）在 `blocks.py`；
本檔只負責一頁一頁的版面配置（`Deck`）與由規格產出整份簡報（`render`）。
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import deck_template
import theme as T
from blocks import BLOCKS, planned_height
from lxml import etree
from qmd_export import SpecError, author_of

L = T.LAYOUT

__all__ = ["BLOCKS", "Deck", "SpecError", "planned_height", "render"]

_TRANSITION = '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" spd="med"><p:fade/></p:transition>'
_OVERFLOW_TOLERANCE = 0.02  # 英吋（約 1.5 pt）：容許浮點與手調的微小誤差，再多就是規格寫太滿


class Deck:
    def __init__(self, short_title: str, assets: Path | None = None, template: str | Path | None = None) -> None:
        """`assets` 是簡報目錄：規格裡的圖片路徑相對於它（省略則用目前目錄）。

        `template` 是範本 `.pptx`（版面依名稱找，契約見 `deck_template.py`）；省略則由設計規格產生。
        """
        self.prs = deck_template.open_template(template)
        self.short = short_title
        self.assets = assets or Path.cwd()
        self.n = 0

    def _new(self, layout: str) -> tuple[Any, Any]:
        self.n += 1
        layout_obj = deck_template.layout_named(self.prs, layout)
        s = self.prs.slides.add_slide(layout_obj)
        s._element.append(etree.fromstring(_TRANSITION))
        return s, layout_obj

    @staticmethod
    def _fill(slide: Any, idx: int, text: str) -> None:
        """把文字放進佔位符；字型、字級與顏色由版面決定。空字串就移除佔位符，免得編輯時留著提示字。"""
        ph = slide.placeholders[idx]
        if not text:
            ph._element.getparent().remove(ph._element)
            return
        ph.text_frame.paragraphs[0].text = text

    def cover(self, title: str, subtitle: str, category: str, meta: str = "", notes: str = "") -> None:
        s, _ = self._new(deck_template.TITLE_SLIDE)
        self._fill(s, deck_template.IDX_REF, category)
        self._fill(s, deck_template.IDX_TITLE, title)
        self._fill(s, deck_template.IDX_BODY, subtitle)
        self._fill(s, deck_template.IDX_META, meta)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def slide(self, ref: str, title: str, blocks: Sequence[tuple[str, dict[str, Any]]], notes: str = "") -> None:
        s, layout = self._new(deck_template.TITLE_ONLY)
        self._fill(s, deck_template.IDX_REF, ref)
        self._fill(s, deck_template.IDX_TITLE, title)
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

        deck_template.add_footer_placeholders(s, layout, self.short)  # 頁尾細線在母片；短名與頁碼是版面的佔位符
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    def save(self, path: str) -> None:
        self.prs.save(path)


def render(spec: dict[str, Any], base_dir: Path | None = None, template: str | Path | None = None) -> Deck:
    """由規格產出簡報。`base_dir` 是簡報目錄：規格裡的圖片路徑相對於它；`template` 是範本 `.pptx`（省略則由設計規格產生）。"""
    d = Deck(spec["short_title"], Path(base_dir) if base_dir else None, template)
    cover = dict(spec["cover"])
    cover.setdefault("meta", author_of(spec))  # 簡報封面不印日期
    d.cover(**cover)
    for ref, title, blocks, *extra in spec["slides"]:
        d.slide(ref, title, blocks, notes=extra[0] if extra else "")
    props = d.prs.core_properties  # 檔案屬性：標題、作者、語言（螢幕閱讀器與檔案總管的搜尋用）
    props.title = str(spec.get("title") or cover["title"]).replace("\n", " ")
    props.author = author_of(spec)
    props.keywords = ", ".join(spec.get("tags", []))
    props.language = "zh-TW"
    return d
