#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Claude Code 的 PostToolUse hook（matcher: Edit|Write|MultiEdit）：改到含 tikzpicture 的 .qmd／.tex 就只檢查那個檔。

從 stdin 讀 hook 的 JSON，取 tool_input.file_path。不是 .qmd／.tex、檔案不存在或不含 \\begin{tikzpicture} 就直接放行。
否則以 uv 執行同目錄的 check.py --json：
  圖有壓疊（check.py 結束碼 1）  → 問題印到 stderr、結束碼 2，Claude Code 會把它回饋給 agent
  執行環境問題（找不到 uv、quarto、TeX，或逾時） → stdout 印 {"systemMessage": …} 警告使用者、結束碼 0，不擋編輯
  通過                         → 什麼都不印、結束碼 0
`--` 之後的參數原樣交給 check.py（例如 -- --mode latex --preamble tex/preamble.tex --max-width 16cm）。

設定（.claude/settings.json）：
  {"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command",
    "command": "uv run \\"$CLAUDE_PROJECT_DIR\\"/.agents/skills/guard-tikz-figures/scripts/hook.py", "timeout": 600}]}]}}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES_DOC = HERE.parent / "references" / "rules.md"


def warn(message: str) -> int:
    print(json.dumps({"systemMessage": f"TikZ 圖版面守門沒有執行（不擋編輯）：{message}"}, ensure_ascii=False))
    return 0


def target(payload: dict) -> Path | None:
    """hook 輸入裡被改的檔案；不是要檢查的檔就回傳 None。"""
    raw = (payload.get("tool_input") or {}).get("file_path")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    if path.suffix not in (".qmd", ".tex") or not path.is_file():
        return None
    try:
        if "\\begin{tikzpicture}" not in path.read_text(encoding="utf-8", errors="ignore"):
            return None
    except OSError:
        return None
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    own, extra = (argv[: argv.index("--")], argv[argv.index("--") + 1 :]) if "--" in argv else (argv, [])
    ap = argparse.ArgumentParser(
        description="Claude Code PostToolUse hook：被改的 .qmd／.tex 含 tikzpicture 時，只檢查該檔的圖。",
        epilog="結束碼：0 通過或無法檢查（以 systemMessage 警告）｜2 圖有壓疊（stderr 回饋給 agent）。"
               "`--` 之後的參數交給 check.py。")
    ap.add_argument("--limit", type=int, default=20, help="最多回饋幾個問題（預設 20）")
    ap.add_argument("--timeout", type=int, default=540, help="整個檢查的時限秒數（預設 540，要小於 hook 的 timeout）")
    args = ap.parse_args(own)

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return warn("stdin 不是 hook 的 JSON")
    path = target(payload if isinstance(payload, dict) else {})
    if path is None:
        return 0
    uv = shutil.which("uv")
    if not uv:
        return warn("找不到 uv（https://docs.astral.sh/uv/）")
    cmd = [uv, "run", "--quiet", "--script", str(HERE / "check.py"), str(path), "--json",
           "--limit", str(args.limit), *extra]
    try:
        done = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return warn(f"檢查超過 {args.timeout} 秒")
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    except ValueError:
        report = {}
    if done.returncode == 0:
        return 0
    if done.returncode != 1 or not report.get("issues"):
        reason = report.get("error") or (done.stderr.strip().splitlines() or ["check.py 沒有輸出"])[-1]
        return warn(reason)

    issues = report["issues"]
    lines = [f"TikZ 圖版面守門：{path.name} 有 {len(issues) + report.get('omitted', 0)} 個壓疊問題，改好再繼續。"]
    for i in issues:
        tag = f" {i['label']}" if i.get("label") else ""
        lines.append(f"- 第 {i['line']} 行{tag} [{i['rule']}] {i['message']}")
    if report.get("omitted"):
        lines.append(f"- …另有 {report['omitted']} 個")
    lines.append(f"每種問題的修法：{RULES_DOC}")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
