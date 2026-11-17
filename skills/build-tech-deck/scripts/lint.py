# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2", "pyyaml>=6", "lxml>=5", "pillow>=10"]
# ///
"""檢查簡報的零折行與白話命名：讀任何 .pptx（不限範本引擎建的）。

用法：uv run lint.py deck.pptx [更多.pptx] [--deny 倉庫名,服務代號] [--allow 詞,詞] [--safety 0.8] [--no-notes] [--json]
結束碼：0 通過；1 有違規；2 用法錯誤或檔案不存在。

- 零折行：估算每段文字寬度（全形 1.0 em、半形 0.55 em、粗體多估 5%，再乘安全係數），找出折行、孤字與單行過長；
  佔位符沒指定的字級與粗細沿版面、母片解析；明確換行（標題、表格儲存格與文字框裡的 `\n`）各行分開估寬。
- 白話命名：投影片與講稿備註不得出現 snake_case 識別字、檔名、路徑與端點；專案專屬的倉庫與服務代號用 --deny 帶入。

同一份實作在範本引擎（assets/deck-template 的 `deckstyle lint`）；這支只是不必安裝引擎就能跑的入口。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "deck-template"))

from deckstyle.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["lint", *sys.argv[1:]]))
