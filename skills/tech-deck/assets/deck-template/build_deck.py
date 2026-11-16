# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2"]
# ///
"""建置簡報：uv run build_deck.py [輸出.pptx]。建好後先跑 lint_wrap.py，再轉 PDF／圖片逐頁看。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deck_engine import build  # noqa: E402
from deck_spec import SLIDES  # noqa: E402

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "deck.pptx"
    build(SLIDES, out)
    print(out)
