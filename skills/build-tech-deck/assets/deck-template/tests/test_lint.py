"""lint：範本必須通過；折行、孤字、單行過長與代碼名稱都要被抓到。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import one_slide

from deckstyle import lint

Build = Callable[[dict[str, Any]], Path]


def _cards(body: str, title: str = "標題", n: int = 3) -> dict[str, Any]:
    items = [{"kind": "gray", "title": "卡", "body": [body]}] * n
    return one_slide([("cards", {"items": items})], title)


def _kinds(path: Path) -> set[str]:
    return {i["type"] for i in lint.lint_wrap(path)}


def test_template_is_clean(template_pptx: Path, template_spec: dict[str, Any]) -> None:
    assert lint.lint_wrap(template_pptx) == []
    deny = template_spec["lint"]["deny"]
    assert lint.lint_names(template_pptx, deny) == []


def test_short_text_passes(build_spec: Build) -> None:
    assert lint.lint_wrap(build_spec(_cards("短短一行"))) == []


def test_long_card_line_wraps(build_spec: Build) -> None:
    assert "折行" in _kinds(build_spec(_cards("這是一行寫得太長太長太長太長太長太長的卡片內文")))


def test_orphan_is_detected(build_spec: Build) -> None:
    # 3 欄卡片可用寬約 250pt：17 字加條列符號約 261pt，折成兩行後末行只剩 1 字
    assert "孤字" in _kinds(build_spec(_cards("一二三四五六七八九十一二三四五六七")))


def test_long_title_is_flagged(build_spec: Build) -> None:
    assert (
        _kinds(build_spec(_cards("短", title="這個標題寫得實在太長太長太長太長太長太長太長太長太長太長太長太長了")))
        != set()
    )


def test_single_line_frame_overflow_is_flagged(tmp_path: Path) -> None:
    """不折行的單行框（word_wrap 關閉）超過框寬就算違規，不受安全係數影響。"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    box = prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(0.5))
    box.text_frame.word_wrap = False
    run = box.text_frame.paragraphs[0].add_run()
    run.text = "這一行文字遠遠超過兩英吋寬的框"
    run.font.size = Pt(20)
    path = tmp_path / "raw.pptx"
    prs.save(str(path))
    assert _kinds(path) == {"單行過長"}


def test_safety_factor_is_adjustable(build_spec: Build) -> None:
    path = build_spec(_cards("這一行有十四個字沒錯吧吧吧吧"))
    assert lint.lint_wrap(path, safety=0.5) != []
    assert lint.lint_wrap(path, safety=1.0) == []


def test_table_cells_are_checked(build_spec: Build) -> None:
    rows = [["欄一", "欄二"], ["這個儲存格寫得非常非常非常非常非常非常非常非常非常非常非常非常非常非常長", "短"]]
    spec = one_slide([("table", {"rows": rows, "col_w": [1, 1]})])
    assert any(i["where"].startswith("表格") for i in lint.lint_wrap(build_spec(spec)))


# ---- 白話命名 ----


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("呼叫 get_user_name 取得資料", "識別字"),
        ("設定寫在 config.toml", "檔案名"),
        ("打 /v2/items 端點", "路徑或端點"),
    ],
)
def test_scan_names_builtin_rules(text: str, label: str) -> None:
    assert any(label in found for found, _ in lint.scan_names(text))


def test_scan_names_clean_text() -> None:
    assert lint.scan_names("法規檢索與租戶入口，ISO/IEC 17788 與 PostgreSQL") == []


def test_deny_matches_whole_words_only() -> None:
    assert lint.scan_names("使用 shop-api 服務", deny=["shop-api"]) == [("倉庫或服務代號", "shop-api")]
    assert lint.scan_names("shop-apiary", deny=["shop-api"]) == []


def test_allow_suppresses_false_positive() -> None:
    assert lint.scan_names("a_b", allow=["a_b"]) == []


def test_lint_names_scans_slides_tables_and_notes(build_spec: Build) -> None:
    spec = one_slide(
        [("table", {"rows": [["欄", "值"], ["x", "load_data"]], "col_w": [1, 1]})],
        title="含 build_deck 的標題",
        notes="講稿提到 deck_spec.py",
    )
    path = build_spec(spec)
    where = {i["where"] for i in lint.lint_names(path)}
    assert where == {"投影片", "表格", "講稿備註"}
    assert {i["where"] for i in lint.lint_names(path, notes=False)} == {"投影片", "表格"}


def test_lint_names_dedupes_same_hit_per_slide(build_spec: Build) -> None:
    path = build_spec(one_slide([("note", {"lines": ["a_b 與 a_b 與 a_b"]})]))
    assert len([i for i in lint.lint_names(path) if i["text"] == "a_b"]) == 1


def test_formatters_name_the_slide() -> None:
    wrap = {"slide": 3, "where": "卡", "type": "折行", "text": "x", "width_pt": 300, "limit_pt": 200}
    assert "第 3 頁" in lint.format_wrap(wrap)
    assert "第 5 頁" in lint.format_names({"slide": 5, "where": "投影片", "type": "檔案名", "text": "a.py"})


def test_explicit_line_break_measures_each_line(build_spec: Build) -> None:
    """標題以明確換行排成兩行時，各行分開估寬；換行前後兩行加總當一行會誤報孤字。"""
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["title"] = "烘烤分選產線的 PLC 控制\n與本體專家系統整合"
    assert lint.lint_wrap(build_spec(spec)) == []
    spec["title"] = "烘烤分選產線的 PLC 控制與本體專家系統整合"  # 同樣的字不換行：一行放不下，要回報
    assert {i["type"] for i in lint.lint_wrap(build_spec(spec))} == {"孤字"}


def test_a_line_that_is_still_too_long_after_the_break_is_flagged(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["title"] = "第一行很短\n" + "這一行寫得實在太長太長太長太長太長太長太長太長太長太長太長太長太長太長太長了"
    assert lint.lint_wrap(build_spec(spec)) != []
