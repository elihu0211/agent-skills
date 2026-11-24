"""文字量測：字寬、折行行數與行高的估法。"""

from __future__ import annotations

import pytest

from deckstyle.measure import char_em, line_height, text_em, wrap_count


def test_char_widths() -> None:
    assert (char_em("中"), char_em("Ａ"), char_em("a"), char_em(" ")) == (1.0, 1.0, 0.55, 0.3)
    assert text_em("中a ") == pytest.approx(1.85)


def test_cjk_wraps_at_any_character() -> None:
    # 72 pt 的字一個 1 吋寬：10 個全形字在 4 吋寬裡折成 3 行
    assert wrap_count("一" * 10, 72, 4.0) == 3


def test_english_wraps_between_words() -> None:
    # 每個 "abcd" 寬 4 × 0.55 = 2.2 吋：兩個詞放不進 4 吋，各占一行
    assert wrap_count("abcd abcd", 72, 4.0) == 2
    assert wrap_count("abcd abcd", 72, 5.0) == 1


def test_explicit_line_breaks_each_start_a_line() -> None:
    assert wrap_count("甲\n乙\n丙", 12, 5.0) == 3


def test_first_line_can_be_wider_for_a_hanging_indent() -> None:
    # 首行 6 吋放得下 6 字，續行 2 吋：8 字 → 首行 6 字、續行 2 字
    assert wrap_count("一" * 8, 72, 2.0, first_in=6.0) == 2
    assert wrap_count("一" * 8, 72, 2.0) == 4


def test_overlong_word_is_split() -> None:
    assert wrap_count("a" * 20, 72, 5.5) == 2  # 20 × 0.55 = 11 吋


def test_line_height() -> None:
    assert line_height(72, 1.4, 1.0) == pytest.approx(1.4)
