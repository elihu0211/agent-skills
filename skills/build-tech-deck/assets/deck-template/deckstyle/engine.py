"""版面配置與整份簡報的產出：由宣告式規格直接畫出 PPTX。

每一頁建在 `template.py` 產生的具名版面上：標題、章節標籤、頁尾與頁碼是真正的 placeholder，
繪圖原語（`draw.py`）與區塊（`blocks.py`：架構拓撲、跨泳道時序、量化長條、原生圖表、大數字、表格…）畫在其上。
本檔負責一頁一頁的版面配置（`Deck`）與由規格產出整份簡報（`render`、`build`）。
規格寫錯（欄位缺漏、未知區塊、邊引用不存在的節點、內容超出頁面…）丟 `SpecError`，訊息帶頁碼與區塊名稱。
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from lxml import etree
from pptx.oxml import parse_xml

from . import config, template
from .blocks import BLOCKS, planned_height
from .draw import line
from .spec import SpecError, slides_of, validate
from .theme import Theme

__all__ = ["Deck", "SpecError", "build", "render"]

_TRANSITIONS = {
    "fade": '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" spd="med"><p:fade/></p:transition>',
}
_OVERFLOW_TOLERANCE = 0.02  # 英吋（約 1.5 pt）：容許浮點與手調的微小誤差，再多就是規格寫太滿
_NSDECL = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)


def _draw_block(t: Theme, slide: Any, kind: str, kw: Mapping[str, Any], y: float, share: float, assets: Path) -> float:
    """畫一個區塊並回傳實際佔用的高度。沒有自己 `h` 欄位的區塊，規格的 `h` 就是配給它的高度；`shots` 另帶簡報目錄。"""
    fn = BLOCKS[kind]
    params = inspect.signature(fn).parameters
    kw = dict(kw)
    if "h" not in params:
        fixed = kw.pop("h", None)
        if fixed is not None:
            share = float(fixed)
    if "assets" in params:
        kw["assets"] = assets
    return fn(t, slide, y, height=share, **kw)


def _placeholder(slide: Any, idx: int) -> Any | None:
    return next((p for p in slide.placeholders if p.placeholder_format.idx == idx), None)


def _set_text(t: Theme, ph: Any, text: str) -> None:
    """寫入 placeholder：`\\n` 是同一段內的換行；字級、粗細與顏色繼承版面。"""
    par = ph.text_frame.paragraphs[0]
    for i, part in enumerate(text.split("\n")):
        if i:
            par.add_line_break()
        run = par.add_run()
        run.text = part
        run._r.get_or_add_rPr().set("lang", t.lang)


def _fill(t: Theme, slide: Any, idx: int, text: str) -> None:
    """填版面上的 placeholder；沒有內容就移除它，不留下「按一下以新增文字」的空框。"""
    ph = _placeholder(slide, idx)
    if ph is None:
        return
    if text:
        _set_text(t, ph, text)
    else:
        ph._element.getparent().remove(ph._element)


class Deck:
    def __init__(self, t: Theme, short_title: str, assets: Path | None = None) -> None:
        """`assets` 是簡報目錄：規格裡的圖片路徑相對於它（省略則用目前目錄）。"""
        self.t = t
        self.prs = template.build(t)
        self.layouts = {layout.name: layout for layout in self.prs.slide_layouts}
        self.short = short_title
        self.assets = assets or Path.cwd()
        self.n = 0

    # ---- 頁面骨架 ----

    def _new(self, layout: str, title: str, notes: str = "") -> Any:
        self.n += 1
        s = self.prs.slides.add_slide(self.layouts[layout])
        if xml := _TRANSITIONS.get(self.t.page.transition):
            s._element.append(etree.fromstring(xml))
        assert s.shapes.title is not None  # 每個內容與封面版面都有標題 placeholder
        _set_text(self.t, s.shapes.title, title)
        if notes:
            frame = s.notes_slide.notes_text_frame
            assert frame is not None  # 剛建立的備註頁一定有文字框
            frame.text = notes
        return s

    def _footer(self, s: Any) -> None:
        """頁尾文字與頁碼：版面 placeholder 的頁面版本。頁碼是欄位，換頁序會自動更新。"""
        if not self.t.page.footer:
            return
        lang = self.t.lang
        tree = s.shapes._spTree
        ftr_id = s.shapes._next_shape_id
        tree.append(
            parse_xml(
                f'<p:sp {_NSDECL}><p:nvSpPr><p:cNvPr id="{ftr_id}" name="頁尾"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                f'<p:nvPr><p:ph type="ftr" sz="quarter" idx="{template.IDX_FTR}"/></p:nvPr></p:nvSpPr><p:spPr/>'
                f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="{lang}"/><a:t>{escape(self.short)}</a:t></a:r></a:p></p:txBody></p:sp>'
            )
        )
        tree.append(
            parse_xml(
                f'<p:sp {_NSDECL}><p:nvSpPr><p:cNvPr id="{ftr_id + 1}" name="頁碼"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                f'<p:nvPr><p:ph type="sldNum" sz="quarter" idx="{template.IDX_SLDNUM}"/></p:nvPr></p:nvSpPr><p:spPr/>'
                f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:fld id="{{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}}" type="slidenum">'
                f'<a:rPr lang="{lang}"/><a:t>{self.n}</a:t></a:fld></a:p></p:txBody></p:sp>'
            )
        )

    def _bottom_rule(self, s: Any, meta: str) -> None:
        """封面與結語頁：有底部說明才畫它上方的細線。"""
        if meta:
            line(self.t, s, self.t.layout.left, self.t.frame.meta_rule_y, self.t.layout.width)

    # ---- 頁面 ----

    def cover(self, title: str, subtitle: str, category: str, meta: str = "", notes: str = "") -> None:
        s = self._new("Title Slide", title, notes)
        _fill(self.t, s, template.IDX_SUB, subtitle)
        _fill(self.t, s, template.IDX_REF, category)
        _fill(self.t, s, template.IDX_META, meta)
        self._bottom_rule(s, meta)

    def divider(self, title: str, sub: str = "", ref: str = "", notes: str = "") -> None:
        """章節分隔頁：章號小標、章名大字、一句說明，與封面共用主色細線。"""
        s = self._new("Section Header", title, notes)
        _fill(self.t, s, template.IDX_SUB, sub)
        _fill(self.t, s, template.IDX_REF, ref)
        self._footer(s)

    def closing(self, title: str, sub: str = "", meta: str = "", notes: str = "") -> None:
        """結語頁：一句話（謝謝、歡迎提問）加聯絡資訊，版型同封面。"""
        s = self._new("Closing", title, notes)
        _fill(self.t, s, template.IDX_SUB, sub)
        _fill(self.t, s, template.IDX_META, meta)
        self._bottom_rule(s, meta)

    def slide(self, ref: str, title: str, blocks: Sequence[tuple[str, dict[str, Any]]], notes: str = "") -> None:
        t, lay = self.t, self.t.layout
        s = self._new("Title Only", title, notes)
        _fill(t, s, template.IDX_REF, ref)
        where = f"第 {self.n} 頁「{title}」"
        for kind, _ in blocks:
            if kind not in BLOCKS:
                raise SpecError(f"{where}：未知區塊 {kind}（可用：{', '.join(BLOCKS)}）")
        main = [b for b in blocks if b[0] != "note"]
        tail = [b for b in blocks if b[0] == "note"]
        tail_h = (lay.note_h + lay.gap) if tail else 0.0
        avail = lay.bottom - lay.top - tail_h

        # 固定高度（帶 h 或 banner）先扣掉，剩下的均分給彈性區塊
        fixed_total, flex_count = 0.0, 0
        for kind, kw in main:
            if "h" in kw or kind == "banner":
                fixed_total += planned_height(t, kind, kw, avail)
            else:
                flex_count += 1
        rem = max(0.5, avail - fixed_total - lay.gap * max(0, len(main) - 1))
        flex_share = rem / max(1, flex_count)

        y = lay.top
        if len(main) == 1:  # 單一區塊的頁面垂直置中
            y += max(0.0, (avail - planned_height(t, main[0][0], main[0][1], avail)) / 2)

        for kind, kw in main:
            share = planned_height(t, kind, kw, avail) if ("h" in kw or kind == "banner") else flex_share
            try:
                y += _draw_block(t, s, kind, kw, y, share, self.assets) + lay.gap
            except SpecError as e:
                raise SpecError(f"{where}的 {kind} 區塊：{e}") from None
        if y - lay.gap > lay.top + avail + _OVERFLOW_TOLERANCE:
            raise SpecError(
                f"{where}：內容畫到 y={y - lay.gap:.2f} in，超出可用範圍（到 {lay.top + avail:.2f} in）；減少區塊或調小 h"
            )

        for kind, kw in tail:
            BLOCKS[kind](t, s, lay.bottom - lay.note_h, **kw)
        self._footer(s)

    def save(self, path: str | Path) -> None:
        self.prs.save(str(path))


def render(spec: Mapping[str, Any], base_dir: Path | None = None, theme: Theme | None = None) -> Deck:
    """由規格產出簡報。`base_dir` 是簡報目錄：規格裡的圖片路徑相對於它，品牌（`_brand.yml`）也從這裡往上找。

    `theme` 省略時由 `base_dir`（或目前目錄）往上找品牌。先 `validate` 再畫，錯誤都是 `SpecError`。
    """
    validate(spec)
    base = Path(base_dir) if base_dir else None
    lang = spec.get("lang", config.DEFAULT_LANG)
    t = theme or Theme.load(base, lang)
    d = Deck(t, spec["short_title"], base)
    authors = config.normalize_authors(spec["author"])
    d.cover(
        title=spec["title"],
        subtitle=spec["subtitle"],
        category=spec["category"],
        meta=spec.get("meta", config.format_author(authors)),  # 封面預設印「單位 姓名」；日期放文件屬性，不印在封面
        notes=spec.get("notes", ""),
    )
    for page in slides_of(spec):
        match page["type"]:
            case "divider":
                d.divider(page["title"], page["sub"], page["ref"], page["notes"])
            case "closing":
                d.closing(page["title"], page["sub"], page["meta"], page["notes"])
            case _:
                d.slide(page["ref"], page["title"], page["blocks"], page["notes"])
    props = d.prs.core_properties
    props.title = str(spec["title"]).replace("\n", "")
    props.author = config.author_names(authors)
    if date := spec.get("date"):  # 有日期就固定建立與修改時間，同一份規格每次建出同樣的文件屬性
        try:
            props.created = props.modified = datetime.fromisoformat(str(date))
        except ValueError:
            raise SpecError(f"date 須為 YYYY-MM-DD：{date!r}") from None
    return d


def build(spec: Mapping[str, Any], out: str | Path, base_dir: Path | None = None, theme: Theme | None = None) -> int:
    """產出並存檔，回傳頁數。"""
    d = render(spec, base_dir, theme)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    d.save(out)
    return d.n
