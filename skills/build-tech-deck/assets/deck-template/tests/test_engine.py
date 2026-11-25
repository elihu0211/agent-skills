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
from pptx.enum.shapes import MSO_SHAPE_TYPE
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


def _figure_slide(build_spec: Build, **shots: Any) -> Any:
    spec = {"items": [{"image": "screens/sample.png", "title": "圖", "body": "說明"}], "figure": True, **shots}
    slide = Presentation(str(build_spec(one_slide([("shots", spec)])))).slides[1]
    pic = next(s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    return slide, pic


def _near(a: float, b: float) -> bool:
    return abs(a - b) < Inches(0.01)


def test_shots_figure_fills_the_height_and_side_takes_the_rest(build_spec: Build, theme: Theme) -> None:
    """figure：圖撐滿區塊高度；卡片欄接在圖右緣、延伸到內容區右緣，圖說在卡片欄底部、與圖底對齊。"""
    lay = theme.layout
    side = [{"kind": "blue", "title": "怎麼看", "body": "x"}]
    slide, pic = _figure_slide(build_spec, side=side, side_w=2.8)  # 範例圖 5:3，卡片欄 2.8 吋時圖受高度限制
    assert _near(pic.top, Inches(lay.top)) and _near(pic.height, Inches(lay.bottom - lay.top))
    sx = pic.left + pic.width + Inches(lay.side_gap)
    caption = next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text.startswith("圖"))
    assert _near(caption.left, sx) and _near(caption.left + caption.width, Inches(lay.right))
    assert _near(caption.top + caption.height, pic.top + pic.height)
    cards = [s for s in slide.shapes if _near(s.left, sx) and s.shape_id != caption.shape_id]
    assert cards and all(s.top + s.height < caption.top for s in cards)


def test_shots_figure_keeps_the_minimum_side_width(build_spec: Build, theme: Theme) -> None:
    """圖太寬時縮圖，卡片欄至少留 side-w（預設 layout.side-w）。"""
    lay = theme.layout
    _, pic = _figure_slide(build_spec, side=[{"kind": "blue", "title": "怎麼看", "body": "x"}])
    assert _near(pic.width, Inches(lay.width - lay.side_gap - lay.side_w))
    assert pic.height < Inches(lay.bottom - lay.top)


def test_shots_figure_without_side_is_centered(build_spec: Build, theme: Theme) -> None:
    lay = theme.layout
    _, pic = _figure_slide(build_spec)
    assert _near(pic.left + pic.width / 2, Inches(lay.left + lay.width / 2))


def test_shots_figure_takes_one_image(build_spec: Build) -> None:
    item = {"image": "screens/sample.png", "title": "圖"}
    with pytest.raises(SpecError, match="figure"):
        build_spec(one_slide([("shots", {"items": [item, item], "figure": True})]))


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


# ---- 依內容估算的高度：表格列高、參考文獻 ----


def _shape(path: Path, slide_no: int, pred: Callable[[Any], bool]) -> Any:
    slide = list(Presentation(str(path)).slides)[slide_no - 1]
    return next(sh for sh in slide.shapes if pred(sh))


def test_table_rows_grow_to_fit_multi_line_cells(build_spec: Build, theme: Theme) -> None:
    """兩三行的儲存格撐高該列、單行的列維持等高；表格總高等於列高加總，單一區塊依實際高度置中。"""
    rows = [["欄名", "說明"]] + [["一行", "一行"]] * 3 + [["三行", "第一行\n第二行\n第三行"]] + [["一行", "一行"]] * 3
    out = build_spec(one_slide([("table", {"rows": rows, "col_w": [1, 3]})]))
    gf = _shape(out, 2, lambda sh: sh.has_table)
    hs = [r.height for r in gf.table.rows]
    assert len({hs[i] for i in (1, 2, 3, 5, 6, 7)}) == 1 and hs[1] < hs[4]
    assert abs(gf.height - sum(hs)) <= 4  # EMU 進位誤差
    lay = theme.layout
    centered = Inches(lay.top + (lay.bottom - lay.top - gf.height / 914400) / 2)
    assert abs(gf.top - centered) < Inches(0.01)


def test_header_row_stays_compact(build_spec: Build) -> None:
    """首列只留字高加少許空白，不跟內容列一起被拉高；省下的高度給內容列。"""
    rows = [["欄名", "說明"]] + [["一行", "一行"]] * 4
    out = build_spec(one_slide([("table", {"rows": rows, "col_w": [1, 3]})]))
    hs = [r.height for r in _shape(out, 2, lambda sh: sh.has_table).table.rows]
    assert hs[0] < Inches(0.5) < hs[1]
    assert len(set(hs[1:])) == 1


def test_header_only_table_renders(build_spec: Build) -> None:
    build_spec(one_slide([("table", {"rows": [["只有欄名"]], "col_w": [1]})]))


def test_table_rows_shrink_to_stay_within_h(build_spec: Build) -> None:
    rows = [["欄"]] + [[f"第 {i} 列"] for i in range(6)] + [["甲\n乙\n丙"]]
    out = build_spec(one_slide([("table", {"rows": rows, "col_w": [1], "h": 4.0})]))
    gf = _shape(out, 2, lambda sh: sh.has_table)
    hs = [r.height for r in gf.table.rows]
    assert sum(hs) <= Inches(4.0) + 8 and hs[1] < hs[-1]


def test_table_too_tall_for_the_page_is_reported(build_spec: Build) -> None:
    rows = [["欄"]] + [["一\n二\n三\n四"] for _ in range(8)]
    with pytest.raises(SpecError, match="超出可用範圍"):
        build_spec(one_slide([("table", {"rows": rows, "col_w": [1]})]))


def test_node_en_is_a_smaller_line_under_the_title(build_spec: Build) -> None:
    node = {"id": "g", "col": 0, "row": 0, "title": "生產系譜", "en": "Production Genealogy", "sub": "封裝紀錄"}
    out = build_spec(one_slide([("arch_graph", {"nodes": [node], "cols": 1, "rows": 1})]))
    card = _shape(out, 2, lambda sh: sh.has_text_frame and "Production Genealogy" in sh.text_frame.text)
    title, en, sub = card.text_frame.paragraphs
    assert (title.text, en.text, sub.text) == ("生產系譜", "Production Genealogy", "封裝紀錄")
    assert en.runs[0].font.size < title.runs[0].font.size
    assert not en.runs[0].font.bold


def _badged_node(**kw: Any) -> dict[str, Any]:
    """四欄三列、有欄標題、區塊高 4.35 吋的圖裡放一個帶徽章的節點：卡片高約 1.08 吋，是最緊的常見尺寸。"""
    return {"id": "n", "col": 0, "row": 0, "title": "現場系統與閘道", "badge": "第二期", "kind": "blue", **kw}


def _graph(node: dict[str, Any]) -> dict[str, Any]:
    return {"nodes": [node], "cols": 4, "rows": 3, "h": 4.35, "col_headers": ["甲", "乙", "丙", "丁"]}


def _card_of(out: Path, node: dict[str, Any]) -> Any:
    return _shape(out, 2, lambda sh: sh.has_text_frame and sh.text_frame.text.startswith(node["title"]))


def test_badge_overlapping_the_title_is_reported(build_spec: Build) -> None:
    """標題、英文名稱與兩行說明共四行，卡片放不下就停在建置時，不讓徽章蓋住標題。"""
    node = _badged_node(en="Field Systems & Gateway", sub="具 REST 的系統直連\n其餘經 nDAS 6000")
    with pytest.raises(SpecError, match=r"「現場系統與閘道」.*徽章.*英文名稱"):
        build_spec(one_slide([("arch_graph", _graph(node))]))


def test_badge_leaves_a_card_with_room_untouched(build_spec: Build) -> None:
    """文字離上緣夠遠，徽章不影響排版：上邊界維持原本的內縮。"""
    node = _badged_node(sub="具 REST 的系統直連\n其餘經 nDAS 6000")
    out = build_spec(one_slide([("arch_graph", _graph(node))]))
    tf = _card_of(out, node).text_frame
    assert tf.margin_top == tf.margin_bottom


def test_badge_pushes_tight_text_below_itself(build_spec: Build) -> None:
    """文字放得下、但置中時會碰到徽章：整塊往下推到剛好離開徽章，下方仍留在卡片內。"""
    node = _badged_node(sub="具 REST 的系統直連\n其餘經 nDAS 6000", bfs=13)
    out = build_spec(one_slide([("arch_graph", _graph(node))]))
    tf = _card_of(out, node).text_frame
    assert tf.margin_top > tf.margin_bottom


def test_numbered_flow_step_reports_text_under_its_badge(build_spec: Build) -> None:
    """流程圖的圓形序號壓在方塊左上角，方塊太矮放不下文字時一樣停在建置時。"""
    items = [{"title": "一二三四五六", "body": ["第一行", "第二行", "第三行", "第四行"], "kind": "blue"}]
    with pytest.raises(SpecError, match="徽章"):
        build_spec(one_slide([("flow", {"items": items, "numbered": True, "h": 1.0})]))


_REFS = [  # 示例書目：夠長，在版心寬裡會折成兩行
    (
        "Example, A., & Sample, B. (2026). A deliberately long reference title that runs past the right margin "
        "so that the hanging indent shows on the second line. Example Press."
    ),
    (
        "Noy, N. F., & McGuinness, D. L. (2001). Ontology development 101: A guide to creating your first "
        "ontology (Technical Report KSL-01-05). Stanford Knowledge Systems Laboratory."
    ),
]


def test_references_hang_and_wrap_without_lint_violations(build_spec: Build) -> None:
    from deckstyle.lint import lint_wrap
    from deckstyle.measure import REFLOW

    out = build_spec(one_slide([("references", {"title": "APA 第 7 版", "items": _REFS})]))
    box = _shape(out, 2, lambda sh: sh.name == REFLOW)
    head, *entries = box.text_frame.paragraphs
    assert head.text == "APA 第 7 版" and [p.text for p in entries] == _REFS
    for p in entries:
        ppr = p._p.pPr
        assert int(ppr.get("marL")) == -int(ppr.get("indent")) > 0  # 懸掛縮排：續行內縮、首行齊左
    assert box.text_frame.word_wrap
    assert lint_wrap(out) == []


def test_references_height_grows_with_wrapped_lines(theme: Theme) -> None:
    from deckstyle.blocks import planned_height

    one = planned_height(theme, "references", {"items": ["短書目。"]}, 4.0)
    two = planned_height(theme, "references", {"items": [_REFS[0] * 2]}, 4.0)
    assert 0 < one < two


def test_too_many_references_are_reported(build_spec: Build) -> None:
    with pytest.raises(SpecError, match="超出可用範圍"):
        build_spec(one_slide([("references", {"items": _REFS * 8})]))


def test_empty_references_are_reported(build_spec: Build) -> None:
    with pytest.raises(SpecError, match="沒有書目"):
        build_spec(one_slide([("references", {"items": []})]))
