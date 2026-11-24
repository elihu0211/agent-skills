"""JSON Schema 匯出：把規格與中繼資料的欄位表轉成 JSON Schema（draft 2020-12），給編輯器做補全與即時驗證。

用法：`deck.yml` 檔頭加一行 `# yaml-language-server: $schema=<schema 檔路徑>`（VS Code 的 YAML 延伸套件），即補全區塊名稱、
`kind` 列舉與欄位。權威的驗證仍是 `spec.validate`（建置時跑）；schema 是同一份欄位表
（`spec.BLOCK_SCHEMA`）的投影，所以新增區塊時不必另外維護。欄位型別補在本檔的 `_TYPES`，沒列到的欄位不限型別。
純標準庫。
"""

from __future__ import annotations

from typing import Any

from .spec import (
    ALIGNS,
    BLOCK_SCHEMA,
    CHART_TYPES,
    KINDS,
    LINT_KEYS,
    PAGE_TYPES,
    TOP_OPTIONAL,
    TOP_REQUIRED,
    kebab,
)

DRAFT = "https://json-schema.org/draft/2020-12/schema"

_STR: dict[str, Any] = {"type": "string"}
_NUM: dict[str, Any] = {"type": "number"}
_INT: dict[str, Any] = {"type": "integer"}
_BOOL: dict[str, Any] = {"type": "boolean"}
_STRS: dict[str, Any] = {"type": "array", "items": _STR}
_TEXT: dict[str, Any] = {"oneOf": [_STR, _STRS]}  # 內文：一個字串（可含換行）或字串清單
_SCALAR: dict[str, Any] = {"oneOf": [_STR, _INT, _NUM]}

# 欄位名稱 → 型別。同名欄位在不同區塊型別不同時，用 _BLOCK_TYPES[(區塊, 欄位)] 覆寫。
_TYPES: dict[str, dict[str, Any]] = {
    **dict.fromkeys(
        ("title", "sub", "en", "caption", "label", "time", "name", "id", "from", "to", "image", "alt", "fmt", "value"),
        _STR,
    ),
    **dict.fromkeys(("h", "tfs", "bfs", "side_w", "cap_h", "crop", "left_w", "ratio", "vmin", "vmax", "size"), _NUM),
    **dict.fromkeys(("lane", "col", "row", "col_span", "row_span", "cols", "rows"), _INT),
    **dict.fromkeys(("bullet", "numbered", "bold", "dash", "inset", "legend", "labels"), _BOOL),
    **dict.fromkeys(("body", "items"), _TEXT),
    **dict.fromkeys(("edge_labels", "col_headers", "categories", "lines"), _STRS),
    "num": _SCALAR,
    "badge": _SCALAR,
    "col_w": {"type": "array", "items": _NUM, "minItems": 1},
    "highlight": {"type": "array", "items": _INT},
    "aligns": {"type": "array", "items": {"enum": list(ALIGNS)}},
    "values": {"type": "array", "items": _NUM},
    "type": {"enum": list(CHART_TYPES)},
    "kind": {"enum": list(KINDS)},
    "detail_kind": {"enum": list(KINDS)},
    "edge": {"enum": ["blocked", "green"]},
}
_CELL = {
    "oneOf": [_STR, {"type": "array", "prefixItems": [_STR, {"enum": list(KINDS)}], "items": False, "minItems": 2}]
}
_BLOCK_TYPES: dict[tuple[str, str], dict[str, Any]] = {
    ("table", "rows"): {"type": "array", "minItems": 1, "items": {"type": "array", "items": _CELL}},
    ("arch_graph", "cols"): _INT,
    ("arch_graph", "rows"): _INT,
    ("columns", "items"): _STRS,  # columns 的 items 在欄位元素層：條列
    ("kpi", "sub"): _TEXT,
    ("references", "items"): {**_STRS, "minItems": 1},  # 每筆書目一個字串，自動折行
}


def _node(block: str, field: str) -> dict[str, Any]:
    if (block, field) in _BLOCK_TYPES:
        return dict(_BLOCK_TYPES[(block, field)])
    return dict(_TYPES.get(field, {}))


def _object(block: str, schema: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """依欄位表產生一個物件的 schema（鍵用 kebab-case）；元素列表（lists）遞迴展開。"""
    req, opt = list(schema.get("req", ())), list(schema.get("opt", ()))
    lists = schema.get("lists", {})
    props: dict[str, Any] = dict(extra or {})
    for field in (*req, *opt):
        if field in lists:
            props[kebab(field)] = {
                "type": "array",
                "items": _object(block, lists[field]),
                **({"minItems": 1} if field in req else {}),
            }
        else:
            props[kebab(field)] = _node(block, field)
    for field, allowed in schema.get("enums", {}).items():
        props[kebab(field)] = {"enum": list(allowed)}
    return {"type": "object", "properties": props, "required": [kebab(f) for f in req], "additionalProperties": False}


def _block(name: str) -> dict[str, Any]:
    obj = _object(name, BLOCK_SCHEMA[name], {"block": {"const": kebab(name)}})
    obj["required"] = ["block", *obj["required"]]
    return obj


def _page(kind: str, spec: dict[str, Any]) -> dict[str, Any]:
    """一種頁面（content、divider、closing）的 schema。內容頁的 `type` 可省略，其餘必填。"""
    props: dict[str, Any] = {"type": {"const": kind}}
    for f in (*spec["req"], *spec["opt"]):
        if f == "blocks":
            props[f] = {"type": "array", "items": {"$ref": "#/$defs/block"}, "minItems": 1}
        elif f != "type":
            props[f] = _TEXT if f == "notes" else _STR
    return {"type": "object", "properties": props, "required": list(spec["req"]), "additionalProperties": False}


def author_schema() -> dict[str, Any]:
    person = {
        "type": "object",
        "properties": {
            "name": _STR,
            "affiliation": {"oneOf": [_STR, _STRS]},
            "affiliations": {
                "type": "array",
                "items": {"oneOf": [_STR, {"type": "object", "properties": {"name": _STR}, "required": ["name"]}]},
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    return {"oneOf": [_STR, person, {"type": "array", "items": {"oneOf": [_STR, person]}, "minItems": 1}]}


def _lint_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {k: _STRS for k in LINT_KEYS}, "additionalProperties": False}


def spec_schema() -> dict[str, Any]:
    """`deck.yml` 的 schema。鍵用 kebab-case，區塊寫成 `{block: 名稱, ...欄位}`。"""
    top: dict[str, Any] = {kebab(f): _STR for f in (*TOP_REQUIRED, *TOP_OPTIONAL)}
    top.update(
        {
            "author": author_schema(),
            "lint": _lint_schema(),
            "notes": _TEXT,
            "slides": {
                "type": "array",
                "minItems": 1,
                "items": {"oneOf": [_page(k, v) for k, v in PAGE_TYPES.items()]},
            },
        }
    )
    return {
        "$schema": DRAFT,
        "title": "deckstyle 簡報規格（deck.yml）",
        "type": "object",
        "properties": top,
        "required": [kebab(f) for f in TOP_REQUIRED],
        "additionalProperties": False,
        "$defs": {"block": {"oneOf": [_block(n) for n in BLOCK_SCHEMA]}},
    }


def metadata_schema() -> dict[str, Any]:
    """`_quarto.yml`／`_metadata.yml` 裡簡報會讀的鍵（author、date、lang、lint）；其餘 Quarto 的鍵不在此限。"""
    return {
        "$schema": DRAFT,
        "title": "deckstyle 讀取的分層中繼資料（author、date、lang、lint）",
        "type": "object",
        "properties": {"author": author_schema(), "date": _SCALAR, "lang": _STR, "lint": _lint_schema()},
    }


def schemas() -> dict[str, dict[str, Any]]:
    return {"spec": spec_schema(), "metadata": metadata_schema()}
