"""字數上限表（references/patterns.md）與引擎的實測一致：上限那一格放得進一行，多一個字就被 lint 抓到。

表裡的數字是「單行放得進去的全形字數」，由零折行 lint 以預設安全係數實測。改了字級、邊距或欄寬，
這裡會失敗，提醒同步更新表。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import one_slide

from deckstyle import lint

Build = Callable[..., Path]
CH = "字"


def _cards(cols: int, n: int) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    return [("cards", {"items": [{"kind": "gray", "title": "卡", "body": [CH * n]}] * cols})], "標題"


def _columns(cols: int, n: int) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    return [("columns", {"cols": [{"title": "欄", "items": [CH * n]}] * cols})], "標題"


def _flow_title(k: int, n: int) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    return [("flow", {"items": [{"kind": "gray", "title": CH * n}] * k})], "標題"


def _flow_body(k: int, n: int) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    return [("flow", {"items": [{"kind": "gray", "title": "題", "body": CH * n}] * k})], "標題"


def _table(cols: int, n: int) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    return [("table", {"col_w": [1] * cols, "rows": [["欄"] * cols, [CH * n] * cols]})], "標題"


# (名稱, 產生器, 上限)：與 patterns.md 的字數上限速查表同一份
LIMITS: list[tuple[str, Callable[[int], tuple[list[tuple[str, dict[str, Any]]], str]], int]] = [
    ("主標題", lambda n: ([("note", {"lines": ["x"]})], CH * n), 24),
    ("note 單行", lambda n: ([("note", {"lines": [CH * n]})], "標題"), 46),
    ("banner 標題", lambda n: ([("banner", {"kind": "gray", "title": CH * n})], "標題"), 38),
    ("banner 內文", lambda n: ([("banner", {"kind": "gray", "title": "題", "body": CH * n})], "標題"), 48),
    *[(f"cards {c} 欄", lambda n, c=c: _cards(c, n), lim) for c, lim in ((2, 20), (3, 12), (4, 10), (5, 7))],
    *[(f"columns {c} 欄", lambda n, c=c: _columns(c, n), lim) for c, lim in ((2, 21), (3, 14))],
    *[(f"flow {k} 節點標題", lambda n, k=k: _flow_title(k, n), lim) for k, lim in ((3, 12), (4, 8), (5, 7), (6, 6))],
    *[(f"flow {k} 節點內文", lambda n, k=k: _flow_body(k, n), lim) for k, lim in ((3, 16), (4, 11), (5, 9), (6, 7))],
    *[(f"table {c} 欄", lambda n, c=c: _table(c, n), lim) for c, lim in ((3, 15), (4, 11), (5, 9))],
]


@pytest.mark.parametrize(("name", "make", "limit"), LIMITS, ids=[x[0] for x in LIMITS])
def test_limit_fits_and_one_more_does_not(name: str, make: Callable[[int], Any], limit: int, build_spec: Build) -> None:
    blocks, title = make(limit)
    assert lint.lint_wrap(build_spec(one_slide(blocks, title))) == [], f"{name}：{limit} 字應放得進一行"
    blocks, title = make(limit + 1)
    assert lint.lint_wrap(build_spec(one_slide(blocks, title))) != [], f"{name}：{limit + 1} 字應被抓到"
