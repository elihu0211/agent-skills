"""規格 → Markdown 大綱：簡報內容的純文字孿生，供 diff、審稿與全文檢索。

純標準庫、不依賴 python-pptx。內容與 PPTX 同源（都讀同一份規格），所以改規格後大綱跟著變；
PPTX 是二進位檔，審稿與 git diff 看這份。每個區塊輸出成一段 Markdown，講稿備註放在頁末的引言區塊。
新增區塊時在 `_block` 加一個分支；測試會檢查每個區塊都有對應輸出。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .config import format_author, normalize_authors
from .spec import SpecError, as_lines, slides_of, validate


def _cell(value: Any) -> str:
    text = value[0] if isinstance(value, list) else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(rows: Sequence[Sequence[Any]]) -> str:
    head, *body = rows
    out = ["| " + " | ".join(_cell(c) for c in head) + " |", "|" + " --- |" * len(head)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return "\n".join(out)


def _titled(items: Sequence[Mapping[str, Any]], body_key: str = "body") -> str:
    """一組「**標題**：說明」條列。"""
    out = []
    for it in items:
        body = "；".join(as_lines(it.get(body_key)))
        out.append(f"- **{it['title']}**" + (f"：{body}" if body else ""))
    return "\n".join(out)


def _block(kind: str, kw: Mapping[str, Any]) -> str:
    match kind:
        case "banner":
            body = "；".join(as_lines(kw.get("body")))
            return f"> **{kw['title']}**" + (f"：{body}" if body else "")
        case "cards" | "kpi" | "steps" | "layers" | "flow":
            return _list_block(kind, kw)
        case "columns":
            return "\n\n".join(
                f"**{c['title']}**\n" + "\n".join(f"- {t}" for t in as_lines(c.get("items"))) for c in kw["cols"]
            )
        case "table":
            return _table(kw["rows"])
        case "swimlane":
            lanes = [ln["name"] for ln in kw["lanes"]]
            rows = [["步驟", "泳道", "動作", "說明"]] + [
                [str(i + 1), lanes[s["lane"]], s["title"], "；".join(as_lines(s.get("sub")))]
                for i, s in enumerate(kw["steps"])
            ]
            out = [_table(rows)]
            if kw.get("thesis"):
                out.append(_titled(kw["thesis"]))
            return "\n\n".join(out)
        case "arch_graph":
            names = {n["id"]: n["title"] for n in kw["nodes"]}
            out = [_table([["節點", "說明"], *([n["title"], "；".join(as_lines(n.get("sub")))] for n in kw["nodes"])])]
            if kw.get("edges"):
                out.append(
                    "\n".join(
                        f"- {names.get(e['from'], e['from'])} → {names.get(e['to'], e['to'])}"
                        + (f"（{e['label']}）" if e.get("label") else "")
                        for e in kw["edges"]
                    )
                )
            if kw.get("side_thesis"):
                out.append(_titled(kw["side_thesis"]))
            return "\n\n".join(out)
        case "bench_chart":
            out = []
            for g in kw["groups"]:
                out.append(_table([[g["title"], "數值"], *([b["label"], b["value"]] for b in g["bars"])]))
            out.append(_titled(kw["thesis"]))
            return "\n\n".join(out)
        case "timeline_diagram":
            out = []
            for t in kw["tracks"]:
                rows = [
                    ["時序", "階段", "內容"],
                    *([p["time"], p["title"], "；".join(as_lines(p.get("body")))] for p in t["phases"]),
                ]
                out.append(f"**{t['title']}**\n\n" + _table(rows))
            return "\n\n".join(out)
        case "shots":
            out = [
                "\n".join(
                    f"- 畫面：**{it['title']}**" + (f"　{it['body']}" if it.get("body") else "") + f"（{it['image']}）"
                    for it in kw["items"]
                )
            ]
            if kw.get("side"):
                out.append(_titled(kw["side"]))
            return "\n\n".join(out)
        case "chart":
            rows = [["", *(s["name"] for s in kw["series"])]] + [
                [c, *(str(s["values"][i]) for s in kw["series"])] for i, c in enumerate(kw["categories"])
            ]
            out = ([f"**{kw['title']}**"] if kw.get("title") else []) + [_table(rows)]
            if kw.get("side"):
                out.append(_titled(kw["side"]))
            return "\n\n".join(out)
        case "references":
            head = [f"**{kw['title']}**"] if kw.get("title") else []
            return "\n\n".join([*head, "\n".join(f"- {r}" for r in as_lines(kw["items"]))])
        case "note":
            return "_" + "".join(kw["lines"]) + "_"
    raise SpecError(f"簡報規格含未知區塊：{kind}")


def _list_block(kind: str, kw: Mapping[str, Any]) -> str:
    if kind == "kpi":
        return "\n".join(
            f"- **{it['value']}**　{it['label']}" + (f"：{'；'.join(as_lines(it.get('sub')))}" if it.get("sub") else "")
            for it in kw["items"]
        )
    if kind == "steps":
        return "\n".join(
            f"{i}. **{it['title']}**" + (f"：{'；'.join(as_lines(it.get('body')))}" if it.get("body") else "")
            for i, it in enumerate(kw["items"], 1)
        )
    if kind == "layers":
        rows = [
            ["層", "名稱", "對應"],
            *(
                [
                    t["name"] + (f"（{t['sub']}）" if t.get("sub") else ""),
                    t["title"],
                    "；".join(as_lines(t.get("body"))),
                ]
                for t in kw["tiers"]
            ),
        ]
        return _table(rows)
    head = f"**{kw['caption']}**\n\n" if kw.get("caption") else ""
    return head + _titled(kw["items"])


def export(spec: Mapping[str, Any]) -> str:
    """回傳完整的 Markdown 大綱（先驗證規格）。"""
    validate(spec)
    out = [f"# {str(spec['title']).replace(chr(10), '')}", "", f"{spec['subtitle']}", ""]
    meta = [f"作者：{format_author(normalize_authors(spec['author']))}"]
    meta += [f"{k}：{spec[k]}" for k in ("date",) if spec.get(k)]
    out += ["　".join(meta), ""]
    if spec.get("notes"):
        out += [f"> 講稿：{spec['notes']}", ""]
    for page in slides_of(spec):
        label = f"{page['ref']}　" if page["ref"] else ""
        out += [f"## {label}{page['title']}", ""]
        if page["type"] == "divider" and page["sub"]:
            out += [page["sub"], ""]
        if page["type"] == "closing":
            out += [x for x in (page["sub"], page["meta"]) if x] + [""]
        for kind, kw in page["blocks"]:
            out += [_block(kind, kw), ""]
        if page["notes"]:
            out += [f"> 講稿：{page['notes']}".replace("\n", "\n> "), ""]
    return "\n".join(out).rstrip() + "\n"
