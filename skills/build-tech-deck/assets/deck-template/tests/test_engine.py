"""引擎：範本建得出來、每個區塊都畫得出東西、版面錯誤停在建置時。"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import TEMPLATE, one_slide
from pptx import Presentation
from pptx.util import Inches

from deckstyle import design, engine
from deckstyle.spec import SpecError
from deckstyle.theme import Theme

Build = Callable[..., Path]


def _texts(path: Path, slide_no: int) -> str:
    slide = list(Presentation(str(path)).slides)[slide_no - 1]
    return "\n".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def _without(theme: Theme, **page: Any) -> Theme:
    """同一個品牌，換掉頁面行為（轉場、頁尾）的 Theme；不動任何全域設定。"""
    d = design.load()
    return Theme.build(theme.brand, dataclasses.replace(d, page=dataclasses.replace(d.page, **page)))


def test_template_builds_all_pages(template_pptx: Path, template_spec: dict[str, Any], theme: Theme) -> None:
    prs = Presentation(str(template_pptx))
    assert len(prs.slides) == len(template_spec["slides"]) + 1  # 加封面
    assert prs.slide_width == Inches(theme.layout.slide_w)


def test_every_page_has_a_title_and_notes_survive(template_pptx: Path) -> None:
    prs = Presentation(str(template_pptx))
    assert all(any(sh.has_text_frame and sh.text_frame.text.strip() for sh in s.shapes) for s in prs.slides)
    assert any(s.has_notes_slide and s.notes_slide.notes_text_frame.text for s in prs.slides)


def test_footer_has_short_title_and_page_number(template_pptx: Path) -> None:
    text = _texts(template_pptx, 3)
    assert "現場雙碼掃描 · 技術提案" in text
    assert "3" in text


def test_cover_prints_affiliation_then_name(template_pptx: Path) -> None:
    assert "範例單位 範例作者" in _texts(template_pptx, 1)


def test_cover_meta_can_be_overridden(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["meta"] = "自訂的底部說明"
    assert "自訂的底部說明" in _texts(build_spec(spec), 1)


def test_cover_has_no_footer(template_pptx: Path) -> None:
    assert "現場雙碼掃描 · 技術提案" not in _texts(template_pptx, 1)


def test_core_properties_follow_spec(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec.update(title="第一行\n第二行", date="2026-01-01", author=[{"name": "甲"}, {"name": "乙"}])
    props = Presentation(str(build_spec(spec))).core_properties
    assert props.title == "第一行第二行"
    assert props.author == "甲、乙"
    assert props.created == datetime(2026, 1, 1)
    assert props.language == "zh-TW"


def test_bad_date_is_rejected(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["date"] = "昨天"
    with pytest.raises(SpecError, match="YYYY-MM-DD"):
        build_spec(spec)


def test_divider_and_closing_pages(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["slides"] += [
        {"type": "divider", "ref": "第二部分", "title": "章名", "sub": "一句說明"},
        {"type": "closing", "title": "謝謝", "sub": "下一步", "meta": "單位"},
    ]
    path = build_spec(spec)
    assert {"章名", "一句說明", "第二部分"} <= set(_texts(path, 3).split("\n"))
    closing = _texts(path, 4)
    assert "謝謝" in closing
    assert "單位" in closing


def test_ref_is_optional(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["slides"] = [{"title": "只有標題", "blocks": [{"block": "note", "lines": ["x"]}]}]
    assert "只有標題" in _texts(build_spec(spec), 2)


def test_footer_can_be_turned_off_without_global_state(theme: Theme, build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["short_title"] = "唯一的簡報短名"
    assert "唯一的簡報短名" in _texts(build_spec(spec), 2)
    assert "唯一的簡報短名" not in _texts(build_spec(spec, _without(theme, footer=False)), 2)
    assert "唯一的簡報短名" in _texts(build_spec(spec), 2)  # 原 theme 不受影響


def test_transition_none_leaves_no_transition(theme: Theme, build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    with_fade = list(Presentation(str(build_spec(spec))).slides)[1]
    assert "transition" in with_fade._element.xml
    without = list(Presentation(str(build_spec(spec, _without(theme, transition="none")))).slides)[1]
    assert "transition" not in without._element.xml


# ---- 區塊與版面 ----


@pytest.mark.parametrize(
    "blocks",
    [
        [("kpi", {"items": [{"value": "9", "label": "指標"}]})],
        [("kpi", {"items": [{"value": str(i), "label": f"指標{i}", "sub": "說明"} for i in range(5)]})],
        [("chart", {"categories": ["甲", "乙"], "series": [{"name": "數量", "values": [1, 2]}], "type": "line"})],
        [("chart", {"categories": ["甲", "乙"], "series": [{"name": "數量", "values": [1, 2]}], "type": "bar"})],
        [("chart", {"categories": ["甲", "乙"], "series": [{"name": "數量", "values": [1, 2]}], "type": "pie"})],
        [
            (
                "chart",
                {
                    "categories": ["甲", "乙"],
                    "series": [{"name": "a", "values": [1, 2]}, {"name": "b", "values": [2, 1]}],
                },
            )
        ],
        [("columns", {"cols": [{"title": "一", "items": ["x"]}, {"title": "二", "items": ["y"]}]})],
        [("cards", {"items": [{"title": "無 kind", "body": "預設灰底"}]})],
        [
            (
                "table",
                {
                    "rows": [["a", "b"], ["1", ["2", "red"]]],
                    "col_w": [1, 1],
                    "aligns": ["left", "right"],
                    "highlight": [1],
                },
            )
        ],
    ],
)
def test_block_variants_render(build_spec: Build, blocks: list[tuple[str, dict[str, Any]]]) -> None:
    build_spec(one_slide(blocks))


def test_chart_series_length_must_match_categories(build_spec: Build) -> None:
    spec = one_slide([("chart", {"categories": ["甲", "乙"], "series": [{"name": "s", "values": [1]}]})])
    with pytest.raises(SpecError, match="1 個值"):
        build_spec(spec)


def test_pie_takes_one_series(build_spec: Build) -> None:
    series = [{"name": "a", "values": [1]}, {"name": "b", "values": [2]}]
    with pytest.raises(SpecError, match="圓餅圖只收一個系列"):
        build_spec(one_slide([("chart", {"categories": ["甲"], "series": series, "type": "pie"})]))


def test_chart_axis_range_must_be_ordered(build_spec: Build) -> None:
    spec = one_slide(
        [("chart", {"categories": ["甲"], "series": [{"name": "s", "values": [1]}], "vmin": 5, "vmax": 1})]
    )
    with pytest.raises(SpecError, match="vmin"):
        build_spec(spec)


def test_edge_to_unknown_node_names_the_page(build_spec: Build) -> None:
    graph = {"nodes": [{"id": "a", "col": 0, "row": 0, "title": "A"}], "edges": [{"from": "a", "to": "zzz"}]}
    with pytest.raises(SpecError, match=r"第 2 頁「標題」的 arch_graph 區塊.*zzz"):
        build_spec(one_slide([("arch_graph", graph)]))


def test_swimlane_step_outside_lanes(build_spec: Build) -> None:
    sw = {"lanes": [{"name": "甲"}], "steps": [{"lane": 3, "title": "越界"}]}
    with pytest.raises(SpecError, match="超出泳道範圍"):
        build_spec(one_slide([("swimlane", sw)]))


def test_overflow_is_reported(build_spec: Build) -> None:
    banners = [("banner", {"kind": "gray", "title": f"橫幅 {i}", "h": 1.2}) for i in range(6)]
    with pytest.raises(SpecError, match="超出可用範圍"):
        build_spec(one_slide(banners))


def test_h_on_block_without_own_h_param_is_honored(build_spec: Build) -> None:
    """swimlane 沒有自己的 h 欄位；規格寫 h 就是配給它的高度，不丟 TypeError。"""
    sw = {
        "lanes": [{"name": "甲"}, {"name": "乙"}],
        "steps": [{"lane": 0, "title": "一"}, {"lane": 1, "title": "二"}],
        "h": 3.0,
    }
    build_spec(one_slide([("swimlane", sw)]))


def test_missing_screenshot_stops_the_build(build_spec: Build) -> None:
    shots = {"items": [{"image": "screens/not-there.png", "title": "缺圖"}]}
    with pytest.raises(FileNotFoundError, match="not-there"):
        build_spec(one_slide([("shots", shots)]))


def test_shots_crop_and_side(build_spec: Build) -> None:
    shots = {
        "items": [{"image": "screens/sample.png", "title": "圖", "body": "說明", "crop": 0.3}],
        "side": [{"kind": "blue", "title": "怎麼看", "body": "x"}],
    }
    build_spec(one_slide([("shots", shots)]))


def test_images_resolve_relative_to_deck_dir(tmp_path: Path, theme: Theme) -> None:
    deck = tmp_path / "deck"
    (deck / "screens").mkdir(parents=True)
    (deck / "screens" / "s.png").write_bytes((TEMPLATE / "screens" / "sample.png").read_bytes())
    spec = one_slide([("shots", {"items": [{"image": "screens/s.png", "title": "圖"}]})])
    assert engine.build(spec, tmp_path / "o.pptx", deck, theme) == 2


def test_build_creates_parent_dirs(tmp_path: Path, theme: Theme) -> None:
    out = tmp_path / "a" / "b" / "o.pptx"
    engine.build(one_slide([("note", {"lines": ["x"]})]), out, TEMPLATE, theme)
    assert out.is_file()


def test_theme_defaults_to_the_brand_found_from_base_dir(repo: Path) -> None:
    """沒給 Theme 就由簡報目錄往上找 _brand.yml；找不到的目錄會明確報錯。"""
    deck = repo / "deck"
    deck.mkdir()
    assert engine.build(one_slide([("note", {"lines": ["x"]})]), repo / "o.pptx", deck) == 2
    bare = repo / "bare"
    (bare / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="找不到 _brand.yml"):
        engine.build(one_slide([("note", {"lines": ["x"]})]), bare / "o.pptx", bare)


def test_build_is_deterministic_in_content(tmp_path: Path, template_spec: dict[str, Any], theme: Theme) -> None:
    a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
    engine.build(template_spec, a, TEMPLATE, theme)
    engine.build(template_spec, b, TEMPLATE, theme)
    n = len(template_spec["slides"]) + 1
    assert [_texts(a, i) for i in range(1, n + 1)] == [_texts(b, i) for i in range(1, n + 1)]


def test_no_hardcoded_color_literals_in_engine_sources() -> None:
    """色碼只在 _brand.yml：引擎原始碼不得出現六位十六進位色碼，也不用 RGBColor(...) 直接寫值。"""
    src = Path(engine.__file__).parent
    for name in ("blocks.py", "draw.py", "engine.py", "outline.py", "lint.py", "template.py", "theme.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert not re.search(r"""["'#][0-9A-Fa-f]{6}["']""", text), f"{name} 寫死了色碼"
        assert "RGBColor(" not in text


def test_no_module_level_theme_state() -> None:
    """繪圖與區塊不靠模組層級的設定：每個公開函式都明確收 Theme（沒有 `import theme as T` 之類的全域）。"""
    src = Path(engine.__file__).parent
    for name in ("blocks.py", "draw.py", "engine.py", "template.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert "import theme as T" not in text
        assert not re.search(r"^[A-Z_]+ = T\.", text, re.MULTILINE)
