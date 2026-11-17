"""預覽：把建好的簡報轉成逐頁 PNG 與接觸表，並在來源變動時自動重建（類似 `quarto preview`）。

PDF 由 PowerPoint 匯出（`export.py`），轉圖用 poppler 的 `pdftoppm`（`brew install poppler`）。
這是寫規格時「改一下就看一眼」的回饋迴路；lint 只是估算，交付前仍要逐頁目視。
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image


class PreviewError(RuntimeError):
    """預覽失敗；訊息說明原因與處置。"""


def render_pages(pdf: Path, out_dir: Path, dpi: int = 72) -> list[Path]:
    """PDF → `slide-01.png`…；回傳依頁序排列的路徑。"""
    exe = shutil.which("pdftoppm")
    if exe is None:
        raise PreviewError("找不到 pdftoppm：請先安裝 poppler（brew install poppler）。")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("slide-*.png"):
        old.unlink()
    run = subprocess.run(
        [exe, "-r", str(dpi), "-png", str(pdf), str(out_dir / "slide")], capture_output=True, text=True, check=False
    )
    if run.returncode != 0:
        raise PreviewError(f"pdftoppm 失敗（結束碼 {run.returncode}）：{run.stderr.strip()}")
    pages = sorted(out_dir.glob("slide-*.png"))
    if not pages:
        raise PreviewError(f"pdftoppm 沒有產出任何頁面：{pdf}")
    return pages


def contact_sheets(pages: list[Path], out_dir: Path, per_sheet: int = 6, cols: int = 2, gap: int = 10) -> list[Path]:
    """把頁面拼成接觸表（每張 per_sheet 頁、cols 欄），方便一次掃過一批頁面。"""
    for old in out_dir.glob("sheet-*.png"):
        old.unlink()
    sheets: list[Path] = []
    for start in range(0, len(pages), per_sheet):
        chunk = [Image.open(p).convert("RGB") for p in pages[start : start + per_sheet]]
        w, h = chunk[0].size
        rows = (len(chunk) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * w + gap * (cols + 1), rows * h + gap * (rows + 1)), (200, 200, 200))
        for i, im in enumerate(chunk):
            canvas.paste(im, (gap + (i % cols) * (w + gap), gap + (i // cols) * (h + gap)))
        path = out_dir / f"sheet-{start // per_sheet + 1}.png"
        canvas.save(path)
        sheets.append(path)
    return sheets


def snapshot(files: Iterable[Path]) -> dict[Path, float]:
    """檔案 → 修改時間；不存在的檔案不列入。"""
    return {f: f.stat().st_mtime for f in files if f.is_file()}


def watch(
    build: Callable[[], None],
    files: Callable[[], Iterable[Path]],
    interval: float = 0.5,
    max_rebuilds: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """先建一次，之後每當 `files()` 列的檔案有變就重建；回傳重建次數。

    `build` 丟出的錯誤由呼叫端在 `build` 內處理（印出後繼續監看）。`max_rebuilds` 給測試用，None 表示直到中斷。
    `files` 每輪重新取，所以新增的圖片與分層設定檔也會被監看。
    """
    build()
    seen = snapshot(files())
    rebuilds = 0
    while max_rebuilds is None or rebuilds < max_rebuilds:
        sleep(interval)
        now = snapshot(files())
        if now != seen:
            seen = now
            build()
            rebuilds += 1
    return rebuilds
