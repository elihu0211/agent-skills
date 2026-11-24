"""分層的簡報中繼資料：直接讀 Quarto 官方的 `_quarto.yml` 與 `_metadata.yml`，作者、日期、語言與 lint 名單只寫一次。

Quarto 把專案層（`_quarto.yml`）、目錄層（`dir/_metadata.yml`）與文件層（前言）合併，越靠近文件的優先；
物件逐鍵合併、陣列串接、純量由較近的一層覆蓋。簡報與 Quarto 文件讀同一批檔案、同一套規則：

    <專案根>/_quarto.yml             專案層：全專案共用的作者與單位
    <專案根>/<目錄>/_metadata.yml     目錄層：這個目錄要加的作者（選用，可再往下一層）
    <簡報目錄>/deck.yml              文件層：deck.yml 裡寫的鍵最後合併

搜尋範圍是簡報目錄往上到專案根（含 `.git` 的目錄）；找不到專案根就只看簡報目錄自己，不會誤讀無關的上層檔案。
每個目錄依序貢獻 `_quarto.yml`、`_metadata.yml`。這些檔案裡直接合併進規格的只有 `LAYERED` 的鍵，其餘（Quarto 的格式、
書目…）不併入。作者用 Quarto 的結構寫法：`name` 加 `affiliation`（字串或清單），也收 `affiliations`（字串或 `{name: ...}`
的清單）；陣列串接，所以上層的作者在下層仍在，同名的作者合併成一位。

deck.yml 的字串可用 Quarto 官方的 `{{< meta 鍵 >}}` 取分層中繼資料的任一個鍵（鍵照 YAML 原樣，`a.b` 取巢狀鍵），
讓課程名稱這類值只在 `_metadata.yml` 寫一次；找不到或不是純量就報錯，不留下原樣的佔位字。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import yamlio
from .spec import SpecError, from_yaml

FILES = ("_quarto.yml", "_quarto.yaml", "_metadata.yml", "_metadata.yaml")
# 可分層的鍵：作者、日期、語言與 lint 名單。標題、輸出檔名與頁面內容是每份簡報自己的，不分層。
LAYERED = ("author", "date", "lang", "lint")
DEFAULT_LANG = "zh-TW"
# Quarto 的 meta 短代碼；鍵可含 `-`、`_` 與表示巢狀的 `.`
META_SHORTCODE = re.compile(r"\{\{<\s*meta\s+([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*>\}\}")


def project_root(start: Path) -> Path | None:
    """往上找第一個含 `.git`（目錄或 worktree 的檔案）的目錄；找不到回傳 None。"""
    start = start.resolve()
    return next((d for d in (start, *start.parents) if (d / ".git").exists()), None)


def layer_files(start: Path, stop: Path | None = None) -> list[Path]:
    """`start` 往上到專案根（含）之間存在的設定檔，由遠到近（低優先到高優先）。

    `stop` 指定專案根（測試與特殊佈局用）；省略就用 `project_root`，再找不到就只看 `start` 自己。
    """
    start = start.resolve()
    root = stop.resolve() if stop else project_root(start)
    if root is None:
        dirs = [start]
    else:
        if root != start and root not in start.parents:
            raise SpecError(f"專案根 {root} 不在簡報目錄 {start} 的上層")
        dirs = [d for d in (start, *start.parents) if d == root or root in d.parents]
    return [d / n for d in reversed(dirs) for n in FILES if (d / n).is_file()]


def merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """Quarto 的合併規則：物件逐鍵合併、陣列串接（base 在前）、純量由 over 覆蓋。"""
    out = dict(base)
    for key, value in over.items():
        cur = out.get(key)
        if isinstance(cur, Mapping) and isinstance(value, Mapping):
            out[key] = merge(cur, value)
        elif isinstance(cur, list) and isinstance(value, list):
            out[key] = [*cur, *value]
        else:
            out[key] = value
    return out


# ---- 作者 ----


def _affiliations(where: str, raw: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("affiliation", "affiliations"):
        v = raw.get(key)
        if v is None:
            continue
        if isinstance(v, (str, Mapping)):
            values.append(v)
        elif isinstance(v, Sequence) and not isinstance(v, bytes):
            values += list(v)
        else:
            raise SpecError(f"{where}：{key} 須為字串、含 name 的表，或它們的清單：{v!r}")
    out = []
    for v in values:
        name = v.get("name") if isinstance(v, Mapping) else v
        if not isinstance(name, str) or not name.strip():
            raise SpecError(f"{where}：單位須為非空字串或含 name 的表：{v!r}")
        out.append(name.strip())
    return out


def normalize_authors(value: Any, where: str = "author") -> list[dict[str, Any]]:
    """把作者寫法正規化成 `[{"name": 姓名, "affiliations": [單位…]}]`，同名合併。

    收：字串（原樣當一位作者）、含 `name` 的表、以及這兩種的清單。
    """
    if isinstance(value, (str, Mapping)):
        items: list[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, bytes):
        items = list(value)
    else:
        raise SpecError(f"{where}：須為字串、含 name 的表，或它們的清單：{value!r}")
    authors: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(items, 1):
        here = f"{where}[{i}]"
        if isinstance(raw, str):
            name, affs = raw, []
        elif isinstance(raw, Mapping):
            name, affs = (
                raw.get("name"),
                _affiliations(here, raw),
            )  # Quarto 的其他作者欄位（email、orcid…）簡報不用，忽略
        else:
            raise SpecError(f"{here}：須為字串或含 name 的表：{raw!r}")
        if not isinstance(name, str) or not name.strip():
            raise SpecError(f"{here}：缺 name")
        entry = authors.setdefault(name.strip(), {"name": name.strip(), "affiliations": []})
        entry["affiliations"] += [a for a in affs if a not in entry["affiliations"]]
    if not authors:
        raise SpecError(f"{where}：不可為空")
    return list(authors.values())


def format_author(authors: Sequence[Mapping[str, Any]]) -> str:
    """封面作者行：單位在前、姓名在後（「範例單位 作者甲」）。

    相鄰且單位相同的作者併成一組，姓名以全形空白隔開；不同單位的組以「；」隔開。
    """
    groups: list[tuple[tuple[str, ...], list[str]]] = []
    for a in authors:
        affs = tuple(a["affiliations"])
        if groups and groups[-1][0] == affs:
            groups[-1][1].append(a["name"])
        else:
            groups.append((affs, [a["name"]]))
    return "；".join((" / ".join(affs) + " " if affs else "") + "　".join(names) for affs, names in groups)


def author_names(authors: Sequence[Mapping[str, Any]]) -> str:
    """文件屬性的作者欄：只列姓名。"""
    return "、".join(a["name"] for a in authors)


# ---- 分層讀取與合併 ----


def _read(path: Path) -> dict[str, Any]:
    try:
        data = yamlio.load(path)
    except yamlio.YamlError as e:
        raise SpecError(str(e)) from None
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise SpecError(f"{path}：最上層須為對應表")
    return dict(data)


def load_layer(path: Path) -> dict[str, Any]:
    """讀一份 `_quarto.yml`／`_metadata.yml`；只取 `LAYERED` 的鍵，作者先正規化（才能跨層串接）。"""
    layer = {k: from_yaml(v) for k, v in _read(path).items() if k in LAYERED}
    if "author" in layer:
        layer["author"] = normalize_authors(layer["author"], f"{path.name} 的 author")
    return layer


def resolve(spec: Mapping[str, Any], deck_dir: Path, stop: Path | None = None) -> dict[str, Any]:
    """把分層設定合併進規格：各層設定檔（遠到近），最後是 deck.yml 自己的同名鍵。

    回傳新的規格，`author` 已是正規化的清單、`lang` 一定有值；原規格不動。
    """
    doc = {k: v for k, v in spec.items() if k in LAYERED}
    if "author" in doc:
        doc["author"] = normalize_authors(doc["author"])
    merged: dict[str, Any] = {}
    for layer in [*(load_layer(p) for p in layer_files(deck_dir, stop)), doc]:
        merged = merge(merged, layer)
    if "author" in merged:
        merged["author"] = normalize_authors(merged["author"])  # 串接後再合併同名
    merged.setdefault("lang", DEFAULT_LANG)
    return expand({**spec, **merged}, metadata(deck_dir, stop))


# ---- {{< meta 鍵 >}} ----


def metadata(deck_dir: Path, stop: Path | None = None) -> dict[str, Any]:
    """分層設定檔的全部鍵（遠到近合併，鍵照 YAML 原樣）；`{{< meta 鍵 >}}` 從這裡取值。"""
    merged: dict[str, Any] = {}
    for path in layer_files(deck_dir, stop):
        merged = merge(merged, _read(path))
    return merged


def _lookup(meta: Mapping[str, Any], key: str) -> str:
    value: Any = meta
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise SpecError(f"{{{{< meta {key} >}}}}：_quarto.yml／_metadata.yml 分層裡找不到這個鍵")
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SpecError(f"{{{{< meta {key} >}}}}：值須為字串或數字，實際是 {value!r}")
    return str(value)


def expand(value: Any, meta: Mapping[str, Any]) -> Any:
    """把規格裡所有字串的 `{{< meta 鍵 >}}` 換成中繼資料的值；其他型別原樣，原規格不動。"""
    if isinstance(value, str):
        return META_SHORTCODE.sub(lambda m: _lookup(meta, m.group(1)), value)
    if isinstance(value, Mapping):
        return {k: expand(v, meta) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, meta) for v in value]
    return value


def describe(spec: Mapping[str, Any], deck_dir: Path, stop: Path | None = None) -> str:
    """`deckstyle inspect` 的輸出：參與合併的檔案與合併後的結果。"""
    files = layer_files(deck_dir, stop)
    out = ["分層（低優先 → 高優先）："]
    out += [f"  {p}" for p in files] or ["  （沒有 _quarto.yml、_metadata.yml）"]
    out.append("  deck.yml")
    final = resolve(spec, deck_dir, stop)
    if "author" in final:
        out.append(f"作者：{format_author(final['author'])}")
    out += [f"{k}：{final[k]}" for k in ("date", "lang") if k in final]
    if final.get("lint"):
        out.append(f"lint：{final['lint']}")
    return "\n".join(out)
