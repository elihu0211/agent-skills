# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2"]
# ///
"""白話命名檢查：投影片與講稿備註不得出現讀者看不懂的代碼名稱。

用法：uv run lint_names.py deck.pptx [--deny 詞1,詞2] [--allow 詞1,詞2] [--no-notes] [--json]
結束碼：0 無違規；1 有違規；2 用法錯誤。

內建擋的樣式（通用）：snake_case 識別字、檔案名（*.py、*.yml、*.toml、*.sql…）、以斜線起頭的路徑與端點（/ui、/v2/items）。
專案專屬的倉庫名稱與服務代號用 --deny 指定（以字界比對、區分大小寫），例如 --deny shop-api,billing。
標準與通用工具名（ISO/IEC 17788、PostgreSQL、Kubernetes）是讀者查得到的名稱，不在內建樣式內；誤報用 --allow 放行。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pptx import Presentation

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("識別字（snake_case）", re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")),
    ("檔案名", re.compile(r"(?<![A-Za-z0-9_-])[\w-]+\.(?:py|toml|ya?ml|sql|env|sh|json|md)(?![A-Za-z0-9_])")),
    ("路徑或端點", re.compile(r"(?<![A-Za-z0-9_)）/])/[a-z][a-z0-9_-]*(?:/[A-Za-z0-9_{}.-]+)*")),
)


def scan(text: str, deny: list[str], allow: set[str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for label, pat in RULES:
        hits += [(label, m.group(0)) for m in pat.finditer(text)]
    for word in deny:
        pat = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(word) + r"(?![A-Za-z0-9_-])")
        hits += [("倉庫或服務代號", m.group(0)) for m in pat.finditer(text)]
    return [(label, hit) for label, hit in hits if hit not in allow]


def _texts(prs: Presentation, notes: bool):
    for no, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame:
                yield no, "投影片", shape.text_frame.text
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        yield no, "表格", cell.text_frame.text
        if notes and slide.has_notes_slide:
            yield no, "講稿備註", slide.notes_slide.notes_text_frame.text


def lint(path: str, deny: list[str], allow: set[str], notes: bool = True) -> list[dict]:
    prs = Presentation(path)
    out: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    for no, where, text in _texts(prs, notes):
        for label, hit in scan(text, deny, allow):
            if (no, label, hit) in seen:
                continue
            seen.add((no, label, hit))
            out.append({"slide": no, "where": where, "type": label, "text": hit})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", help="要檢查的 .pptx")
    ap.add_argument("--deny", default="", help="額外禁用的倉庫名稱與服務代號，逗號分隔")
    ap.add_argument("--allow", default="", help="放行的字串，逗號分隔")
    ap.add_argument("--no-notes", action="store_true", help="不檢查講稿備註")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出違規清單")
    args = ap.parse_args()
    if not Path(args.pptx).is_file():
        print(f"找不到檔案：{args.pptx}", file=sys.stderr)
        return 2
    deny = [w for w in args.deny.split(",") if w]
    allow = {w for w in args.allow.split(",") if w}
    issues = lint(args.pptx, deny, allow, notes=not args.no_notes)
    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        for i in issues:
            print(f"第 {i['slide']} 頁 {i['where']}：{i['type']}「{i['text']}」，改成白話的功能名稱")
        print(f"{'違規 ' + str(len(issues)) + ' 處' if issues else '未發現倉庫或代碼名稱'}", file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
