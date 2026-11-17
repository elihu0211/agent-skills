# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2", "pillow"]
# ///
"""建置簡報：uv run build_deck.py [輸出.pptx] [--pdf]。

建好後先跑 lint_wrap.py 與 lint_names.py，再轉 PDF／圖片逐頁看。`--pdf` 在 macOS 以 PowerPoint 匯出向量 PDF
（同名 .pdf）；匯出前會關閉已開啟的簡報，所以以檔案鎖串行，多個行程同時建置也不會互相關掉對方的文件。
"""
from __future__ import annotations

import argparse
import fcntl
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from deck_engine import render  # noqa: E402
from deck_spec import SPEC  # noqa: E402


def export_pdf(pptx: Path, pdf: Path) -> bool:
    script = f'''
    tell application "Microsoft PowerPoint"
        close every presentation saving no
        open POSIX file "{pptx.resolve()}"
        delay 3
        save active presentation in POSIX file "{pdf.resolve()}" as save as PDF
        close active presentation saving no
    end tell
    '''
    lock = Path(tempfile.gettempdir()) / "tech-deck-powerpoint-export.lock"
    try:
        with open(lock, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            pdf.unlink(missing_ok=True)
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
        return pdf.exists() and pdf.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001
        print(f"PowerPoint 匯出 PDF 失敗：{exc}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default="deck.pptx", help="輸出的 .pptx（預設 deck.pptx）")
    ap.add_argument("--pdf", action="store_true", help="另以 PowerPoint 匯出同名 PDF（僅 macOS）")
    args = ap.parse_args()
    deck = render(SPEC, HERE)
    deck.save(args.out)
    print(f"{args.out}（{deck.n} 頁）")
    if args.pdf:
        pdf = Path(args.out).with_suffix(".pdf")
        if not export_pdf(Path(args.out), pdf):
            return 2
        print(pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
