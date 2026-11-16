# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2"]
# ///
"""lint_wrap.py 與範本引擎的測試：範本必須通過；各種違規必須被抓到。"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "assets" / "deck-template"))

import deck_engine  # noqa: E402
import deck_spec  # noqa: E402
import lint_wrap  # noqa: E402


def build(slides) -> str:
    out = str(Path(tempfile.mkdtemp()) / "t.pptx")
    deck_engine.build(slides, out)
    return out


def card_slide(body_line: str, title: str = "標題"):
    return [("(1) 測試", title, [("cards", {"items": [{"kind": "gray", "title": "卡", "body": [body_line]}] * 3})], "")]


def kinds(path: str) -> set[str]:
    return {i["type"] for i in lint_wrap.lint(path, 0.8)}


def test_sample_template_is_clean():
    assert lint_wrap.lint(build(deck_spec.SLIDES), 0.8) == []


def test_every_primitive_is_exercised_by_sample():
    used = {kind for slide in deck_spec.SLIDES for kind, _ in slide[2]}
    assert used == set(deck_engine.PRIMITIVES), f"範本沒涵蓋原語：{set(deck_engine.PRIMITIVES) - used}"


def test_short_card_line_passes():
    assert kinds(build(card_slide("**標籤**：十個字內說明"))) == set()


def test_long_card_line_is_wrap():
    assert "折行" in kinds(build(card_slide("**標籤**：" + "很長的說明文字" * 4)))


def test_orphan_tail_detected():
    # 3 欄卡片可用寬度 ≈ 247pt：18 個全形字 @13.5pt 約 243pt 滿行；多 3 字落到第二行
    assert "孤字" in kinds(build(card_slide("字" * 21)))


def test_title_over_26_chars_flagged():
    assert "單行過長" in kinds(build(card_slide("短", title="標" * 27)))


def test_title_26_chars_passes():
    assert kinds(build(card_slide("短", title="標" * 26))) == set()


def test_table_cell_wrap_detected():
    slides = [("(1) 測試", "表格", [("table", {"col_w": [1, 1], "rows": [["甲", "乙"], ["短", "這是一段會超出欄寬的很長很長的儲存格文字" * 2]]})], "")]
    assert "折行" in kinds(build(slides)) or "孤字" in kinds(build(slides))


def test_dash_applied_for_amber_card():
    from pptx import Presentation
    prs = Presentation(build([("(1) 測試", "標題", [("cards", {"items": [{"kind": "amber", "title": "待驗", "body": ["x"]}]})], "")]))
    dashes = [s.line.dash_style for s in prs.slides[0].shapes if s.shape_type is not None and getattr(s, "line", None) is not None and s.line.dash_style]
    assert dashes, "amber 卡片應為虛線框"


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
