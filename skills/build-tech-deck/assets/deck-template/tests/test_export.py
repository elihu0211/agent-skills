"""PDF 匯出的錯誤訊息：PowerPoint 卡住類的錯誤碼附處置，其餘錯誤原樣。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from deckstyle import export


def _fail_with(monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)

    monkeypatch.setattr(export.subprocess, "run", fake_run)


@pytest.mark.parametrize("code", ["-9074", "-2700", "-609", "-1712"])
def test_stuck_powerpoint_errors_carry_a_remedy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str) -> None:
    _fail_with(monkeypatch, f"195:208: execution error: Microsoft PowerPoint 發生錯誤：發生錯誤。 ({code})")
    with pytest.raises(export.ExportError, match="處置：PowerPoint 可能停在儲存對話框") as e:
        export.export_pdf(tmp_path / "a.pptx", tmp_path / "a.pdf")
    assert code in str(e.value)


def test_other_errors_are_reported_as_is(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fail_with(monkeypatch, "execution error: 找不到應用程式 (-600)")
    with pytest.raises(export.ExportError) as e:
        export.export_pdf(tmp_path / "a.pptx", tmp_path / "a.pdf")
    assert "處置" not in str(e.value)
    assert "-600" in str(e.value)
