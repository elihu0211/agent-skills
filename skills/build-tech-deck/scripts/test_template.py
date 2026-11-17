# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2", "pillow", "lxml"]
# ///
"""deck_template：由 tokens.toml 產生的 PPTX 範本（佈景主題、母片、版面）與引擎對它的使用。

執行：uv run test_template.py（bash test.sh 會一併跑）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

DECK = Path(__file__).resolve().parent.parent / "assets" / "deck-template"
sys.path.insert(0, str(DECK))

import deck_engine  # noqa: E402
import deck_template as D  # noqa: E402
import theme as T  # noqa: E402

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PANDOC_LAYOUTS = (
    "Title Slide",
    "Title and Content",
    "Section Header",
    "Two Content",
    "Comparison",
    "Content with Caption",
    "Blank",
)


def small_spec(**cover) -> dict:
    return {
        "title": "測試",
        "short_title": "測試簡報",
        "author": "作者",
        "tags": ["slides"],
        "cover": {"category": "分類", "title": "題名\n第二行", "subtitle": "副題", **cover},
        "slides": [
            ("01 章節", "第一頁標題", [("note", {"lines": ["結論"]})], "講稿"),
            ("02 章節", "第二頁標題", [("note", {"lines": ["結論二"]})]),
        ],
    }


class Template(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prs = D.new_presentation()

    def test_has_the_seven_layouts_quarto_and_pandoc_look_up_by_name(self):
        names = [layout.name for layout in self.prs.slide_layouts]
        for name in PANDOC_LAYOUTS:
            self.assertEqual(names.count(name), 1, name)
        self.assertIn(D.TITLE_ONLY, names)

    def test_layout_order_follows_the_declared_order(self):
        self.assertEqual([layout.name for layout in self.prs.slide_layouts], list(D.LAYOUT_ORDER))

    def test_the_engine_contract_holds(self):
        D.check_contract(self.prs)

    def test_a_missing_contract_placeholder_is_named(self):
        prs = D.new_presentation()
        layout = D.layout_named(prs, D.TITLE_ONLY)
        ref = next(p for p in layout.placeholders if p.placeholder_format.idx == D.IDX_REF)
        ref._element.getparent().remove(ref._element)
        with self.assertRaisesRegex(ValueError, "13"):
            D.check_contract(prs)

    def test_an_unknown_layout_name_lists_the_available_ones(self):
        with self.assertRaisesRegex(ValueError, "Title Only"):
            D.layout_named(self.prs, "Nope")

    def test_slide_size_comes_from_the_design_spec(self):
        self.assertAlmostEqual(self.prs.slide_width / 914400, T.LAYOUT.slide_w, places=2)
        self.assertAlmostEqual(self.prs.slide_height / 914400, T.LAYOUT.slide_h, places=2)

    def test_theme_colors_and_fonts_come_from_the_tokens(self):
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT
        from lxml import etree

        root = etree.fromstring(self.prs.slide_master.part.part_related_by(RT.THEME).blob)
        clr = root.find(f"{A}themeElements/{A}clrScheme")
        got = {el.tag.removeprefix(A): el[0].get("val") for el in clr}
        self.assertEqual(got, D._theme_colors())
        for group in ("majorFont", "minorFont"):
            font = root.find(f"{A}themeElements/{A}fontScheme/{A}{group}")
            self.assertEqual(font.find(f"{A}latin").get("typeface"), T.FONT)
            self.assertEqual(font.find(f"{A}ea").get("typeface"), T.FONT)

    def test_master_background_is_the_theme_background_and_not_a_picture(self):
        bg = self.prs.slide_master._element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}bg")
        self.assertIsNotNone(bg.find(f".//{A}schemeClr"))

    def test_roundtrip_through_a_file_keeps_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.pptx"
            self.prs.save(str(path))
            D.open_template(path)  # 不丟例外


class EngineUsesTheTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deck = deck_engine.render(small_spec(), DECK)
        cls.slides = list(cls.deck.prs.slides)

    def test_slides_use_the_named_layouts(self):
        self.assertEqual(self.slides[0].slide_layout.name, D.TITLE_SLIDE)
        self.assertEqual(self.slides[1].slide_layout.name, D.TITLE_ONLY)

    def test_titles_are_real_title_placeholders(self):
        self.assertEqual(self.slides[1].shapes.title.text_frame.text, "第一頁標題")
        self.assertEqual(self.slides[2].shapes.title.text_frame.text, "第二頁標題")

    def test_cover_fields_land_in_their_placeholders(self):
        s = self.slides[0]
        self.assertEqual(s.placeholders[D.IDX_REF].text_frame.text, "分類")
        self.assertIn("題名", s.shapes.title.text_frame.text)
        self.assertEqual(s.placeholders[D.IDX_BODY].text_frame.text, "副題")
        self.assertEqual(s.placeholders[D.IDX_META].text_frame.text, "作者")

    def test_an_empty_author_removes_its_placeholder(self):
        spec = small_spec()
        spec["author"] = ""
        s = list(deck_engine.render(spec, DECK).prs.slides)[0]
        self.assertNotIn(D.IDX_META, [p.placeholder_format.idx for p in s.placeholders])

    def test_footer_text_and_slide_number_are_placeholders_with_a_field(self):
        s = self.slides[1]
        by_idx = {p.placeholder_format.idx: p for p in s.placeholders}
        self.assertEqual(by_idx[D.IDX_FOOTER].text_frame.text, "測試簡報")
        self.assertEqual(len(by_idx[D.IDX_NUMBER]._element.findall(f".//{A}fld")), 1)
        self.assertEqual(by_idx[D.IDX_NUMBER]._element.find(f".//{A}fld").get("type"), "slidenum")

    def test_the_cover_has_no_footer(self):
        idxs = [p.placeholder_format.idx for p in self.slides[0].placeholders]
        self.assertNotIn(D.IDX_FOOTER, idxs)
        self.assertNotIn(D.IDX_NUMBER, idxs)

    def test_shape_ids_are_unique_on_every_slide(self):
        for n, s in enumerate(self.slides, 1):
            ids = [sh.shape_id for sh in s.shapes]
            self.assertEqual(len(ids), len(set(ids)), f"第 {n} 頁")

    def test_footer_is_last_in_reading_order(self):
        names = [sh.name for sh in self.slides[1].shapes]
        self.assertEqual(names[0].split()[0], "Title")
        self.assertIn("Slide Number", names[-1])

    def test_slides_carry_no_hardcoded_geometry_for_placeholders(self):
        # 位置與字型都沿用版面：換範本時投影片才會跟著變
        for sh in self.slides[1].placeholders:
            self.assertIsNone(sh._element.spPr.find(f"{A}xfrm"), sh.name)

    def test_notes_survive(self):
        self.assertEqual(self.slides[1].notes_slide.notes_text_frame.text, "講稿")

    def test_document_properties(self):
        props = self.deck.prs.core_properties
        self.assertEqual(props.title, "測試")
        self.assertEqual(props.author, "作者")
        self.assertEqual(props.language, "zh-TW")
        self.assertEqual(props.keywords, "slides")

    def test_runs_do_not_hardcode_a_font(self):
        # 字型由佈景主題決定，換主題字型整份跟著變
        for s in self.slides:
            for el in s._element.iter(f"{A}rPr"):
                self.assertIsNone(el.find(f"{A}latin"))

    def test_a_custom_template_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.pptx"
            prs = D.new_presentation()
            prs.core_properties.subject = "自訂範本"
            prs.save(str(path))
            deck = deck_engine.render(small_spec(), DECK, template=path)
            self.assertEqual(deck.prs.core_properties.subject, "自訂範本")

    def test_build_deck_emit_template_roundtrip(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            tpl, out = Path(tmp) / "tpl.pptx", Path(tmp) / "out.pptx"
            build = DECK / "build_deck.py"
            self.assertEqual(subprocess.run([sys.executable, str(build), "--emit-template", str(tpl)], capture_output=True).returncode, 0)
            D.open_template(tpl)  # 匯出的範本符合契約
            self.assertEqual(subprocess.run([sys.executable, str(build), str(out), "--template", str(tpl)], capture_output=True).returncode, 0)
            self.assertTrue(out.is_file())

    def test_a_template_without_the_contract_is_rejected(self):
        from pptx import Presentation

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.pptx"
            Presentation().save(str(path))  # python-pptx 內建範本：沒有 Title Only 的 idx 13
            with self.assertRaises(ValueError):
                deck_engine.render(small_spec(), DECK, template=path)


if __name__ == "__main__":
    unittest.main()
