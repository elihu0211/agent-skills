"""簡報品質檢查：零折行與白話命名，讀建好的 `.pptx`。

- `lint_wrap`：以字級與字元寬度估算每段文字，找出會折行、孤字或單行過長的段落。全形 1.0 em、半形 0.55 em，
  粗體多估 `bold_extra`；門檻（安全係數、孤字字數）取自設計參數 `design.yml` 的 `lint`。估算不取代轉 PDF 後的逐頁目視。
- `lint_names`：投影片與講稿備註不得出現讀者看不懂的代碼名稱（snake_case 識別字、檔名、路徑與端點，
  加上各簡報自己在規格 `lint.deny` 列出的倉庫與服務代號）。

兩者都回傳違規的 dict 清單（空清單＝通過），由 CLI 與測試共用。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.util import Emu

from . import design

DEFAULT_PT = 18.0  # run 沒指定字級時的預設
_DEFAULT_MARGIN = Emu(91440)  # 文字框沒指定邊距時，PowerPoint 的預設 0.1 英吋


def _char_em(ch: str) -> float:
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    return 0.3 if ch == " " else 0.55


@dataclass(frozen=True)
class _Inherited:
    """placeholder 沒在頁面上指定時，從版面與母片繼承的字級、粗細與左右內距。"""

    size: float = DEFAULT_PT
    bold: bool = False
    inset: Emu = _DEFAULT_MARGIN


def _inherited(slide: Any, shape: Any) -> _Inherited:
    """沿 頁面 → 版面 → 母片 查 placeholder 的樣式；不是 placeholder 就回傳預設。"""
    if not getattr(shape, "is_placeholder", False):
        return _Inherited()
    ph = shape.placeholder_format
    layout = slide.slide_layout
    chain = [
        p
        for src in (layout, layout.slide_master)
        for p in src.placeholders
        if p.placeholder_format.idx == ph.idx or p.placeholder_format.type == ph.type
    ]
    elems = [p._element for p in chain]
    is_title = ph.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
    style = layout.slide_master._element.xpath(f".//p:{'titleStyle' if is_title else 'bodyStyle'}/a:lvl1pPr/a:defRPr")
    defs = [d for e in elems for d in e.xpath(".//a:lstStyle/a:lvl1pPr/a:defRPr")] + style
    size = next((int(d.get("sz")) / 100 for d in defs if d.get("sz")), DEFAULT_PT)
    bold = next((d.get("b") == "1" for d in defs if d.get("b") is not None), False)
    insets = [e.xpath(".//a:bodyPr")[0].get("lIns") for e in elems if e.xpath(".//a:bodyPr")]
    inset = next((Emu(int(v)) for v in insets if v is not None), _DEFAULT_MARGIN)
    return _Inherited(size, bold, inset)


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _para_width_pt(par: Any, bold_extra: float, base: _Inherited) -> tuple[float, float]:
    """回傳（段落估算寬度 pt, 代表字級 pt）。run 沒指定字級與粗細時用繼承值。

    明確換行（`a:br`，標題裡的 `\\n`）把段落切成幾行，各行分開估寬，取最寬的一行：換行前後兩行不是一行。
    """
    lines, size = [0.0], base.size
    for el in par._p:
        if el.tag == f"{_A}br":
            lines.append(0.0)
        elif el.tag == f"{_A}r":
            props = el.find(f"{_A}rPr")
            sz = props.get("sz") if props is not None else None
            size = int(sz) / 100 if sz else size
            b_attr = props.get("b") if props is not None else None
            bold = base.bold if b_attr is None else b_attr in ("1", "true")
            text = "".join(t.text or "" for t in el.findall(f"{_A}t"))
            lines[-1] += sum(_char_em(c) for c in text) * size * (1 + bold_extra if bold else 1.0)
    return max(lines), size


def _frame_width_pt(shape: Any, frame: Any, base: _Inherited) -> float:
    left = frame.margin_left if frame.margin_left is not None else base.inset
    right = frame.margin_right if frame.margin_right is not None else base.inset
    return Emu(shape.width - left - right).pt


def _check_frame(
    no: int,
    label: str,
    frame: Any,
    avail_pt: float,
    slide_w_pt: float,
    left_pt: float,
    wraps: bool,
    safety: float,
    orphan_chars: float,
    bold_extra: float,
    base: _Inherited = _Inherited(),
) -> Iterator[dict[str, Any]]:
    for par in frame.paragraphs:
        text = "".join(r.text for r in par.runs)
        if not text.strip():
            continue
        width, size = _para_width_pt(par, bold_extra, base)
        if wraps:
            limit = avail_pt * safety
            if width > limit:
                lines = int(width // avail_pt) + 1
                tail = width - (lines - 1) * avail_pt
                kind = "孤字" if lines >= 2 and tail <= orphan_chars * size else "折行"
                yield {
                    "slide": no,
                    "where": label,
                    "type": kind,
                    "text": text[:40],
                    "width_pt": round(width),
                    "limit_pt": round(limit),
                }
        else:
            # 不折行的單行框（標題、分類標籤）：超過框寬（留 5% 餘裕）就會壓到版心外；不受安全係數影響
            limit = min(avail_pt * 0.95, slide_w_pt - left_pt)
            if width > limit:
                yield {
                    "slide": no,
                    "where": label,
                    "type": "單行過長",
                    "text": text[:40],
                    "width_pt": round(width),
                    "limit_pt": round(limit),
                }


def lint_wrap(path: str | Path, safety: float | None = None) -> list[dict[str, Any]]:
    """找出會折行、孤字或單行過長的段落。`safety` 省略則用集中參數的值。"""
    cfg = design.load().lint
    safety = cfg.safety if safety is None else safety
    prs = Presentation(str(path))
    slide_w_pt = Emu(prs.slide_width or 0).pt
    out: list[dict[str, Any]] = []
    for no, slide in enumerate(prs.slides, 1):
        for raw in slide.shapes:
            shape: Any = raw  # python-pptx 的型別標註把 BaseShape 當成沒有 text_frame／table
            if shape.has_text_frame:
                frame = shape.text_frame
                base = _inherited(slide, shape)
                out += _check_frame(
                    no,
                    shape.name,
                    frame,
                    _frame_width_pt(shape, frame, base),
                    slide_w_pt,
                    Emu(shape.left or 0).pt,
                    frame.word_wrap is not False,
                    safety,
                    cfg.orphan_chars,
                    cfg.bold_extra,
                    base,
                )
            elif shape.has_table:
                for r, row in enumerate(shape.table.rows):
                    for c, cell in enumerate(row.cells):
                        width = Emu(shape.table.columns[c].width - cell.margin_left - cell.margin_right).pt
                        out += _check_frame(
                            no,
                            f"表格[{r},{c}]",
                            cell.text_frame,
                            width,
                            slide_w_pt,
                            0,
                            True,
                            safety,
                            cfg.orphan_chars,
                            cfg.bold_extra,
                        )
    return out


# ---- 白話命名 ----

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("識別字（snake_case）", re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")),
    ("檔案名", re.compile(r"(?<![A-Za-z0-9_-])[\w-]+\.(?:py|toml|ya?ml|sql|env|sh|json|md|ipynb)(?![A-Za-z0-9_])")),
    ("路徑或端點", re.compile(r"(?<![A-Za-z0-9_)）/])/[a-z][a-z0-9_-]*(?:/[A-Za-z0-9_{}.-]+)*")),
)


def scan_names(text: str, deny: Iterable[str] = (), allow: Iterable[str] = ()) -> list[tuple[str, str]]:
    """一段文字裡的（違規類型, 字串）。`deny` 以字界比對、區分大小寫；`allow` 放行誤報。"""
    hits: list[tuple[str, str]] = []
    for label, pat in _RULES:
        hits += [(label, m.group(0)) for m in pat.finditer(text)]
    for word in deny:
        pat = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(word) + r"(?![A-Za-z0-9_-])")
        hits += [("倉庫或服務代號", m.group(0)) for m in pat.finditer(text)]
    allowed = set(allow)
    return [(label, hit) for label, hit in hits if hit not in allowed]


def _texts(prs: Any, notes: bool) -> Iterator[tuple[int, str, str]]:
    for no, slide in enumerate(prs.slides, 1):
        for raw in slide.shapes:
            shape: Any = raw
            if shape.has_text_frame:
                yield no, "投影片", shape.text_frame.text
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        yield no, "表格", cell.text_frame.text
        if notes and slide.has_notes_slide:
            yield no, "講稿備註", slide.notes_slide.notes_text_frame.text


def lint_names(
    path: str | Path, deny: Iterable[str] = (), allow: Iterable[str] = (), notes: bool = True
) -> list[dict[str, Any]]:
    """投影片與講稿備註裡的代碼名稱。"""
    prs = Presentation(str(path))
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    deny, allow = list(deny), list(allow)
    for no, where, text in _texts(prs, notes):
        for label, hit in scan_names(text, deny, allow):
            if (no, label, hit) in seen:
                continue
            seen.add((no, label, hit))
            out.append({"slide": no, "where": where, "type": label, "text": hit})
    return out


def format_wrap(issue: dict[str, Any]) -> str:
    return (
        f"第 {issue['slide']} 頁 {issue['where']}：{issue['type']}"
        f"（估 {issue['width_pt']}pt > 上限 {issue['limit_pt']}pt）「{issue['text']}」"
    )


def format_names(issue: dict[str, Any]) -> str:
    return f"第 {issue['slide']} 頁 {issue['where']}：{issue['type']}「{issue['text']}」，改成白話的功能名稱"
