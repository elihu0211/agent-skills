"""匯出 PDF：以 macOS 的 Microsoft PowerPoint 把 `.pptx` 轉成向量 PDF（內嵌字型，與投影所見一致）。

PowerPoint 開檔再另存是唯一能忠實呈現 PingFang TC 與圓角形狀的路徑；沒有 PowerPoint 的環境只能出 `.pptx`。
匯出失敗或逾時以 `ExportError` 停下，不是警告後繼續。多個行程同時匯出時以檔案鎖串行，不會互相關掉對方的文件。
"""

from __future__ import annotations

import fcntl
import subprocess
import tempfile
from pathlib import Path

EXPORT_TIMEOUT_S = 180  # 整個 AppleScript 的上限；PowerPoint 開檔的輪詢上限（20 秒）在腳本內

# 路徑與檔名以 argv 傳入，不拼進腳本字串（路徑含引號或空白也安全）。只關自己開的那份：
# 以檔名取得 presentation，使用者已開著的其他簡報不受影響。
_SCRIPT = """
on run argv
    set pptxFile to POSIX file (item 1 of argv)
    set pdfFile to POSIX file (item 2 of argv)
    set deckName to item 3 of argv
    tell application "Microsoft PowerPoint"
        open pptxFile
        repeat 40 times
            if exists presentation deckName then exit repeat
            delay 0.5
        end repeat
        if not (exists presentation deckName) then error "PowerPoint 20 秒內沒有開啟 " & deckName
        set deck to presentation deckName
        try
            save deck in pdfFile as save as PDF
        on error msg
            close deck saving no
            error msg
        end try
        close deck saving no
    end tell
end run
"""


class ExportError(RuntimeError):
    """PDF 匯出失敗；訊息說明原因與處置。"""


# PowerPoint 卡住時 AppleScript 常回的錯誤碼：-9074（儲存失敗）、-2700（AppleEvent 逾時）、
# -609（連線失效）、-1712（逾時）。實測這些失敗前，PowerPoint 的系統日誌都有儲存對話框
# （openAndSavePanelService）；恢復都發生在 PowerPoint 行程重啟之後。
_STUCK_CODES = ("-9074", "-2700", "-609", "-1712")


def _hint(stderr: str) -> str:
    """錯誤碼屬於「PowerPoint 卡住」一類時，附上處置；其餘錯誤原樣，不猜原因。"""
    if not any(f"({code})" in stderr or f" {code}" in stderr for code in _STUCK_CODES):
        return ""
    return (
        "\n處置：PowerPoint 可能停在儲存對話框或卡住了。切到 PowerPoint 關掉對話框與殘留開著的簡報；"
        "仍失敗就結束 PowerPoint（先存好自己的檔案）再重跑。"
    )


def export_pdf(pptx: Path, pdf: Path) -> None:
    """用 PowerPoint 匯出向量 PDF；失敗丟 `ExportError`。"""
    pdf.unlink(missing_ok=True)
    argv = [str(pptx.resolve()), str(pdf.resolve()), pptx.name]
    lock = Path(tempfile.gettempdir()) / "deckstyle-powerpoint-export.lock"
    try:
        with lock.open("w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            run = subprocess.run(
                ["osascript", "-", *argv],
                input=_SCRIPT,
                capture_output=True,
                text=True,
                timeout=EXPORT_TIMEOUT_S,
                check=False,
            )
    except FileNotFoundError:
        raise ExportError("PowerPoint 匯出 PDF 需要 macOS 的 osascript；沒有的環境只出 .pptx（不加 --pdf）。") from None
    except subprocess.TimeoutExpired:
        raise ExportError(
            f"PowerPoint 匯出 {pptx.name} 逾時（{EXPORT_TIMEOUT_S} 秒）：確認 PowerPoint 沒有卡在對話框，"
            "並關掉它殘留開著的這份簡報後重試。"
        ) from None
    if run.returncode != 0:
        stderr = run.stderr.strip()
        raise ExportError(
            f"PowerPoint 匯出 {pptx.name} 失敗（osascript 結束碼 {run.returncode}）：{stderr}{_hint(stderr)}"
        )
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise ExportError(f"PowerPoint 回報成功，但沒有產出 {pdf}。")
