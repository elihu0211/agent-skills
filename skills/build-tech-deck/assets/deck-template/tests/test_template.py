"""範本：主題、母片與具名版面由集中參數產生；每頁建在版面的 placeholder 上，並帶無障礙資訊。"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import one_slide
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from deckstyle import design, engine, template
from deckstyle.theme import Theme

Build = Callable[..., Path]
LAYOUTS = ["Title Slide", "Title and Content", "Section Header", "Title Only", "Blank", "Closing"]


def _slides(path: Path) -> list[Any]:
    return list(Presentation(str(path)).slides)


def _theme_xml(prs: Any) -> Any:
    from lxml import etree

    return etree.fromstring(prs.slide_master.part.part_related_by(RT.THEME).blob)


A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _footer_off(theme: Theme) -> Theme:
    d = design.load()
    return Theme.build(theme.brand, dataclasses.replace(d, page=dataclasses.replace(d.page, footer=False)))


# ---- 範本本身 ----


def test_template_has_named_layouts(theme: Theme) -> None:
    prs = template.build(theme)
    assert [layout.name for layout in prs.slide_layouts] == LAYOUTS
    assert len(prs.slides) == 0
    # Pandoc／Quarto 的 reference-doc 約定要有的名稱，我們有的部分名稱一致
    assert {"Title Slide", "Title and Content", "Section Header", "Blank"} <= {la.name for la in prs.slide_layouts}


def test_template_round_trips(tmp_path: Path, theme: Theme) -> None:
    out = tmp_path / "t.pptx"
    template.build(theme).save(str(out))
    assert [la.name for la in Presentation(str(out)).slide_layouts] == LAYOUTS


def test_theme_colors_follow_the_brand(theme: Theme) -> None:
    root = _theme_xml(template.build(theme))
    brand = theme.brand.color
    got = {el.tag.split("}")[1]: el[0].get("val") for el in root.find(".//a:clrScheme", A)}
    assert got["dk1"] == brand["foreground"]
    assert got["lt1"] == brand["background"]
    assert got["accent1"] == brand["primary"]
    assert got["accent2"] == brand["success"]
    assert got["accent3"] == brand["warning"]
    assert got["accent4"] == brand["danger"]
    assert got["hlink"] == brand["link"]


def test_theme_fonts_follow_the_brand(theme: Theme) -> None:
    root = _theme_xml(template.build(theme))
    fonts = root.find(".//a:fontScheme", A)
    for group in ("majorFont", "minorFont"):
        assert fonts.find(f"a:{group}/a:ea", A).get("typeface") == theme.font
        assert fonts.find(f"a:{group}/a:latin", A).get("typeface") == theme.font


def test_theme_is_named_after_brand(theme: Theme) -> None:
    assert _theme_xml(template.build(theme)).get("name") == theme.brand.name


def test_master_geometry_follows_the_design(theme: Theme) -> None:
    prs = template.build(theme)
    title = prs.slide_master.placeholders[0]
    assert title.left == pytest.approx(theme.layout.left * 914400, abs=2)
    assert title.width == pytest.approx(theme.layout.width * 914400, abs=2)
    assert title.top == pytest.approx(theme.frame.title_y * 914400, abs=2)
    assert prs.slide_width == pytest.approx(theme.layout.slide_w * 914400, abs=2)


def test_master_draws_footer_rule_only_when_footer_is_on(theme: Theme) -> None:
    def rules(prs: Any) -> list[str]:
        return [s.name for s in prs.slide_master.shapes if s.shape_type == MSO_SHAPE_TYPE.LINE]

    assert rules(template.build(theme)) == ["頁尾細線"]
    assert rules(template.build(_footer_off(theme))) == []


def test_cover_layouts_hide_master_decoration(theme: Theme) -> None:
    prs = template.build(theme)
    shown = {la.name: la._element.get("showMasterSp") for la in prs.slide_layouts}
    assert shown["Title Slide"] == shown["Closing"] == "0"
    assert shown["Title Only"] == "1"


# ---- 每一頁建在版面上 ----


def test_every_slide_uses_a_named_layout_and_title_placeholder(template_pptx: Path) -> None:
    for slide in _slides(template_pptx):
        assert slide.slide_layout.name in LAYOUTS
        title = slide.shapes.title
        assert title is not None
        assert title.text_frame.text.strip()


def test_title_comes_first_in_reading_order(template_pptx: Path) -> None:
    for slide in _slides(template_pptx):
        first = next(iter(slide.shapes))
        assert first.is_placeholder
        assert first.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)


def test_layout_by_page_type(template_pptx: Path) -> None:
    slides = _slides(template_pptx)
    assert slides[0].slide_layout.name == "Title Slide"
    assert slides[-1].slide_layout.name == "Closing"
    assert "Section Header" in {s.slide_layout.name for s in slides}
    assert {s.slide_layout.name for s in slides[1:-1]} <= {"Title Only", "Section Header"}


def test_no_empty_placeholder_is_left_on_a_slide(template_pptx: Path) -> None:
    for slide in _slides(template_pptx):
        for ph in slide.placeholders:
            assert ph.text_frame.text.strip(), f"第 {slide.slide_id} 頁留著空的 {ph.name}"


def test_empty_ref_removes_the_label_placeholder(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["slides"] = [{"title": "沒有章節標籤", "blocks": [{"block": "note", "lines": ["x"]}]}]
    slide = _slides(build_spec(spec))[1]
    assert template.IDX_REF not in {p.placeholder_format.idx for p in slide.placeholders}


def test_footer_and_slide_number_are_real_placeholders(template_pptx: Path) -> None:
    slide = _slides(template_pptx)[2]
    kinds = {p.placeholder_format.type for p in slide.placeholders}
    assert {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER} <= kinds
    number = next(p for p in slide.placeholders if p.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER)
    fld = number._element.xpath(".//a:fld")[0]
    assert fld.get("type") == "slidenum"  # 欄位：換頁序時 PowerPoint 自動更新
    assert fld.xpath("a:t")[0].text == "3"


def test_cover_and_closing_have_no_footer(template_pptx: Path) -> None:
    slides = _slides(template_pptx)
    for slide in (slides[0], slides[-1]):
        assert PP_PLACEHOLDER.SLIDE_NUMBER not in {p.placeholder_format.type for p in slide.placeholders}


def test_footer_off_adds_no_footer_placeholders(theme: Theme, build_spec: Build) -> None:
    slide = _slides(build_spec(one_slide([("note", {"lines": ["x"]})]), _footer_off(theme)))[1]
    assert PP_PLACEHOLDER.FOOTER not in {p.placeholder_format.type for p in slide.placeholders}


def test_title_line_break_stays_in_one_title(template_pptx: Path) -> None:
    cover = _slides(template_pptx)[0]
    assert cover.shapes.title is not None
    assert len(cover.shapes.title.text_frame.paragraphs) == 1  # 換行在同一段，大綱檢視只有一個標題
    assert "\v" in cover.shapes.title.text_frame.text or "\n" in cover.shapes.title.text_frame.text


def test_footer_text_is_escaped(build_spec: Build) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["short_title"] = "A&B <簡報>"
    slide = _slides(build_spec(spec))[1]
    ftr = next(p for p in slide.placeholders if p.placeholder_format.type == PP_PLACEHOLDER.FOOTER)
    assert ftr.text_frame.text == "A&B <簡報>"


# ---- 無障礙 ----


def test_runs_carry_the_document_language(template_pptx: Path) -> None:
    for slide in _slides(template_pptx):
        for sp in slide.shapes:
            if sp.has_text_frame:
                for r in sp._element.xpath(".//a:r/a:rPr"):
                    assert r.get("lang") == "zh-TW"
    assert Presentation(str(template_pptx)).core_properties.language == "zh-TW"


def test_runs_do_not_hardcode_a_font(template_pptx: Path) -> None:
    """字型繼承主題，不在每個 run 寫死；改 _brand.yml 的字型就全份跟著變。"""
    for slide in _slides(template_pptx):
        assert not slide._element.xpath(".//a:rPr/a:latin"), "run 寫死了字型"


def test_pictures_charts_and_tables_have_alt_text(template_pptx: Path) -> None:
    found = {"picture": 0, "chart": 0, "table": 0}
    for slide in _slides(template_pptx):
        for sp in slide.shapes:
            descr = sp._element.xpath(".//p:cNvPr")[0].get("descr")
            if sp.shape_type == MSO_SHAPE_TYPE.PICTURE:
                found["picture"] += 1
            elif sp.has_chart:
                found["chart"] += 1
            elif sp.has_table:
                found["table"] += 1
            else:
                continue
            assert descr, f"{sp.name} 缺替代文字"
    assert all(found.values()), found


def test_picture_alt_text_prefers_spec_alt(build_spec: Build) -> None:
    shots = {"items": [{"image": "screens/sample.png", "title": "標題", "body": "說明", "alt": "工單清單，有五列"}]}
    slide = _slides(build_spec(one_slide([("shots", shots)])))[1]
    pic = next(s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert pic._element.xpath(".//p:cNvPr")[0].get("descr") == "工單清單，有五列"


def test_picture_alt_text_defaults_to_title_and_body(build_spec: Build) -> None:
    shots = {"items": [{"image": "screens/sample.png", "title": "標題", "body": "說明"}]}
    slide = _slides(build_spec(one_slide([("shots", shots)])))[1]
    pic = next(s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert pic._element.xpath(".//p:cNvPr")[0].get("descr") == "標題：說明"


def test_template_survives_engine_round_trip(tmp_path: Path, template_spec: dict[str, Any], theme: Theme) -> None:
    from conftest import TEMPLATE

    out = tmp_path / "x.pptx"
    engine.build(template_spec, out, TEMPLATE, theme)
    assert len(Presentation(str(out)).slides) == len(template_spec["slides"]) + 1
