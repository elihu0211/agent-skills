"""品牌：讀 Quarto 官方的 _brand.yml，簡報的顏色與字型只從這裡來。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import BRAND_FILE, write

from deckstyle import brand, yamlio


def _data() -> dict[str, Any]:
    return yamlio.load(BRAND_FILE)


def test_project_brand_is_valid() -> None:
    b = brand.load(BRAND_FILE)
    assert b.name
    assert b.font
    assert len(b.hex("blue")) == 6
    assert all(len(v) == 6 for v in b.color.values())


def test_every_required_name_is_present_in_the_project_brand() -> None:
    b = brand.load(BRAND_FILE)
    assert set(brand.REQUIRED_PALETTE) <= set(b.palette)
    assert set(brand.REQUIRED_COLORS) <= set(b.color)


def test_semantic_color_may_be_a_literal_hex() -> None:
    data = _data()
    data["color"]["primary"] = "#112233"
    assert brand.parse(data).color["primary"] == "112233"


def test_font_base_may_be_a_mapping() -> None:
    data = _data()
    data["typography"]["base"] = {"family": "Noto Sans TC", "size": "16px"}
    assert brand.parse(data).font == "Noto Sans TC"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.pop("color"), "color.palette"),
        (lambda d: d["color"]["palette"].pop("blue"), "缺引擎必要的色票：blue"),
        (lambda d: d["color"]["palette"].update(blue="2563EB"), "#RRGGBB"),
        (lambda d: d["color"].pop("primary"), "缺語義色 primary"),
        (lambda d: d["color"].update(primary="no-such-name"), "#RRGGBB"),
        (lambda d: d.pop("typography"), "typography.base"),
    ],
)
def test_invalid_brand_is_rejected(edit: Any, message: str) -> None:
    data = _data()
    edit(data)
    with pytest.raises(brand.BrandError, match=message):
        brand.parse(data)


def test_find_walks_up_to_the_project_root(repo: Path) -> None:
    deep = repo / "a" / "b"
    deep.mkdir(parents=True)
    assert brand.find(deep) == repo / "_brand.yml"


def test_nearest_brand_wins(repo: Path) -> None:
    near = write(repo / "course" / "_brand.yml", (repo / "_brand.yml").read_text(encoding="utf-8"))
    assert brand.find(repo / "course" / "deck") == near


def test_brand_directory_form_is_found(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    path = write(tmp_path / "_brand" / "_brand.yml", "x: 1\n")
    assert brand.find(tmp_path) == path


def test_search_stops_at_the_project_root(tmp_path: Path) -> None:
    """專案根（含 .git）以上的 _brand.yml 不該被誤讀。"""
    write(tmp_path / "_brand.yml", "x: 1\n")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    assert brand.find(project) is None


def test_discover_explains_where_to_put_the_file(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(brand.BrandError, match="找不到 _brand.yml"):
        brand.discover(tmp_path)


def test_load_error_names_the_file(tmp_path: Path) -> None:
    path = write(tmp_path / "_brand.yml", "color: {}\n")
    with pytest.raises(brand.BrandError, match="_brand.yml"):
        brand.load(path)
