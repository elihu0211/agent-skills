"""宣告式規格的結構與驗證：規格是純資料（YAML 讀進來的 dict、list、字串、數字），不依賴 python-pptx。

簡報來源是 `deck.yml`：鍵用 Quarto 慣用的 kebab-case（`short-title`、`col-w`），讀進來後 `from_yaml` 換成內部的
snake_case，之後引擎、匯出器與驗證都吃同一份形狀。只有一種寫法，沒有別名與相容形式：

- 最上層：`title`、`subtitle`、`category`、`short-title`、`slides` 必填；`author`、`date`、`lang`、`lint` 可來自
  Quarto 的 `_quarto.yml`／`_metadata.yml` 分層（見 `config.py`）；`output-file`、`meta`、`notes` 選填。
- 每頁是一個 mapping：`type`（`content` 預設、`divider`、`closing`）、`ref`、`title`、`sub`、`meta`、`notes`，
  內容頁另有 `blocks`；每個區塊是 `{block: 名稱, ...欄位}`。

規格寫錯就在繪圖前停下，訊息帶頁碼、區塊與欄位，不讓 `KeyError` 或 `TypeError` 漏到使用者眼前。

查規格錯誤：訊息的「第 N 頁」從封面算起（封面是第 1 頁，`slides` 的第一項是第 2 頁）。每個區塊的必填與選填欄位
在下面的 `BLOCK_SCHEMA`；`deckstyle schema spec -o spec.schema.json` 輸出同一份 JSON Schema，`deck.yml` 檔頭加
`# yaml-language-server: $schema=spec.schema.json` 就能讓編輯器即時標出寫錯的欄位。各區塊的寫法與範例在技能的
`SKILL.md` 與 `references/declarations.md`、`references/patterns.md`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SEMANTIC = ("blue", "green", "amber", "red")
# 卡片與節點的 kind：語義色（含 _fill 淡底版）加四個中性與墨色。唯一真值是 theme 的 cards，測試比對兩邊一致。
KINDS = (
    "gray",
    "white",
    "dark",
    "solid_dark",
    *SEMANTIC,
    *(f"{k}_fill" for k in SEMANTIC),
)
EDGE_KINDS = ("solid", "forward", "green", "dashed", "blocked")
CHART_TYPES = ("column", "bar", "line", "pie")
ALIGNS = ("left", "center", "right")
PAGE_TYPES = {
    "content": {"req": ("title", "blocks"), "opt": ("type", "ref", "notes")},
    "divider": {"req": ("type", "title"), "opt": ("ref", "sub", "notes")},
    "closing": {"req": ("type", "title"), "opt": ("sub", "meta", "notes")},
}


class SpecError(ValueError):
    """簡報規格有誤；訊息說明哪裡錯、該怎麼改。"""


# 會畫成文字的欄位：值須是字串，不然畫到一半才 TypeError。TEXT_MANY 另收字串清單（多行或條列）。
TEXT_ONE = ("title", "subtitle", "category", "short_title", "ref", "meta", "caption", "label", "time", "name", "alt")
TEXT_ONE += ("value", "en")
TEXT_MANY = ("sub", "body", "items", "lines", "edge_labels", "col_headers", "notes")
_YAML_HINT = (
    "：YAML 會把沒加引號的 2026、3.5、true 讀成數字或布林；方括號清單 [a, b] 以半形逗號分項，"
    "文字裡有半形逗號（如「Lin & Huang, 2026」）就整段加引號"
)


def check_text(where: str, field: str, value: Any) -> None:
    """會畫成文字的欄位須是字串（TEXT_MANY 也收字串清單，選填留空可為 null）；其他欄位不在這裡管。"""
    if field not in TEXT_ONE and field not in TEXT_MANY:
        return
    many = field in TEXT_MANY
    if isinstance(value, str) or (many and value is None):
        return
    if many and isinstance(value, list):
        for i, v in enumerate(value):
            if not isinstance(v, str):
                raise SpecError(
                    f"{where}：{kebab(field)} 第 {i + 1} 項須為字串，拿到 {v!r}（{type(v).__name__}）{_YAML_HINT}"
                )
        return
    want = "字串或字串清單" if many else "字串"
    raise SpecError(f"{where}：{kebab(field)} 須為{want}，拿到 {value!r}（{type(value).__name__}）{_YAML_HINT}")


def kebab(name: str) -> str:
    """內部 snake_case → 使用者寫的 kebab-case（訊息與 schema 用）。"""
    return name.replace("_", "-")


def from_yaml(data: Any) -> Any:
    """YAML 讀進來的結構：所有 mapping 的鍵由 kebab-case 換成 snake_case；值不動。"""
    if isinstance(data, Mapping):
        return {str(k).replace("-", "_"): from_yaml(v) for k, v in data.items()}
    if isinstance(data, list):
        return [from_yaml(v) for v in data]
    return data


def as_lines(body: Any) -> list[str]:
    """區塊內文的行：字串依換行拆開（略過空行），序列照原樣，空值是空串列。引擎與匯出器共用。"""
    if not body:
        return []
    if isinstance(body, str):
        return [s for s in body.split("\n") if s]
    return list(body)


def check_table(rows: Sequence[Sequence[Any]], col_w: Sequence[float]) -> None:
    """表格規格：至少一列、每列的欄數等於欄寬數、欄寬為正。"""
    if not rows:
        raise SpecError("表格沒有列")
    if any(not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0 for w in col_w):
        raise SpecError(f"col-w 須為正數：{list(col_w)}")
    for i, row in enumerate(rows):
        if len(row) != len(col_w):
            raise SpecError(f"表格第 {i + 1} 列有 {len(row)} 欄，但 col-w 有 {len(col_w)} 個欄寬")


# ---- 區塊欄位表 ----
# 每個區塊：req 必填、opt 選填、lists 是「欄位 → 該欄每個元素的欄位表」（可巢狀）、kinds 是值須為卡片 kind 的欄位、
# enums 是值須在名單內的欄位。`h`（固定高度，英吋）每個區塊都收。新增區塊要同時改這裡、blocks.py 與 outline.py。

_TXT = {"req": ("title",), "opt": ("kind", "body", "bullet"), "kinds": ("kind",)}  # 帶標題的卡片

BLOCK_SCHEMA: dict[str, dict[str, Any]] = {
    "banner": {"req": ("kind", "title"), "opt": ("body", "h", "tfs", "bfs"), "kinds": ("kind",)},
    "cards": {"req": ("items",), "opt": ("h", "bullet"), "lists": {"items": _TXT}},
    "flow": {
        "req": ("items",),
        "opt": ("h", "caption", "edge_labels", "numbered"),
        "lists": {"items": {"req": ("title",), "opt": ("kind", "body"), "kinds": ("kind",)}},
    },
    "swimlane": {
        "req": ("lanes", "steps"),
        "opt": ("thesis", "h"),
        "lists": {
            "lanes": {"req": ("name",), "opt": ("sub",)},
            "steps": {
                "req": ("lane", "title"),
                "opt": ("sub", "kind", "edge", "dash"),
                "kinds": ("kind",),
                "enums": {"edge": ("blocked", "green")},
            },
            "thesis": _TXT,
        },
    },
    "arch_graph": {
        "req": ("nodes",),
        "opt": ("edges", "zones", "col_headers", "side_thesis", "cols", "rows", "h"),
        "lists": {
            "nodes": {
                "req": ("id", "col", "row", "title"),
                "opt": ("kind", "sub", "en", "col_span", "row_span", "inset", "badge", "tfs", "bfs", "bullet"),
                "kinds": ("kind",),
            },
            "edges": {"req": ("from", "to"), "opt": ("kind", "label"), "enums": {"kind": EDGE_KINDS}},
            "zones": {
                "req": ("col", "row"),
                "opt": ("col_span", "row_span", "kind", "title", "sub"),
                "kinds": ("kind",),
            },
            "side_thesis": _TXT,
        },
    },
    "bench_chart": {
        "req": ("groups", "thesis"),
        "opt": ("h",),
        "lists": {
            "groups": {
                "req": ("title", "bars"),
                "lists": {
                    "bars": {"req": ("label", "ratio", "value"), "opt": ("kind",), "kinds": ("kind",)},
                },
            },
            "thesis": _TXT,
        },
    },
    "timeline_diagram": {
        "req": ("tracks",),
        "opt": ("h",),
        "lists": {
            "tracks": {
                "req": ("title", "phases"),
                "lists": {"phases": {"req": ("time", "title"), "opt": ("kind", "body", "bullet"), "kinds": ("kind",)}},
            },
        },
    },
    "table": {"req": ("rows", "col_w"), "opt": ("h", "highlight", "aligns")},
    "steps": {
        "req": ("items",),
        "opt": ("h",),
        "lists": {"items": {"req": ("title",), "opt": ("num", "body")}},
    },
    "columns": {
        "req": ("cols",),
        "opt": ("h",),
        "lists": {"cols": {"req": ("title",), "opt": ("kind", "items"), "kinds": ("kind",)}},
    },
    "shots": {
        "req": ("items",),
        "opt": ("side", "side_w", "cap_h", "figure", "h"),
        "lists": {
            "items": {"req": ("image", "title"), "opt": ("body", "crop", "alt")},
            "side": _TXT,
        },
    },
    "layers": {
        "req": ("tiers",),
        "opt": ("left_w", "h"),
        "lists": {
            "tiers": {
                "req": ("name", "title"),
                "opt": ("sub", "kind", "detail_kind", "body", "bullet"),
                "kinds": ("kind", "detail_kind"),
            },
        },
    },
    "kpi": {
        "req": ("items",),
        "opt": ("h",),
        "lists": {"items": {"req": ("value", "label"), "opt": ("kind", "sub"), "kinds": ("kind",)}},
    },
    "chart": {
        "req": ("categories", "series"),
        "opt": ("type", "title", "fmt", "legend", "labels", "vmin", "vmax", "side", "side_w", "h"),
        "enums": {"type": CHART_TYPES},
        "lists": {
            "series": {"req": ("name", "values"), "opt": ("kind",), "kinds": ("kind",)},
            "side": _TXT,
        },
    },
    "references": {"req": ("items",), "opt": ("title", "size", "h")},
    "note": {"req": ("lines",), "opt": ("size", "bold")},
}

TOP_REQUIRED = ("title", "subtitle", "category", "short_title", "slides")
TOP_OPTIONAL = ("author", "date", "lang", "output_file", "meta", "notes", "lint")
LINT_KEYS = ("deny", "allow")


def _names(keys: Sequence[str]) -> str:
    return "、".join(kebab(k) for k in keys)


def _keys(where: str, obj: Mapping[str, Any], req: Sequence[str], opt: Sequence[str]) -> None:
    if not isinstance(obj, Mapping):
        raise SpecError(f"{where}：須為對應表，拿到 {type(obj).__name__}")
    if missing := [k for k in req if k not in obj]:
        raise SpecError(f"{where}：缺必填欄位 {_names(missing)}")
    if unknown := [k for k in obj if k not in (*req, *opt)]:
        raise SpecError(f"{where}：未知欄位 {_names([str(k) for k in unknown])}（可用：{_names((*req, *opt))}）")


def _check(where: str, obj: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """依欄位表檢查一個物件（含巢狀的元素列表）。"""
    lists = schema.get("lists", {})
    _keys(where, obj, schema.get("req", ()), schema.get("opt", ()))
    for field, value in obj.items():
        if field not in lists:
            check_text(where, field, value)
    for field in schema.get("kinds", ()):
        if field in obj and obj[field] not in KINDS:
            raise SpecError(f"{where}：{kebab(field)}={obj[field]!r} 不是合法的 kind（可用：{', '.join(KINDS)}）")
    for field, allowed in schema.get("enums", {}).items():
        if field in obj and obj[field] not in allowed:
            raise SpecError(f"{where}：{kebab(field)}={obj[field]!r} 不合法（可用：{', '.join(allowed)}）")
    for field, item_schema in lists.items():
        if field not in obj:
            continue
        seq = obj[field]
        if isinstance(seq, (str, bytes)) or not isinstance(seq, Sequence):
            raise SpecError(f"{where}：{kebab(field)} 須為清單")
        if not seq and field in schema.get("req", ()):
            raise SpecError(f"{where}：{kebab(field)} 不可為空")
        for i, item in enumerate(seq):
            _check(f"{where}的 {kebab(field)}[{i + 1}]", item, item_schema)


def _check_table(where: str, kw: Mapping[str, Any]) -> None:
    try:
        check_table(kw["rows"], kw["col_w"])
    except SpecError as e:
        raise SpecError(f"{where}：{e}") from None
    for i, row in enumerate(kw["rows"]):
        for j, cell in enumerate(row):
            if isinstance(cell, list):
                if len(cell) != 2 or cell[1] not in KINDS:
                    raise SpecError(f"{where}：表格第 {i + 1} 列第 {j + 1} 欄的 [文字, kind] 不合法：{cell!r}")
            elif not isinstance(cell, str):
                raise SpecError(f"{where}：表格第 {i + 1} 列第 {j + 1} 欄須為字串或 [文字, kind]：{cell!r}")
    for a in kw.get("aligns") or ():
        if a not in ALIGNS:
            raise SpecError(f"{where}：aligns 只能是 {', '.join(ALIGNS)}：{a!r}")


def check_block(where: str, name: str, kw: Mapping[str, Any]) -> None:
    """檢查一個區塊（區塊名稱、必填與未知欄位、kind 名稱、表格形狀）。"""
    if name not in BLOCK_SCHEMA:
        raise SpecError(f"{where}：未知區塊 {kebab(name)}（可用：{', '.join(map(kebab, BLOCK_SCHEMA))}）")
    _check(f"{where}的 {kebab(name)} 區塊", kw, BLOCK_SCHEMA[name])
    if name == "table":
        _check_table(f"{where}的 table 區塊", kw)


def split_block(where: str, block: Any) -> tuple[str, dict[str, Any]]:
    """`{block: 名稱, ...欄位}` → (名稱, 欄位)。"""
    if not isinstance(block, Mapping) or not isinstance(block.get("block"), str):
        raise SpecError(f"{where}：區塊須寫成 {{block: 名稱, ...欄位}}：{block!r}")
    return block["block"].replace("-", "_"), {k: v for k, v in block.items() if k != "block"}


def slides_of(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把規格的頁面補齊成固定形狀：`type`、`ref`、`title`、`blocks`（已拆成 (名稱, 欄位)）、`sub`、`meta`、`notes`。"""
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(spec["slides"], 2):  # 封面是第 1 頁
        where = f"第 {i} 頁"
        if not isinstance(entry, Mapping):
            raise SpecError(f"{where}：須為對應表（鍵：type、ref、title、blocks…）：{entry!r}")
        kind = entry.get("type", "content")
        if kind not in PAGE_TYPES:
            raise SpecError(f"{where}：未知頁面類型 {kind!r}（可用：{', '.join(PAGE_TYPES)}）")
        page = PAGE_TYPES[kind]
        _keys(where, entry, page["req"], page["opt"])
        blocks = entry.get("blocks", [])
        if not isinstance(blocks, list):
            raise SpecError(f"{where}：blocks 須為清單")
        out.append(
            {
                "type": kind,
                "ref": "",
                "title": "",
                "sub": "",
                "meta": "",
                "notes": "",
                **entry,
                "blocks": [split_block(f"{where}「{entry.get('title', '')}」", b) for b in blocks],
            }
        )
    return out


def validate(spec: Mapping[str, Any]) -> None:
    """建置前檢查整份規格；第一個錯誤就丟 `SpecError`，訊息帶頁碼與區塊。

    規格須是分層合併後的結果（`config.resolve`）：作者可以寫在 `deck.yml`，也可以來自上層的 `_quarto.yml`／`_metadata.yml`。
    """
    if isinstance(spec, Mapping) and "author" not in spec:
        raise SpecError(
            "規格缺作者（author）：寫在 deck.yml，或放進上層的 _quarto.yml／_metadata.yml 並用 deckstyle build 分層合併"
        )
    _keys("規格", spec, TOP_REQUIRED, TOP_OPTIONAL)
    for field in ("title", "subtitle", "category", "short_title", "meta", "notes"):
        if field in spec:
            check_text("規格", field, spec[field])
    from .config import normalize_authors  # 延後匯入：config 也匯入本檔的 SpecError

    normalize_authors(spec["author"])
    if "lint" in spec:
        _keys("規格的 lint", spec["lint"], (), LINT_KEYS)
        for key in LINT_KEYS:
            names = spec["lint"].get(key, [])
            if not isinstance(names, list) or not all(isinstance(w, str) for w in names):
                raise SpecError(f"規格的 lint.{key}：須為字串清單")
    if not spec["slides"]:
        raise SpecError("規格沒有任何頁面（slides 是空的）")
    for n, page in enumerate(slides_of(spec), 2):
        where = f"第 {n} 頁「{page['title']}」"
        if not isinstance(page["title"], str) or not page["title"].strip():
            raise SpecError(f"第 {n} 頁：主標題不可空白，須為字串：{page['title']!r}")
        for field in ("ref", "sub", "meta", "notes"):
            check_text(where, field, page[field])
        if page["type"] != "content":
            continue
        if not page["blocks"]:
            raise SpecError(f"{where}：blocks 不可空")
        for name, kw in page["blocks"]:
            check_block(where, name, kw)
