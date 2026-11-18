"""設計參數 design.yml 的載入與驗證：預設值合格；各種不合規格都被擋下並指出位置。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deckstyle import design, yamlio


def _data() -> dict[str, Any]:
    return yamlio.load(design.DESIGN_PATH)


def test_default_design_loads() -> None:
    d = design.load()
    assert d.layout.width == pytest.approx(d.layout.right - d.layout.left)
    assert d.page.footer is True


def test_kebab_keys_become_snake_fields() -> None:
    d = design.load()
    assert d.layout.slide_w == 13.333
    assert d.geometry.radius_pt == 3
    assert d.frame.accent_weight_pt == 3


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.update(schema=2), "schema"),
        (lambda d: d.update(extra={}), "未知的區段"),
        (lambda d: d.pop("layout"), "layout"),
        (lambda d: d["layout"].update(left=13.0), "left < right"),
        (lambda d: d["layout"].update(bottom=7.2), "footer-rule"),
        (lambda d: d["layout"].update(**{"side-w": 11.5}), "side-w"),
        (lambda d: d["layout"].pop("gap"), "缺 gap"),
        (lambda d: d["type"].update(extra=1), "未知 extra"),
        (lambda d: d["type"].update(**{"slide-title": -1}), "正數"),
        (lambda d: d["page"].update(transition="spin"), "transition"),
        (lambda d: d["page"].update(footer="yes"), "true 或 false"),
        (lambda d: d["lint"].update(safety=1.5), "safety"),
        (lambda d: d["frame"].pop("ref-y"), "缺 ref_y"),
        (lambda d: d["frame"].pop("header-rule-y"), "缺 header_rule_y"),
        (lambda d: d["frame"].update(**{"header-rule-y": 1.2}), "header-rule-y"),
        (lambda d: d["frame"].update(**{"header-rule-y": 1.8}), "header-rule-y"),
    ],
)
def test_invalid_design_is_rejected(edit: Any, message: str) -> None:
    data = _data()
    edit(data)
    with pytest.raises(design.DesignError, match=message):
        design.parse(data)


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(design.DesignError, match="對應表"):
        design.parse([])


def test_load_accepts_another_file(tmp_path: Path) -> None:
    text = design.DESIGN_PATH.read_text(encoding="utf-8").replace("gap: 0.18", "gap: 0.25")
    path = tmp_path / "design.yml"
    path.write_text(text, encoding="utf-8")
    assert design.load(path).layout.gap == 0.25
