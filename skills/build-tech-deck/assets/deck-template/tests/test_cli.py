"""命令列：new、build、lint、outline、inspect、schema、template、theme 的結束碼與產出。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import TEMPLATE, one_slide, write
from pptx import Presentation

from deckstyle import cli, outline

AUTHOR = "author:\n  - name: 作者甲\n    affiliation: 範例單位\n"


def _deck(path: Path, spec: dict[str, Any]) -> Path:
    """把內部形狀的規格寫成使用者看到的 deck.yml（kebab-case）。"""

    def kebab(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k).replace("_", "-"): kebab(x) for k, x in v.items()}
        return [kebab(x) for x in v] if isinstance(v, list) else v

    return write(
        path / "deck.yml" if path.suffix != ".yml" else path,
        yaml.safe_dump(kebab(spec), allow_unicode=True, sort_keys=False),
    )


@pytest.fixture
def project(repo: Path) -> Path:
    """有品牌與專案層作者的假專案。"""
    write(repo / "_quarto.yml", AUTHOR)
    return repo


def test_new_copies_template_and_builds(project: Path) -> None:
    dest = project / "deck"
    assert cli.main(["new", str(dest)]) == 0
    assert (dest / "deck.yml").is_file()
    assert (dest / "screens" / "sample.png").is_file()
    assert cli.main(["build", str(dest)]) == 0  # 傳目錄即可
    built = dest / "_output" / "D01_現場雙碼掃描技術提案_v1.0.pptx"
    assert built.is_file()
    cover = Presentation(str(built)).slides[0]
    assert "範例單位 作者甲" in {sh.text_frame.text for sh in cover.shapes if sh.has_text_frame}


def test_new_refuses_to_overwrite(project: Path) -> None:
    cli.main(["new", str(project / "d")])
    assert cli.main(["new", str(project / "d")]) == 2
    assert cli.main(["new", str(project / "d"), "--force"]) == 0


def test_build_returns_1_when_lint_fails(project: Path) -> None:
    spec = one_slide([("note", {"lines": ["呼叫 load_data 函式"]})])
    path = _deck(project / "d", spec)
    out = project / "o.pptx"
    assert cli.main(["build", str(path), "-o", str(out)]) == 1
    assert out.is_file()  # lint 失敗仍留下 pptx 供檢視
    assert cli.main(["build", str(path), "-o", str(out), "--no-lint"]) == 0


def test_build_uses_spec_deny_list(project: Path) -> None:
    spec = one_slide([("note", {"lines": ["連到 shop-api 服務"]})])
    assert cli.main(["build", str(_deck(project / "a", spec)), "-o", str(project / "a.pptx")]) == 0
    spec["lint"] = {"deny": ["shop-api"]}
    assert cli.main(["build", str(_deck(project / "b", spec)), "-o", str(project / "b.pptx")]) == 1


def test_build_uses_the_layered_deny_list(project: Path) -> None:
    write(project / "_quarto.yml", AUTHOR + "lint:\n  deny: [shop-api]\n")
    spec = one_slide([("note", {"lines": ["連到 shop-api 服務"]})])
    del spec["author"]
    assert cli.main(["build", str(_deck(project / "d", spec)), "-o", str(project / "o.pptx")]) == 1


def test_build_reports_spec_errors(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = one_slide([("note", {})])
    assert cli.main(["build", str(_deck(project / "d", spec)), "-o", str(project / "o.pptx")]) == 1
    assert "規格有誤" in capsys.readouterr().err


def test_build_without_brand_says_where_to_put_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".git").mkdir()
    spec = one_slide([("note", {"lines": ["x"]})])
    assert cli.main(["build", str(_deck(tmp_path / "d", spec))]) == 1
    assert "_brand.yml" in capsys.readouterr().err


def test_build_missing_spec(tmp_path: Path) -> None:
    assert cli.main(["build", str(tmp_path / "none.yml")]) == 2


def test_find_spec_accepts_both_yaml_extensions(tmp_path: Path) -> None:
    with pytest.raises(cli.CliError, match="沒有規格檔"):
        cli.find_spec(tmp_path)
    write(tmp_path / "deck.yaml", "title: x\n")
    assert cli.find_spec(tmp_path).name == "deck.yaml"
    write(tmp_path / "deck.yml", "title: x\n")
    assert cli.find_spec(tmp_path).name == "deck.yml"


def test_broken_yaml_names_file_and_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "deck.yml", "title: [\n")
    assert cli.main(["build", str(tmp_path)]) == 2
    assert "deck.yml" in capsys.readouterr().err


def test_non_mapping_deck_is_rejected(tmp_path: Path) -> None:
    write(tmp_path / "deck.yml", "- a\n")
    assert cli.main(["build", str(tmp_path)]) == 2


def test_default_output_name_follows_output_file(project: Path) -> None:
    spec = one_slide([("note", {"lines": ["x"]})])
    spec["output_file"] = "D02_期末簡報_v1.0"
    deck = project / "deck"
    _deck(deck, spec)
    assert cli.main(["build", str(deck)]) == 0
    assert (deck / "_output" / "D02_期末簡報_v1.0.pptx").is_file()


def test_kebab_keys_in_deck_yml_reach_the_engine(project: Path) -> None:
    """使用者寫 kebab-case（short-title、arch-graph、col-w），引擎內部用 snake_case，兩邊接得起來。"""
    write(
        project / "d" / "deck.yml",
        """
title: 題名
subtitle: 副題
category: 分類
short-title: 短名
slides:
  - title: 一頁
    blocks:
      - block: table
        col-w: [1, 1]
        rows: [[欄一, 欄二], [甲, [乙, green]]]
      - block: arch-graph
        nodes:
          - {id: a, col: 0, row: 0, title: A}
""",
    )
    assert cli.main(["build", str(project / "d"), "-o", str(project / "o.pptx")]) == 0


def test_lint_subcommand(tmp_path: Path, template_pptx: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["lint", str(template_pptx)]) == 0
    assert cli.main(["lint", str(template_pptx), "--json"]) == 0
    assert '"wrap": []' in capsys.readouterr().out
    assert cli.main(["lint", str(tmp_path / "missing.pptx")]) == 2


def test_lint_subcommand_deny(build_spec: Any) -> None:
    path = build_spec(one_slide([("note", {"lines": ["連到 shop-api 服務"]})]))
    assert cli.main(["lint", str(path)]) == 0
    assert cli.main(["lint", str(path), "--deny", "shop-api"]) == 1
    assert cli.main(["lint", str(path), "--deny", "shop-api", "--allow", "shop-api"]) == 0


def test_theme_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["theme", str(TEMPLATE)]) == 0
    assert "品牌：example-brand" in capsys.readouterr().out


def test_theme_subcommand_without_brand(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert cli.main(["theme", str(tmp_path)]) == 1


def test_python_dash_m_entry() -> None:
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "deckstyle", "theme", str(TEMPLATE)], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0
    assert "品牌" in r.stdout


def test_inspect_lists_layers(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deck = project / "course" / "deck"
    write(project / "course" / "_metadata.yml", "author:\n  - name: 作者乙\n    affiliation: 範例單位\n")
    spec = one_slide([("note", {"lines": ["x"]})])
    del spec["author"]
    _deck(deck, spec)
    assert cli.main(["inspect", str(deck)]) == 0
    out = capsys.readouterr().out
    assert out.index("_quarto.yml") < out.index("_metadata.yml") < out.index("deck.yml")
    assert "作者：範例單位 作者甲　作者乙" in out


def test_build_without_any_author_explains_where_to_put_it(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(project / "_quarto.yml", "")
    spec = one_slide([("note", {"lines": ["x"]})])
    del spec["author"]
    assert cli.main(["build", str(_deck(project / "d", spec)), "-o", str(project / "o.pptx")]) == 1
    assert "_quarto.yml" in capsys.readouterr().err


# ---- 大綱 ----


def test_outline_covers_every_block(template_spec: dict[str, Any]) -> None:
    text = outline.export(template_spec)
    assert text.startswith("# ")
    assert text.count("\n## ") == len(template_spec["slides"])
    assert "> 講稿：" in text
    assert "作者：範例單位 範例作者" in text


@pytest.mark.parametrize(
    "kind",
    [
        "banner",
        "cards",
        "kpi",
        "steps",
        "layers",
        "flow",
        "columns",
        "table",
        "swimlane",
        "arch_graph",
        "bench_chart",
        "timeline_diagram",
        "shots",
        "chart",
        "note",
    ],
)
def test_outline_handles_each_block(kind: str, template_spec: dict[str, Any]) -> None:
    from deckstyle.spec import slides_of

    sample = next(kw for page in slides_of(template_spec) for name, kw in page["blocks"] if name == kind)
    assert outline._block(kind, sample).strip()


def test_outline_cli_writes_file(project: Path) -> None:
    spec = one_slide([("note", {"lines": ["結論"]})], title="測試頁")
    path = _deck(project / "d", spec)
    out = project / "o.md"
    assert cli.main(["outline", str(path), "-o", str(out)]) == 0
    assert "## 01 測試　測試頁" in out.read_text(encoding="utf-8")
    assert cli.main(["build", str(path), "-o", str(project / "o.pptx"), "--outline", str(project / "x.md")]) == 0
    assert (project / "x.md").is_file()
