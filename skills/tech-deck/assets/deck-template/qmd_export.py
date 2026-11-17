"""由宣告式規格產出 `index.qmd`（供文件庫的檢查工具比對禁用字元、標點、連結與書目；單獨使用簡報時可略過）。

純標準庫、不依賴 python-pptx：檢查工具在沒有簡報相依套件的環境也要能比對。內容與 PPTX 逐字同源。

檢查工具以檔案路徑單獨載入本檔（不經 sys.path），所以引擎與匯出器共用的規格層工具
（`as_lines`、`SpecError`、`check_table`）放在這裡，確保兩邊讀同一份規格得到同一個結果。
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_TAG = re.compile(r"[\w-]+")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


class SpecError(ValueError):
    """簡報規格有誤；訊息說明哪裡錯、該怎麼改。"""


DEFAULTS = Path(__file__).with_name("defaults.toml")


def author_of(spec: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> str:
    """封面與 front matter 的作者：規格有寫就用規格的（空字串＝沒有），沒寫用 `defaults.toml`。

    引擎與匯出器都經這一處，兩邊讀到同一個作者。`defaults` 只給測試注入。
    """
    if "author" not in spec:
        if defaults is None:
            with DEFAULTS.open("rb") as f:
                defaults = tomllib.load(f)
        value = defaults.get("author", "")
    else:
        value = spec["author"]
    if not isinstance(value, str):
        raise SpecError(f"作者欄要是字串（空字串代表沒有）：{value!r}")
    return value


def _tex(text: str) -> str:
    """raw LaTeX 儲存格：跳脫特殊字元，`**粗體**` 轉 `\\textbf`。"""
    parts = _BOLD.split(text)
    out: list[str] = []
    for i, part in enumerate(parts):
        esc = "".join(_TEX_SPECIAL.get(c, c) for c in part)
        out.append(rf"\textbf{{{esc}}}" if i % 2 else esc)
    return "".join(out)


def as_lines(body: Any) -> list[str]:
    """區塊內文的行：字串依換行拆開（略過空行），序列照原樣，空值是空串列。PPTX 與 qmd 共用。"""
    if not body:
        return []
    if isinstance(body, str):
        return [s for s in body.split("\n") if s]
    return list(body)


def check_table(rows: Sequence[Sequence[Any]], col_w: Sequence[float]) -> None:
    """表格規格：至少一列、每列的欄數等於欄寬數。"""
    if not rows:
        raise SpecError("表格沒有列")
    for i, row in enumerate(rows):
        if len(row) != len(col_w):
            raise SpecError(f"表格第 {i + 1} 列有 {len(row)} 欄，但 col_w 有 {len(col_w)} 個欄寬")


def _scalar(value: str) -> str:
    """YAML 純量：JSON 字串是合法的 YAML 雙引號純量，引號、反斜線與控制字元由 json.dumps 跳脫。"""
    return json.dumps(value, ensure_ascii=False)


def _one_line(value: str) -> str:
    return value.replace("\n", "")


def _front_matter(spec: dict[str, Any], defaults: Mapping[str, Any] | None) -> str:
    cover = spec["cover"]
    bad = [t for t in spec["tags"] if not _TAG.fullmatch(t)]
    if bad:
        raise SpecError(f"標籤只能含字母、數字、底線與連字號：{bad}")
    tags = "\n".join(f"  - {t}" for t in spec["tags"])
    author = author_of(spec, defaults)
    fields = [
        f"title: {_scalar(_one_line(cover['title']))}",
        f"subtitle: {_scalar(_one_line(cover['subtitle']))}",
        *([f"author: {_scalar(author)}"] if author else []),
        f"date: {_scalar(spec['date'])}",
        'type: "slides"',
        f"output-file: {_scalar(spec['output_file'])}",
        f"shorttitle: {_scalar(spec['short_title'])}",
        'category: "slides"',
        f"status: {_scalar(spec['status'])}",
        f"updated: {_scalar(spec['date'])}",
        f"version: {_scalar(spec['version'])}",
        f"tags:\n{tags}",
    ]
    return "---\n" + "\n".join(fields) + "\n---\n"


def _columns(cols: Sequence[tuple[str, Sequence[str]]]) -> str:
    width = (94 // len(cols)) if len(cols) > 2 else 47
    out = ["::: columns", ""]
    for title, items in cols:
        out += [f':::: {{.column width="{width}%"}}', f"**{title}**", ""]
        out += [f"- {t}" for t in items]
        out += ["::::", ""]
    out.append(":::")
    return "\n".join(out)


def _table(rows: Sequence[Sequence[Any]], col_w: Sequence[float]) -> str:
    check_table(rows, col_w)
    rows = [[c[0] if isinstance(c, tuple) else c for c in row] for row in rows]  # (字串, kind) 取字串
    n = len(col_w)
    mean = sum(col_w) / n
    spec = " ".join(
        rf">{{\hsize={w / mean:.2f}\hsize\raggedright\arraybackslash}}X" for w in col_w
    )
    body = [r"\toprule", " & ".join(rf"\textbf{{{_tex(c)}}}" for c in rows[0]) + r" \\", r"\midrule"]
    for i, row in enumerate(rows[1:]):
        if i:
            body.append(r"\addlinespace")
        body.append(" & ".join(_tex(c) for c in row) + r" \\")
    body.append(r"\bottomrule")
    return "\n".join(
        ["```{=latex}", r"\footnotesize", rf"\begin{{tabularx}}{{\linewidth}}{{{spec}}}", *body,
         r"\end{tabularx}", "```"]
    )


def _steps(items: Sequence[dict[str, Any]]) -> str:
    rows = [["活動", "重點"]]
    for i, it in enumerate(items):
        body = as_lines(it.get("body"))
        rows.append([f"{it.get('num', i + 1)}　{it['title']}", "；".join(body)])
    return _table(rows, [3.0, 8.7])


def _block(kind: str, kw: dict[str, Any]) -> str:
    if kind == "banner":
        body_list = as_lines(kw.get("body"))
        suffix = ("：" + "；".join(body_list)) if body_list else ""
        return f"**{kw['title']}**{suffix}"
    if kind == "cards":
        return _columns([(c["title"], as_lines(c.get("body"))) for c in kw["items"]])
    if kind == "flow":
        out = []
        if kw.get("caption"):
            out.append(f"**{kw['caption']}**\n")
        out.append(_columns([(c["title"], as_lines(c.get("body"))) for c in kw["items"]]))
        return "\n".join(out)
    if kind == "swimlane":
        out = []
        lane_names = [ln["name"] + (f"（{ln['sub']}）" if ln.get("sub") else "") for ln in kw["lanes"]]
        rows = [["步驟", "泳道", "動作", "說明"]]
        for i, st in enumerate(kw["steps"]):
            rows.append([
                str(i + 1),
                lane_names[st["lane"]],
                st["title"],
                "；".join(as_lines(st.get("sub"))),
            ])
        out.append(_table(rows, [1.2, 2.6, 3.0, 4.9]))
        if kw.get("thesis"):
            out.append("")
            out.append(_columns([(c["title"], as_lines(c.get("body"))) for c in kw["thesis"]]))
        return "\n".join(out)
    if kind == "arch_graph":
        out = []
        rows = [["節點", "說明"]]
        for nd in kw["nodes"]:
            rows.append([nd["title"], "；".join(as_lines(nd.get("sub")))])
        out.append(_table(rows, [3.8, 7.9]))
        if kw.get("side_thesis"):
            out.append("")
            out.append(_columns([(c["title"], as_lines(c.get("body"))) for c in kw["side_thesis"]]))
        return "\n".join(out)
    if kind == "bench_chart":
        out = []
        for grp in kw["groups"]:
            rows = [[grp["title"], "實測數值"]]
            for b in grp["bars"]:
                rows.append([b["label"], b["value"]])
            out.append(_table(rows, [4.5, 7.2]))
            out.append("")
        out.append(_columns([(c["title"], as_lines(c.get("body"))) for c in kw["thesis"]]))
        return "\n".join(out)
    if kind == "timeline_diagram":
        out = []
        for tr in kw["tracks"]:
            out.append(f"**{tr['title']}**\n")
            rows = [["時序／波次", "階段", "內容"]]
            for ph in tr["phases"]:
                rows.append([ph["time"], ph["title"], "；".join(as_lines(ph.get("body")))])
            out.append(_table(rows, [2.5, 3.2, 6.0]))
            out.append("")
        return "\n".join(out).rstrip()
    if kind == "columns":
        return _columns([(c["title"], as_lines(c.get("items"))) for c in kw["cols"]])
    if kind == "steps":
        return _steps(kw["items"])
    if kind == "table":
        return _table(kw["rows"], kw["col_w"])
    if kind == "shots":
        out = [_columns([(it["title"], as_lines(it.get("body"))) for it in kw["items"]])]
        if kw.get("side"):
            out += ["", _columns([(c["title"], as_lines(c.get("body"))) for c in kw["side"]])]
        return "\n".join(out)
    if kind == "layers":
        rows = [["層", "名稱", "對應"]]
        for t in kw["tiers"]:
            rows.append([t["name"] + (f"（{t['sub']}）" if t.get("sub") else ""), t["title"], "；".join(as_lines(t.get("body")))])
        return _table(rows, [2.6, 3.2, 5.9])
    if kind == "note":
        return r"\small " + "".join(kw["lines"])
    raise SpecError(f"簡報規格含未知區塊：{kind}")


def export(spec: dict[str, Any], defaults: Mapping[str, Any] | None = None) -> str:
    """回傳完整 `index.qmd` 文字。"""
    out = [_front_matter(spec, defaults)]
    for _ref, title, blocks, *extra in spec["slides"]:
        out.append(f"## {title}\n")
        out += [_block(k, kw) + "\n" for k, kw in blocks]
        if extra and extra[0]:
            out.append(f"::: notes\n{extra[0]}\n:::\n")
    return "\n".join(out)
