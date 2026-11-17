"""Theme：由品牌與設計參數組成的不可變物件，沒有全域狀態。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from conftest import write

from deckstyle import design, spec
from deckstyle.theme import Theme


def test_cards_match_spec_kinds(theme: Theme) -> None:
    """spec.KINDS（規格合法名單）與 theme.cards（實際樣式）是同一份。"""
    assert set(theme.cards) == set(spec.KINDS)


def test_colors_come_from_the_brand(theme: Theme) -> None:
    assert str(theme.accent) == theme.brand.hex("blue")
    assert str(theme.ink) == theme.brand.hex("ink")
    assert str(theme.tones["red"].line) == theme.brand.hex("rose")


def test_theme_is_immutable(theme: Theme) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        theme.ink = theme.white  # type: ignore[misc]


def test_two_brands_make_two_themes(repo: Path) -> None:
    """品牌由目錄往上搜尋，不同目錄的簡報可以有不同品牌，互不影響。"""
    other = (repo / "_brand.yml").read_text(encoding="utf-8").replace('blue: "#2563EB"', 'blue: "#0000FF"')
    write(repo / "course" / "_brand.yml", other)
    a, b = Theme.load(repo), Theme.load(repo / "course")
    assert str(a.accent) == "2563EB"
    assert str(b.accent) == "0000FF"


def test_design_is_replaceable_without_touching_globals(theme: Theme) -> None:
    d = design.load()
    quiet = dataclasses.replace(d, page=dataclasses.replace(d.page, footer=False))
    t2 = Theme.build(theme.brand, quiet)
    assert t2.page.footer is False
    assert theme.page.footer is True


def test_lang_is_a_theme_property() -> None:
    from deckstyle.brand import discover

    assert Theme.build(discover(Path(__file__).parent), lang="en").lang == "en"


def test_aliases_follow_design(theme: Theme) -> None:
    assert theme.layout is theme.design.layout
    assert theme.line_strong == theme.design.geometry.strong_pt
    assert theme.font == theme.brand.font
