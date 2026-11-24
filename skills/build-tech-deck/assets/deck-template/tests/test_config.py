"""分層中繼資料：直接讀 Quarto 官方的 _quarto.yml 與 _metadata.yml（專案層 → 目錄層 → 文件層）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import QUARTO_FILE, write

from deckstyle import config
from deckstyle.spec import SpecError

AUTHOR = "author:\n  - name: 作者甲\n    affiliation: 範例單位\n"


# ---- 合併規則 ----


def test_merge_follows_quarto_rules() -> None:
    base = {"format": {"toc": True}, "bib": ["a"], "title": "舊"}
    over = {"format": {"fold": True}, "bib": ["b"], "title": "新"}
    assert config.merge(base, over) == {"format": {"toc": True, "fold": True}, "bib": ["a", "b"], "title": "新"}


def test_merge_does_not_mutate_inputs() -> None:
    base = {"bib": ["a"]}
    config.merge(base, {"bib": ["b"]})
    assert base == {"bib": ["a"]}


# ---- 作者 ----


def test_author_string_table_and_list_forms() -> None:
    assert config.normalize_authors("作者甲") == [{"name": "作者甲", "affiliations": []}]
    one = config.normalize_authors({"name": "作者甲", "affiliation": "單位甲"})
    assert one == [{"name": "作者甲", "affiliations": ["單位甲"]}]
    many = config.normalize_authors([{"name": "甲", "affiliations": ["單位一", {"name": "單位二"}]}, "乙"])
    assert many[0]["affiliations"] == ["單位一", "單位二"]
    assert many[1]["name"] == "乙"


def test_other_quarto_author_fields_are_ignored() -> None:
    got = config.normalize_authors([{"name": "甲", "email": "a@b.c", "orcid": "0000", "corresponding": True}])
    assert got == [{"name": "甲", "affiliations": []}]


def test_same_name_merges_into_one_author() -> None:
    merged = config.normalize_authors(
        [{"name": "作者甲", "affiliation": "單位甲"}, {"name": "作者甲", "affiliation": ["單位甲", "研究室"]}]
    )
    assert merged == [{"name": "作者甲", "affiliations": ["單位甲", "研究室"]}]


@pytest.mark.parametrize(
    "bad", [[], {}, 5, [{"affiliation": "x"}], [{"name": "甲", "affiliation": 3}], [3], [{"name": " "}]]
)
def test_bad_author_is_rejected(bad: Any) -> None:
    with pytest.raises(SpecError):
        config.normalize_authors(bad)


def test_format_author_puts_affiliation_before_name() -> None:
    authors = config.normalize_authors({"name": "作者甲", "affiliation": "範例單位"})
    assert config.format_author(authors) == "範例單位 作者甲"


def test_format_author_groups_by_affiliation() -> None:
    authors = config.normalize_authors(
        [{"name": n, "affiliation": "單位甲"} for n in ("作者甲", "作者乙", "作者丙")] + ["指導老師"]
    )
    assert config.format_author(authors) == "單位甲 作者甲　作者乙　作者丙；指導老師"
    assert config.author_names(authors) == "作者甲、作者乙、作者丙、指導老師"


# ---- 分層 ----


def test_layers_run_from_root_to_nearest(repo: Path) -> None:
    root = write(repo / "_quarto.yml", AUTHOR)
    course = write(repo / "course" / "_metadata.yml", AUTHOR)
    deck = repo / "course" / "deck"
    deck.mkdir()
    deep = write(deck / "_metadata.yml", "lang: en\n")
    assert config.layer_files(deck) == [root, course, deep]


def test_each_directory_contributes_quarto_then_metadata(repo: Path) -> None:
    a = write(repo / "_quarto.yml", AUTHOR)
    b = write(repo / "_metadata.yml", "lang: en\n")
    assert config.layer_files(repo) == [a, b]


def test_without_git_root_only_the_deck_dir_counts(tmp_path: Path) -> None:
    deck = tmp_path / "deck"
    write(tmp_path / "_quarto.yml", AUTHOR)  # 上層的檔案不該被誤讀
    own = write(deck / "_metadata.yml", AUTHOR)
    assert config.layer_files(deck) == [own]


def test_worktree_style_git_file_marks_the_root(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert config.project_root(tmp_path / "a") == tmp_path


def test_explicit_stop_must_be_an_ancestor(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="不在簡報目錄"):
        config.layer_files(tmp_path / "a", stop=tmp_path / "b")


def test_resolve_concatenates_authors_across_layers(repo: Path) -> None:
    write(repo / "_quarto.yml", AUTHOR)
    write(repo / "g" / "_metadata.yml", "author:\n  - name: 作者乙\n    affiliation: 範例單位\n")
    spec = {"short_title": "s", "author": {"name": "作者丙", "affiliation": "範例單位"}}
    final = config.resolve(spec, repo / "g")
    assert config.format_author(final["author"]) == "範例單位 作者甲　作者乙　作者丙"
    assert spec["author"] == {"name": "作者丙", "affiliation": "範例單位"}  # 原規格不動


def test_resolve_dedupes_author_repeated_in_document(repo: Path) -> None:
    write(repo / "_quarto.yml", AUTHOR)
    spec = {"author": {"name": "作者甲", "affiliation": "範例單位"}}
    assert config.format_author(config.resolve(spec, repo)["author"]) == "範例單位 作者甲"


def test_document_scalar_wins_over_layers(repo: Path) -> None:
    write(repo / "_quarto.yml", "lang: en\ndate: 2026-01-01\n" + AUTHOR)
    final = config.resolve({"lang": "zh-TW"}, repo)
    assert final["lang"] == "zh-TW"
    assert str(final["date"]) == "2026-01-01"


def test_lang_defaults_to_zh_tw(repo: Path) -> None:
    assert config.resolve({}, repo)["lang"] == "zh-TW"


def test_lint_lists_concatenate(repo: Path) -> None:
    write(repo / "_quarto.yml", AUTHOR + "lint:\n  deny: [shop-api]\n")
    write(repo / "c" / "_metadata.yml", "lint:\n  deny: [billing]\n  allow: [a_b]\n")
    final = config.resolve({"lint": {"deny": ["x-svc"]}}, repo / "c")
    assert final["lint"] == {"deny": ["shop-api", "billing", "x-svc"], "allow": ["a_b"]}


def test_other_quarto_keys_are_ignored(repo: Path) -> None:
    """_quarto.yml 裡 Quarto 自己的鍵（project、format、bibliography…）簡報不讀，也不報錯。"""
    write(
        repo / "_quarto.yml",
        "project:\n  type: default\nformat:\n  pdf:\n    toc: true\nbibliography: refs.bib\n" + AUTHOR,
    )
    final = config.resolve({}, repo)
    assert "project" not in final and "format" not in final
    assert final["author"][0]["name"] == "作者甲"


def test_yaml_syntax_error_names_the_file(repo: Path) -> None:
    write(repo / "_quarto.yml", "author: [\n")
    with pytest.raises(SpecError, match=r"_quarto\.yml"):
        config.resolve({}, repo)


def test_non_mapping_layer_is_rejected(repo: Path) -> None:
    write(repo / "_quarto.yml", "- a\n- b\n")
    with pytest.raises(SpecError, match="對應表"):
        config.resolve({}, repo)


def test_empty_layer_file_is_fine(repo: Path) -> None:
    write(repo / "_quarto.yml", "")
    assert config.resolve({"author": "甲"}, repo)["author"][0]["name"] == "甲"


def test_resolve_without_layers_normalizes_author() -> None:
    final = config.resolve({"short_title": "s", "author": "甲"}, Path("/nonexistent-deck-dir"))
    assert final["author"] == [{"name": "甲", "affiliations": []}]


def test_project_quarto_yml_declares_the_author() -> None:
    """專案根的 _quarto.yml 是作者的唯一來源：結構合規，封面印得出「單位 姓名」。"""
    layer = config.load_layer(QUARTO_FILE)
    assert config.format_author(layer["author"])


def test_describe_lists_files_and_result(repo: Path) -> None:
    write(repo / "_quarto.yml", AUTHOR)
    text = config.describe({"short_title": "s"}, repo)
    assert "_quarto.yml" in text
    assert "作者：範例單位 作者甲" in text


# ---- {{< meta 鍵 >}} ----


def test_meta_shortcode_reads_any_layered_key(repo: Path) -> None:
    write(repo / "_quarto.yml", AUTHOR)
    write(repo / "c" / "_metadata.yml", "course-name: 課程甲\ncourse:\n  code: 1234\n")
    spec = {
        "category": "{{< meta course.code >}} {{< meta course-name >}}｜期末",
        "slides": [
            {
                "ref": "{{<meta course-name>}}｜問題",
                "blocks": [{"block": "note", "lines": ["{{< meta course-name >}}"]}],
            }
        ],
    }
    final = config.resolve(spec, repo / "c" / "deck")
    assert final["category"] == "1234 課程甲｜期末"
    assert final["slides"][0]["ref"] == "課程甲｜問題"
    assert final["slides"][0]["blocks"][0]["lines"] == ["課程甲"]
    assert spec["category"].startswith("{{< meta")  # 原規格不動


def test_meta_shortcode_nearer_layer_wins(repo: Path) -> None:
    write(repo / "_quarto.yml", "course-name: 上層\n")
    write(repo / "c" / "_metadata.yml", "course-name: 下層\n")
    assert config.resolve({"category": "{{< meta course-name >}}"}, repo / "c")["category"] == "下層"


def test_meta_shortcode_missing_key_is_an_error(repo: Path) -> None:
    with pytest.raises(SpecError, match="找不到這個鍵"):
        config.resolve({"category": "{{< meta course-name >}}"}, repo)


def test_meta_shortcode_rejects_non_scalar_values(repo: Path) -> None:
    write(repo / "_quarto.yml", "course:\n  code: 1234\n")
    with pytest.raises(SpecError, match="值須為字串或數字"):
        config.resolve({"category": "{{< meta course >}}"}, repo)
