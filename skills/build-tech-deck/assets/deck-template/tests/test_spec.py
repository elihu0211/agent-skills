"""規格驗證：寫錯的規格在繪圖前就停下，訊息帶頁碼、區塊與欄位。"""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest
from conftest import one_slide

from deckstyle import blocks
from deckstyle.spec import (
    BLOCK_SCHEMA,
    SpecError,
    as_lines,
    check_table,
    from_yaml,
    kebab,
    slides_of,
    split_block,
    validate,
)


def test_template_spec_is_valid(template_spec: dict[str, Any]) -> None:
    validate(template_spec)


def test_schema_covers_exactly_the_engine_blocks() -> None:
    assert set(BLOCK_SCHEMA) == set(blocks.BLOCKS)


def test_template_exercises_every_block(template_spec: dict[str, Any]) -> None:
    used = {name for page in slides_of(template_spec) for name, _ in page["blocks"]}
    assert used == set(blocks.BLOCKS), f"範本沒涵蓋區塊：{set(blocks.BLOCKS) - used}"


def test_as_lines() -> None:
    assert as_lines(None) == []
    assert as_lines("a\n\nb") == ["a", "b"]
    assert as_lines(["x", "y"]) == ["x", "y"]


def test_kebab_and_from_yaml_round_trip_keys() -> None:
    assert kebab("short_title") == "short-title"
    data = from_yaml(
        {"short-title": "x", "slides": [{"col-w": [1], "blocks": [{"block": "arch-graph", "col-span": 2}]}]}
    )
    assert data == {"short_title": "x", "slides": [{"col_w": [1], "blocks": [{"block": "arch-graph", "col_span": 2}]}]}


def test_split_block_accepts_kebab_names() -> None:
    assert split_block("p", {"block": "arch-graph", "cols": 3}) == ("arch_graph", {"cols": 3})
    with pytest.raises(SpecError, match="區塊須寫成"):
        split_block("p", ["note", {}])


def test_check_table_rejects_bad_shapes() -> None:
    with pytest.raises(SpecError, match="沒有列"):
        check_table([], [1])
    with pytest.raises(SpecError, match="2 欄"):
        check_table([["a", "b"]], [1])
    with pytest.raises(SpecError, match="正數"):
        check_table([["a"]], [0])


def test_slides_of_fills_defaults() -> None:
    spec = one_slide([("note", {"lines": ["x"]})], notes="備註")
    spec["slides"].append({"type": "divider", "title": "章", "sub": "說明"})
    pages = slides_of(spec)
    assert [p["type"] for p in pages] == ["content", "divider"]
    assert pages[0]["notes"] == "備註"
    assert pages[0]["blocks"] == [("note", {"lines": ["x"]})]
    assert pages[1]["sub"] == "說明"
    assert pages[1]["ref"] == ""


def _bad(**top: Any) -> dict[str, Any]:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec.update(top)
    return spec


def _page(*blocks_: dict[str, Any], title: str = "t") -> dict[str, Any]:
    return _bad(slides=[{"title": title, "blocks": list(blocks_)}])


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"author": "a", "short_title": "x"}, "缺必填欄位"),
        ({"short_title": "x"}, "缺作者"),
        (_bad(author=[{"affiliation": "單位"}]), "缺 name"),
        (_bad(extra=1), "未知欄位 extra"),
        (_bad(slides=[]), "沒有任何頁面"),
        (_bad(slides=[("01", "t")]), "須為對應表"),
        (_bad(slides=[{"type": "bogus", "title": "t"}]), "未知頁面類型"),
        (_bad(slides=[{"type": "divider"}]), "缺必填欄位 title"),
        (_bad(slides=[{"title": "  ", "blocks": [{"block": "note", "lines": ["x"]}]}]), "主標題不可空白"),
        (_bad(slides=[{"title": "t", "blocks": []}]), "blocks 不可空"),
        (_bad(slides=[{"title": "t", "blocks": "note"}]), "blocks 須為清單"),
        (_page({"lines": ["x"]}), "區塊須寫成"),
        (_page({"block": "nope"}), "未知區塊 nope"),
        (_page({"block": "note"}), "缺必填欄位 lines"),
        (_page({"block": "note", "lines": ["x"], "color": "red"}), "未知欄位 color"),
        (_page({"block": "banner", "kind": "purple", "title": "x"}), "不是合法的 kind"),
        (_page({"block": "cards", "items": []}), "items 不可為空"),
        (_page({"block": "cards", "items": [{"kind": "gray"}]}), r"cards 區塊的 items\[1\]"),
        (_page({"block": "cards", "items": "abc"}), "須為清單"),
        (_page({"block": "table", "rows": [["a", "b"]], "col_w": [1]}), "2 欄"),
        (_page({"block": "table", "rows": [[["a", "nope"]]], "col_w": [1]}), r"\[文字, kind\]"),
        (_page({"block": "table", "rows": [["a"]], "col_w": [1], "aligns": ["middle"]}), "aligns"),
        (
            _page({"block": "chart", "categories": ["a"], "series": [{"name": "s", "values": [1]}], "type": "radar"}),
            "type",
        ),
        (
            _page({"block": "note", "lines": ["見（Lin & Huang", 2026, "§3.2）"]}),
            r"lines 第 2 項須為字串.*2026.*半形逗號",
        ),
        (_page({"block": "kpi", "items": [{"value": 40, "label": "件數"}]}), r"items\[1\]：value 須為字串"),
        (_page({"block": "cards", "items": [{"title": True}]}), "title 須為字串"),
        (_page({"block": "references", "items": ["a", 3]}), "items 第 2 項須為字串"),
        (
            _bad(slides=[{"title": "t", "notes": 3, "blocks": [{"block": "note", "lines": ["x"]}]}]),
            "notes 須為字串或字串清單",
        ),
        (_bad(subtitle=2026), "subtitle 須為字串"),
        (_bad(lint={"deny": "shop"}), "字串清單"),
        (_bad(lint={"bogus": []}), "未知欄位 bogus"),
    ],
)
def test_invalid_specs_are_rejected(spec: dict[str, Any], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        validate(spec)


def test_error_message_uses_the_names_users_write() -> None:
    """訊息裡的鍵與區塊名稱用 kebab-case（使用者寫的樣子），不是內部的 snake_case。"""
    with pytest.raises(SpecError, match="short-title"):
        validate({"author": "a", "title": "t"})
    with pytest.raises(SpecError, match="arch-graph"):
        validate(_page({"block": "arch_graph"}))


def test_error_message_names_page_and_block() -> None:
    with pytest.raises(SpecError, match=r"第 2 頁「流程總覽」的 note 區塊"):
        validate(_page({"block": "note"}, title="流程總覽"))


def test_validate_does_not_mutate(template_spec: dict[str, Any]) -> None:
    before = copy.deepcopy(template_spec)
    validate(template_spec)
    assert template_spec == before


def test_stdlib_only_modules_do_not_import_pptx() -> None:
    """spec、design、config、outline、schema 只用標準庫與 PyYAML，沒有 python-pptx 的環境（守門）也要載得進來。"""
    pkg = Path(blocks.__file__).parent
    heavy = {"pptx", "lxml", "PIL"}
    sibling_heavy = {"blocks", "draw", "engine", "theme", "template", "lint", "export", "cli", "preview"}
    for name in ("spec", "design", "config", "outline", "schema", "yamlio"):
        tree = ast.parse((pkg / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                mods = {top} if node.level == 0 else {a.name for a in node.names} | ({top} if top else set())
            else:
                continue
            assert not mods & heavy, f"{name}.py 匯入了 {mods & heavy}"
            assert not mods & sibling_heavy, f"{name}.py 匯入了需要 python-pptx 的 {mods & sibling_heavy}"
