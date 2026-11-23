# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""檢查 Markdown／Quarto 文件內的 Mermaid 區塊是否符合深／淺色自動切換規範。

用法：
    uv run scripts/lint_mermaid.py docs/
    uv run scripts/lint_mermaid.py docs/architecture.md --json
    uv run scripts/lint_mermaid.py docs/ --check-mmdc
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "_output", "__pycache__", ".pytest_cache"}
DOC_SUFFIXES = {".md", ".qmd"}

FENCE_OPEN = re.compile(r"^(`{3,})mermaid\s*$")
LEGACY_INIT = re.compile(r"%%\{\s*init\s*:", re.I)
HARDCODED_THEME = re.compile(r"^\s*(theme|themeVariables)\s*:", re.M)
SUBGRAPH_DECL = re.compile(r"^\s*subgraph\s+([\w-]+)\b", re.MULTILINE)
STYLE_LINE = re.compile(r"^\s*(style|classDef)\s+([\w-]+)\s+(.+)$", re.MULTILINE)
FILL_PROP = re.compile(r"\bfill\s*:\s*([^,\s;]+)", re.I)
COLOR_PROP = re.compile(r"(?<![a-z-])color\s*:\s*([^,\s;]+)", re.I)
SEQ_RECT = re.compile(r"^\s*rect\s+(?:rgb|rgba)\s*\(", re.I | re.M)


@dataclass
class Issue:
    file: str
    line: int
    rule: str
    message: str


def extract_blocks(path: Path) -> list[tuple[int, str]]:
    """回傳 [(起始行號 1-based, 區塊內容), ...]。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        m = FENCE_OPEN.match(lines[i])
        if not m:
            i += 1
            continue
        ticks = m.group(1)
        close_re = re.compile(rf"^{re.escape(ticks)}\s*$")
        start_line = i + 1
        buf: list[str] = []
        i += 1
        while i < len(lines) and not close_re.match(lines[i]):
            buf.append(lines[i])
            i += 1
        blocks.append((start_line, "\n".join(buf)))
        i += 1
    return blocks


def parse_frontmatter(block: str) -> str:
    if not block.startswith("---\n"):
        return ""
    head, sep, _ = block[4:].partition("\n---\n")
    return head if sep else ""


def lint_block(rel_file: str, start_line: int, block: str) -> list[Issue]:
    issues: list[Issue] = []

    if LEGACY_INIT.search(block):
        issues.append(
            Issue(
                file=rel_file,
                line=start_line,
                rule="legacy-init",
                message="改用 YAML frontmatter（--- config: ... ---）取代舊版 %%{init:...}%%",
            )
        )

    fm = parse_frontmatter(block)
    if fm and HARDCODED_THEME.search(fm):
        issues.append(
            Issue(
                file=rel_file,
                line=start_line,
                rule="hardcoded-theme",
                message="移除 frontmatter 的 theme／themeVariables，保留閱讀器深／淺色自動切換",
            )
        )

    transparent_targets: set[str] = set()
    for m in STYLE_LINE.finditer(block):
        kind, target, props = m.group(1), m.group(2), m.group(3)
        fill_m = FILL_PROP.search(props)
        if fill_m:
            val = fill_m.group(1).lower()
            if val in {"transparent", "none"}:
                if kind == "style":
                    transparent_targets.add(target)
            else:
                issues.append(
                    Issue(
                        file=rel_file,
                        line=start_line,
                        rule="hardcoded-color",
                        message=f"{kind} {target} 不可寫死 fill:{fill_m.group(1)}（請用 fill:transparent 搭配語意 stroke）",
                    )
                )
        color_m = COLOR_PROP.search(props)
        if color_m:
            issues.append(
                Issue(
                    file=rel_file,
                    line=start_line,
                    rule="hardcoded-color",
                    message=f"{kind} {target} 不可寫死字色 color:{color_m.group(1)}（交由宿主深／淺色主題決定）",
                )
            )

    for sg in SUBGRAPH_DECL.finditer(block):
        sg_id = sg.group(1)
        if sg_id not in transparent_targets:
            issues.append(
                Issue(
                    file=rel_file,
                    line=start_line,
                    rule="subgraph-fill",
                    message=f"subgraph {sg_id} 缺少 style {sg_id} fill:transparent,stroke:<語意色>,stroke-width:1.5px",
                )
            )

    if "sequenceDiagram" in block and SEQ_RECT.search(block):
        issues.append(
            Issue(
                file=rel_file,
                line=start_line,
                rule="sequence-rect",
                message="sequenceDiagram 避免使用 rect rgb(...) 色塊（暗黑模式會產生破碎色塊），改用 autonumber 與原生 alt／else",
            )
        )

    return issues


def check_mmdc(rel_file: str, start_line: int, block: str) -> list[Issue]:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "diagram.mmd"
        out = Path(tmp) / "diagram.svg"
        src.write_text(block, encoding="utf-8")
        proc = subprocess.run(
            ["mmdc", "-i", str(src), "-o", str(out)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip().splitlines()[:3]
            return [
                Issue(
                    file=rel_file,
                    line=start_line,
                    rule="mmdc-syntax",
                    message="mmdc 渲染失敗：" + " | ".join(err),
                )
            ]
    return []


def collect_files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        if p.is_file():
            if p.suffix.lower() in DOC_SUFFIXES:
                found.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if any(part in SKIP_DIRS for part in child.parts):
                    continue
                if child.is_file() and child.suffix.lower() in DOC_SUFFIXES:
                    found.append(child)
        else:
            print(f"錯誤：找不到路徑 {p}", file=sys.stderr)
            sys.exit(2)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description="檢查 Markdown／Quarto 文件中的 Mermaid 圖表是否符合深／淺色主題自動切換規範。"
    )
    parser.add_argument("paths", nargs="+", type=Path, help="要檢查的檔案或目錄")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 格式輸出結果")
    parser.add_argument("--check-mmdc", action="store_true", help="額外呼叫 mmdc 檢查 Mermaid 語法")
    args = parser.parse_args()

    if args.check_mmdc and not shutil.which("mmdc"):
        print("錯誤：找不到 mmdc 指令，請先安裝 @mermaid-js/mermaid-cli 或移除 --check-mmdc", file=sys.stderr)
        return 2

    files = collect_files(args.paths)
    all_issues: list[Issue] = []
    block_count = 0

    for f in files:
        blocks = extract_blocks(f)
        block_count += len(blocks)
        for start_line, block in blocks:
            all_issues.extend(lint_block(str(f), start_line, block))
            if args.check_mmdc:
                all_issues.extend(check_mmdc(str(f), start_line, block))

    if args.as_json:
        payload = {
            "files_checked": len(files),
            "blocks_checked": block_count,
            "issue_count": len(all_issues),
            "issues": [asdict(i) for i in all_issues],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for i in all_issues:
            print(f"{i.file}:{i.line}: [{i.rule}] {i.message}")
        status = "OK" if not all_issues else "FAIL"
        print(f"{status}: 檢查 {len(files)} 檔、{block_count} 個 Mermaid 區塊，發現 {len(all_issues)} 個問題")

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
