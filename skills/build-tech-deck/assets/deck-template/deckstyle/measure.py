"""文字量測：估一段文字的寬度、會折成幾行、佔多高，引擎配置區塊高度與 lint 共用同一套估法。

寬度以字元估：全形 1.0 em、半形 0.55 em、空白 0.3 em（比實際字形略寬的保守值）。行高＝字級 × PowerPoint 的單倍行高
（`design.yml` 的 `type.line-em`，實測 1.2 em，與字型的 ascent＋descent 無關）× 段落的行距倍數。估算只用來配置高度與找出會折行的段落，不取代轉 PDF 後的逐頁目視。
"""

from __future__ import annotations

import unicodedata

# 允許自動折行的文字框名稱：區塊把這種框命名成它，`lint_wrap` 就不把其中的折行當違規（如參考文獻的長書目）。
REFLOW = "可折行文字"


def char_em(ch: str) -> float:
    """一個字元的寬（em）。"""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    return 0.3 if ch == " " else 0.55


def text_em(text: str) -> float:
    """一行文字的寬（em）。"""
    return sum(char_em(c) for c in text)


def _tokens(line: str) -> list[str]:
    """斷行單位：英文與數字以詞為單位（連同緊貼的半形標點），全形字逐字，空白各自一個。"""
    out: list[str] = []
    word = ""
    for ch in line:
        if ch == " " or char_em(ch) == 1.0:
            if word:
                out.append(word)
                word = ""
            out.append(ch)
        else:
            word += ch
    if word:
        out.append(word)
    return out


def wrap_count(text: str, size: float, width_in: float, first_in: float | None = None) -> int:
    """`text` 在可用寬 `width_in` 英吋裡折成幾行（貪婪法）。

    明確換行各起一行；`first_in` 是每段首行的可用寬（懸掛縮排時首行比續行寬）。單一詞比整行還寬時照字寬硬切。
    """
    em_in = size / 72.0
    total = 0
    for para in text.split("\n"):
        lines, cur, avail = 1, 0.0, (first_in if first_in is not None else width_in)
        for tok in _tokens(para):
            w = text_em(tok) * em_in
            if tok == " ":
                cur += w if cur else 0.0  # 行首的空白不佔寬
                continue
            if cur and cur + w > avail:
                lines += 1
                cur, avail = 0.0, width_in
            while w > avail:  # 超長的詞（網址、DOI）硬切
                lines += 1
                w -= avail
                avail = width_in
            cur += w
        total += lines
    return total


def line_height(size: float, line_em: float, spacing: float) -> float:
    """一行文字的高（英吋）：字級 × 字型單倍行高 × 行距倍數。"""
    return size * line_em * spacing / 72.0
