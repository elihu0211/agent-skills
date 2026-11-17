"""YAML 讀取：安全載入，布林只認 `true`／`false`（YAML 1.2 核心結構，與 Quarto 的 js-yaml 一致）。

PyYAML 預設是 YAML 1.1：`no`、`on`、`off`、`y` 會變成布林，中文簡報裡的 `no`（編號）或 `on` 因此被吃掉。
這裡換掉布林的隱含解析規則，其餘照 `yaml.SafeLoader`。純函式、無全域狀態。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class _Loader(yaml.SafeLoader):
    """YAML 1.2 風格：只有 true／false（大小寫不拘）是布林。"""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


class YamlError(ValueError):
    """YAML 語法錯誤；訊息帶檔名與行號。"""


def loads(text: str, name: str = "<字串>") -> Any:
    try:
        return yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"{name}:{mark.line + 1}" if mark else name
        raise YamlError(f"{where}：YAML 語法錯誤：{getattr(e, 'problem', e)}") from None


def load(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"), path.name)
