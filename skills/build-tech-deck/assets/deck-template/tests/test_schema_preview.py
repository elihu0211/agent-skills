"""JSON Schema、範本輸出、預覽與監看。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import TEMPLATE, write
from PIL import Image
from pptx import Presentation

from deckstyle import cli, preview, schema, spec

# ---- JSON Schema ----


def _kebab(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k).replace("_", "-"): _kebab(x) for k, x in v.items()}
    return [_kebab(x) for x in v] if isinstance(v, list) else v


def _deck_data(template_spec: dict[str, Any]) -> dict[str, Any]:
    """範本讀成使用者看到的 deck.yml 形狀（kebab-case、不含分層才有的作者與語言）。"""
    data = _kebab(template_spec)
    data.pop("author", None)
    data.pop("lang", None)
    return data


def test_schema_has_every_block_and_page_type() -> None:
    s = schema.spec_schema()
    blocks = {b["properties"]["block"]["const"] for b in s["$defs"]["block"]["oneOf"]}
    assert blocks == {spec.kebab(n) for n in spec.BLOCK_SCHEMA}
    pages = {p["properties"]["type"]["const"] for p in s["properties"]["slides"]["items"]["oneOf"]}
    assert pages == set(spec.PAGE_TYPES)


def test_schema_uses_kebab_case_keys() -> None:
    s = schema.spec_schema()
    assert "short-title" in s["properties"]
    assert "short_title" not in s["properties"]
    table = next(b for b in s["$defs"]["block"]["oneOf"] if b["properties"]["block"]["const"] == "table")
    assert "col-w" in table["properties"]


def test_schema_enums_follow_spec_constants() -> None:
    s = schema.spec_schema()
    cards = next(b for b in s["$defs"]["block"]["oneOf"] if b["properties"]["block"]["const"] == "cards")
    assert cards["properties"]["items"]["items"]["properties"]["kind"]["enum"] == list(spec.KINDS)
    graph = next(b for b in s["$defs"]["block"]["oneOf"] if b["properties"]["block"]["const"] == "arch-graph")
    assert graph["properties"]["edges"]["items"]["properties"]["kind"]["enum"] == list(spec.EDGE_KINDS)


def test_schema_is_json_serializable() -> None:
    json.dumps(schema.schemas(), ensure_ascii=False)


def test_template_validates_against_schema(template_spec: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    s = schema.spec_schema()
    jsonschema.Draft202012Validator.check_schema(s)
    assert list(jsonschema.Draft202012Validator(s).iter_errors(_deck_data(template_spec))) == []


def test_template_yaml_file_validates_as_written() -> None:
    """範本 deck.yml 本身（不經內部轉換）符合 schema。"""
    jsonschema = pytest.importorskip("jsonschema")
    data = yaml.safe_load((TEMPLATE / "deck.yml").read_text(encoding="utf-8"))
    assert list(jsonschema.Draft202012Validator(schema.spec_schema()).iter_errors(data)) == []


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["slides"][0]["blocks"][0].update(block="nope"),
        lambda d: d["slides"][0]["blocks"][0].update(extra=1),
        lambda d: d["slides"][0].pop("title"),
        lambda d: d.pop("title"),
        lambda d: d.update(bogus=1),
    ],
)
def test_schema_rejects_bad_data(edit: Any, template_spec: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    data = _deck_data(template_spec)
    edit(data)
    assert list(jsonschema.Draft202012Validator(schema.spec_schema()).iter_errors(data))


def test_metadata_schema_accepts_the_repo_quarto_file() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from conftest import QUARTO_FILE

    data = yaml.safe_load((QUARTO_FILE).read_text(encoding="utf-8"))
    assert list(jsonschema.Draft202012Validator(schema.metadata_schema()).iter_errors(data)) == []


def test_schema_cli(tmp_path: Path) -> None:
    out = tmp_path / "s.json"
    assert cli.main(["schema", "spec", "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["title"].startswith("deckstyle")


# ---- 範本輸出 ----


def test_template_cli_writes_empty_branded_deck(tmp_path: Path) -> None:
    out = tmp_path / "brand.pptx"
    assert cli.main(["template", "-o", str(out), "--brand-from", str(TEMPLATE)]) == 0
    prs = Presentation(str(out))
    assert len(prs.slides) == 0
    assert len(prs.slide_layouts) == 6


# ---- 預覽與監看 ----


def _touch(path: Path) -> Path:
    path.write_text("", encoding="utf-8")
    return path


def test_contact_sheets_tile_pages(tmp_path: Path) -> None:
    pages = []
    for i in range(7):
        p = tmp_path / f"slide-{i + 1:02d}.png"
        Image.new("RGB", (96, 54), (i * 30, 100, 100)).save(p)
        pages.append(p)
    sheets = preview.contact_sheets(pages, tmp_path, per_sheet=6, cols=2, gap=10)
    assert [s.name for s in sheets] == ["sheet-1.png", "sheet-2.png"]
    assert Image.open(sheets[0]).size == (2 * 96 + 30, 3 * 54 + 40)
    assert Image.open(sheets[1]).size == (2 * 96 + 30, 1 * 54 + 20)


def test_contact_sheets_remove_stale_sheets(tmp_path: Path) -> None:
    (tmp_path / "sheet-9.png").write_bytes(b"old")
    p = tmp_path / "slide-01.png"
    Image.new("RGB", (10, 10)).save(p)
    preview.contact_sheets([p], tmp_path)
    assert not (tmp_path / "sheet-9.png").exists()


def test_render_pages_needs_pdftoppm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(preview.PreviewError, match="poppler"):
        preview.render_pages(tmp_path / "x.pdf", tmp_path)


def test_snapshot_ignores_missing_files(tmp_path: Path) -> None:
    f = _touch(tmp_path / "a")
    assert set(preview.snapshot([f, tmp_path / "missing"])) == {f}


def test_watch_rebuilds_when_a_file_changes(tmp_path: Path) -> None:
    import os

    f = _touch(tmp_path / "spec")
    calls: list[int] = []
    ticks = iter(range(100))

    def fake_sleep(_s: float) -> None:
        if next(ticks) == 2:  # 第三輪：改檔案
            f.write_text("changed", encoding="utf-8")
            os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))

    n = preview.watch(lambda: calls.append(1), lambda: [f], interval=0, max_rebuilds=1, sleep=fake_sleep)
    assert n == 1
    assert len(calls) == 2  # 先建一次，再因變動重建一次


def test_watch_notices_new_files(tmp_path: Path) -> None:
    files = [_touch(tmp_path / "a")]
    calls: list[int] = []

    def fake_sleep(_s: float) -> None:
        if len(files) == 1:
            files.append(_touch(tmp_path / "new.png"))

    preview.watch(lambda: calls.append(1), lambda: list(files), interval=0, max_rebuilds=1, sleep=fake_sleep)
    assert len(calls) == 2


def test_watched_files_include_brand_design_and_layers(repo: Path) -> None:
    write(repo / "_quarto.yml", "author: 甲\n")
    deck = repo / "deck"
    write(deck / "deck.yml", "title: x\n")
    write(deck / "screens" / "a.png", "")
    names = {p.name for p in cli._watched(deck / "deck.yml", deck)}
    assert {"deck.yml", "design.yml", "_brand.yml", "_quarto.yml", "a.png"} <= names


def test_preview_cli_runs_the_pipeline(
    monkeypatch: pytest.MonkeyPatch, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / "_quarto.yml", "author: 甲\n")
    deck = repo / "deck"
    cli.main(["new", str(deck)])
    seen: dict[str, Path] = {}

    def fake_pdf(pptx: Path, pdf: Path) -> None:
        seen["pdf"] = pdf
        pdf.write_bytes(b"%PDF")

    def fake_pages(pdf: Path, out_dir: Path, dpi: int = 72) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "slide-01.png"
        Image.new("RGB", (96, 54)).save(p)
        return [p]

    monkeypatch.setattr("deckstyle.export.export_pdf", fake_pdf)
    monkeypatch.setattr("deckstyle.preview.render_pages", fake_pages)
    assert cli.main(["preview", str(deck)]) == 0
    assert seen["pdf"].suffix == ".pdf"
    assert (deck / "_output" / "preview" / "sheet-1.png").is_file()
    assert "預覽" in capsys.readouterr().err


def test_preview_watch_mode_survives_spec_errors(
    monkeypatch: pytest.MonkeyPatch, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / "deck" / "deck.yml", "title: only\n")

    def run_once_then_interrupt(build: Any, files: Any, interval: float = 0.5) -> int:
        build()
        raise KeyboardInterrupt

    monkeypatch.setattr("deckstyle.preview.watch", run_once_then_interrupt)
    assert cli.main(["preview", str(repo / "deck"), "--watch"]) == 0
    err = capsys.readouterr().err
    assert "✗" in err and "結束監看" in err


def test_preview_without_watch_raises_spec_errors(repo: Path) -> None:
    write(repo / "deck" / "deck.yml", "title: only\n")
    assert cli.main(["preview", str(repo / "deck")]) == 1
