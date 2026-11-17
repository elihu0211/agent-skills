# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2", "pillow"]
# ///
"""範本引擎、lint_wrap.py 與 lint_names.py 的測試：範本必須通過；各種違規必須被抓到。"""
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE.parent / "assets" / "deck-template"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TEMPLATE))

import blocks  # noqa: E402
import deck_engine  # noqa: E402
import deck_spec  # noqa: E402
import lint_names  # noqa: E402
import lint_wrap  # noqa: E402
import theme  # noqa: E402


def build_spec(spec) -> str:
    out = str(Path(tempfile.mkdtemp()) / "t.pptx")
    deck_engine.render(spec, TEMPLATE).save(out)
    return out


def one_slide(blocks, title="標題", notes=""):
    return {
        "short_title": "測試", "author": "作者",
        "cover": {"category": "分類", "title": "題名", "subtitle": "副題"},
        "slides": [("01 測試", title, blocks, notes)],
    }


def card_slide(body_line: str, title: str = "標題", n: int = 3) -> str:
    items = [{"kind": "gray", "title": "卡", "body": [body_line]}] * n
    return build_spec(one_slide([("cards", {"items": items})], title))


def kinds(path: str) -> set[str]:
    return {i["type"] for i in lint_wrap.lint(path, 0.8)}


# ---- 範本與引擎 ----

def cover_texts(path: str) -> list[str]:
    from pptx import Presentation

    return [sh.text_frame.text for sh in Presentation(path).slides[0].shapes if sh.has_text_frame]


def cover_spec(**author) -> dict:
    spec = one_slide([("note", {"lines": ["結論"]})])
    spec.pop("author")
    spec.update(author)
    return spec


def test_cover_author_comes_from_defaults_when_spec_is_silent():
    assert "範例單位" in cover_texts(build_spec(cover_spec()))


def test_spec_author_overrides_the_default():
    texts = cover_texts(build_spec(cover_spec(author="某某單位")))
    assert "某某單位" in texts and "範例單位" not in texts


def test_empty_author_leaves_the_cover_line_out():
    texts = cover_texts(build_spec(cover_spec(author="")))
    assert "範例單位" not in texts and "" not in texts


def test_non_string_author_stops_the_build():
    try:
        build_spec(cover_spec(author=["甲", "乙"]))
    except ValueError as e:
        assert "字串" in str(e)
    else:
        raise AssertionError("非字串的作者欄應該停下")


def test_sample_template_is_clean():
    path = build_spec(deck_spec.SPEC)
    assert lint_wrap.lint(path, 0.8) == []
    assert lint_names.lint(str(path), [], set()) == []


def test_every_block_is_exercised_by_sample():
    used = {kind for slide in deck_spec.SPEC["slides"] for kind, _ in slide[2]}
    assert used == set(blocks.BLOCKS), f"範本沒涵蓋區塊：{set(blocks.BLOCKS) - used}"


def test_every_card_kind_is_defined():
    for kind in ("gray", "white", "blue", "blue_fill", "green", "green_fill", "amber", "amber_fill", "red", "red_fill", "dark", "solid_dark"):
        assert kind in theme.CARDS, kind


def test_theme_has_no_hardcoded_colors():
    src = (TEMPLATE / "theme.py").read_text(encoding="utf-8")
    assert re.findall(r"""["']#?[0-9A-Fa-f]{6}["']""", src) == [], "色票只在 tokens.toml 定義"


def test_roles_point_at_a_palette():
    for name, role in theme.TOKENS.role.items():
        assert role.palette in theme.TOKENS.palette, name


def test_cards_are_rounded():
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
    from pptx import Presentation
    prs = Presentation(card_slide("短"))
    rounded = [s for s in prs.slides[1].shapes
               if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and s.auto_shape_type == MSO_SHAPE.ROUNDED_RECTANGLE]
    assert len(rounded) >= 3, "三張卡片都應為圓角矩形"
    assert all(0 < s.adjustments[0] <= 0.5 for s in rounded)


def test_missing_image_stops_the_build():
    spec = one_slide([("shots", {"items": [{"image": "screens/not-there.png", "title": "圖", "body": "說明"}]})])
    try:
        build_spec(spec)
    except FileNotFoundError:
        return
    raise AssertionError("缺圖應在建置時停下")


def test_table_semantic_cell_keeps_color():
    from pptx import Presentation
    spec = one_slide([("table", {"col_w": [1, 1], "rows": [["甲", "乙"], ["短", ("好", "green")]]})])
    prs = Presentation(build_spec(spec))
    cell = next(s for s in prs.slides[1].shapes if s.has_table).table.cell(1, 1)
    run = cell.text_frame.paragraphs[0].runs[0]
    assert run.font.color.rgb == theme.TONES["green"].text and run.font.bold


# ---- lint_wrap ----

def test_short_card_line_passes():
    assert kinds(card_slide("**標籤**：十個字內說明")) == set()


def test_long_card_line_is_wrap():
    assert "折行" in kinds(card_slide("**標籤**：" + "很長的說明文字" * 4))


def test_orphan_tail_detected():
    # 3 欄卡片內文寬約 250pt；全形 18 字 @14.5pt 略超過一行，落到第二行的只有 1 字
    assert "孤字" in kinds(card_slide("字" * 18))


def test_title_over_limit_flagged_and_at_limit_passes():
    assert "折行" in kinds(card_slide("短", title="標" * 27))
    assert kinds(card_slide("短", title="標" * 24)) == set()


def test_table_cell_wrap_detected():
    spec = one_slide([("table", {"col_w": [1, 1], "rows": [["甲", "乙"], ["短", "這是一段會超出欄寬的很長很長的儲存格文字" * 2]]})])
    assert kinds(build_spec(spec)) & {"折行", "孤字"}


# ---- lint_names ----

def names(text: str, deny=(), allow=()) -> set[str]:
    return {label for label, _ in lint_names.scan(text, list(deny), set(allow))}


def test_names_flags_identifiers_files_and_paths():
    assert "識別字（snake_case）" in names("調大 shared_buffers 參數")
    assert "檔案名" in names("見 deploy.yml 與 check.py")
    assert "路徑或端點" in names("打 /v2/items 與 /ui")


def test_names_passes_plain_text_and_ordinary_slashes():
    for text in ("平台服務與營運後台", "I/O 與 24/7 的 2026/11/17", "PostgreSQL 與 Kubernetes", "ISO/IEC 17788", "和/或"):
        assert names(text) == set(), text


def test_names_deny_and_allow():
    assert "倉庫或服務代號" in names("後端 shop-api 負責", deny=["shop-api"])
    assert names("後端 shop-api 負責", deny=["shop-api"], allow=["shop-api"]) == set()
    assert names("shop-apis 與 myshop-api", deny=["shop-api"]) == set()  # 字界比對


def test_names_scans_notes_and_tables():
    spec = one_slide([("table", {"col_w": [1, 1], "rows": [["a", "b"], ["x", "見 run_job"]]})], notes="講稿含 /health")
    issues = lint_names.lint(build_spec(spec), [], set())
    assert {i["where"] for i in issues} == {"表格", "講稿備註"}
    assert lint_names.lint(build_spec(spec), [], set(), notes=False)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {exc!r}")
    sys.exit(1 if failed else 0)
