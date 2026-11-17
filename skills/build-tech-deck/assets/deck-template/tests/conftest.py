"""測試共用：真實專案的品牌與範本、單頁規格產生器與建置輔助。

測試讀專案根的 `_brand.yml`（品牌的唯一真值）；需要隔離的情形（分層設定、找不到品牌…）用 `repo` 夾具建假專案。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from deckstyle import brand, cli, config, engine
from deckstyle.theme import Theme

TEMPLATE = Path(engine.__file__).parent / "template"
# 品牌與作者設定檔：從範本目錄往上找（範本自帶一份示例，專案把它們放到專案根後也找得到）
BRAND_FILE = brand.find(TEMPLATE)
QUARTO_FILE = next(p for p in config.layer_files(TEMPLATE) if p.name == "_quarto.yml")
assert BRAND_FILE is not None


@pytest.fixture(scope="session")
def theme() -> Theme:
    """真實品牌（專案根的 _brand.yml）加套件的 design.yml。"""
    return Theme.load(TEMPLATE)


@pytest.fixture(scope="session")
def template_spec() -> dict[str, Any]:
    """範本 deck.yml 讀成內部形狀；作者固定，不依賴專案根的 _quarto.yml。"""
    spec, _ = cli.load_raw(TEMPLATE)
    return {**spec, "author": {"name": "範例作者", "affiliation": "範例單位"}, "lang": config.DEFAULT_LANG}


@pytest.fixture(scope="session")
def template_pptx(tmp_path_factory: pytest.TempPathFactory, template_spec: dict[str, Any], theme: Theme) -> Path:
    out = tmp_path_factory.mktemp("deck") / "t.pptx"
    engine.build(template_spec, out, TEMPLATE, theme)
    return out


def one_slide(blocks: list[tuple[str, dict[str, Any]]], title: str = "標題", notes: str = "") -> dict[str, Any]:
    """只有一頁內容的最小規格（內部形狀：snake_case 鍵）。"""
    return {
        "title": "題名",
        "subtitle": "副題",
        "category": "分類",
        "short_title": "測試",
        "author": "作者",
        "slides": [
            {"ref": "01 測試", "title": title, "blocks": [{"block": n, **kw} for n, kw in blocks], "notes": notes}
        ],
    }


@pytest.fixture
def build_spec(tmp_path: Path, theme: Theme) -> Callable[..., Path]:
    """把規格建成 pptx 並回傳路徑（圖片相對於範本目錄；可帶別的 Theme）。"""

    def _build(spec: dict[str, Any], t: Theme | None = None) -> Path:
        out = tmp_path / "t.pptx"
        engine.build(spec, out, TEMPLATE, t or theme)
        return out

    return _build


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """假專案：`.git` 標出專案根，內含真實的 `_brand.yml` 副本。"""
    (tmp_path / ".git").mkdir()
    (tmp_path / "_brand.yml").write_text(BRAND_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
