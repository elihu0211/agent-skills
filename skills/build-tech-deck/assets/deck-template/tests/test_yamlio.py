"""YAML 讀取：安全載入，布林只認 true／false（YAML 1.2 核心結構）。"""

from __future__ import annotations

import pytest

from deckstyle import yamlio


@pytest.mark.parametrize("word", ["no", "No", "NO", "yes", "on", "off", "y", "n"])
def test_yaml_1_1_booleans_stay_strings(word: str) -> None:
    assert yamlio.loads(f"k: {word}\n") == {"k": word}


@pytest.mark.parametrize(("text", "value"), [("true", True), ("True", True), ("FALSE", False), ("false", False)])
def test_true_and_false_are_booleans(text: str, value: bool) -> None:
    assert yamlio.loads(f"k: {text}\n") == {"k": value}


def test_numbers_and_chinese_text_survive() -> None:
    assert yamlio.loads("a: 1.5\nb: 00 摘要 · Summary\nc: [1, 2]\n") == {
        "a": 1.5,
        "b": "00 摘要 · Summary",
        "c": [1, 2],
    }


def test_syntax_error_names_file_and_line() -> None:
    with pytest.raises(yamlio.YamlError, match=r"x\.yml:\d+"):
        yamlio.loads("a: 1\nb: [\n", "x.yml")


def test_unsafe_tags_are_rejected() -> None:
    with pytest.raises(yamlio.YamlError):
        yamlio.loads("k: !!python/object/apply:os.system ['echo hi']\n")
