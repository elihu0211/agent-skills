"""PDF 匯出：PowerPoint 只碰唯一檔名的副本（不撞使用者開著的同名簡報）；卡住類錯誤碼附處置，其餘錯誤原樣。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from deckstyle import export


def _deck(folder: Path) -> Path:
    deck = folder / "a.pptx"
    deck.write_bytes(b"pptx bytes")
    return deck


def _fail_with(monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)

    monkeypatch.setattr(export.subprocess, "run", fake_run)


@pytest.mark.parametrize("code", ["-9074", "-2700", "-609", "-1712"])
def test_stuck_powerpoint_errors_carry_a_remedy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str) -> None:
    _fail_with(monkeypatch, f"195:208: execution error: Microsoft PowerPoint 發生錯誤：發生錯誤。 ({code})")
    with pytest.raises(export.ExportError, match="處置：PowerPoint 可能停在儲存對話框") as e:
        export.export_pdf(_deck(tmp_path), tmp_path / "a.pdf")
    assert code in str(e.value)


def test_other_errors_are_reported_as_is(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fail_with(monkeypatch, "execution error: 找不到應用程式 (-600)")
    with pytest.raises(export.ExportError) as e:
        export.export_pdf(_deck(tmp_path), tmp_path / "a.pdf")
    assert "處置" not in str(e.value)
    assert "-600" in str(e.value)


def test_powerpoint_only_sees_a_uniquely_named_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """使用者開著同名簡報時，PowerPoint 以檔名找簡報會抓錯；交給它的必須是同資料夾、唯一檔名的副本。"""
    deck, pdf = _deck(tmp_path), tmp_path / "a.pdf"
    seen: dict[str, Path | str | bytes] = {}

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        opened, target, name = Path(cmd[2]), Path(cmd[3]), cmd[4]
        seen.update(opened=opened, name=name, bytes=opened.read_bytes())
        target.write_bytes(b"%PDF")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export.subprocess, "run", fake_run)
    export.export_pdf(deck, pdf)
    opened = seen["opened"]
    assert isinstance(opened, Path)
    assert opened.parent == deck.parent
    assert opened.name != deck.name
    assert seen["name"] == opened.name
    assert seen["bytes"] == deck.read_bytes()
    assert not opened.exists()
    assert pdf.read_bytes() == b"%PDF"


def test_the_copy_is_removed_when_export_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    _fail_with(monkeypatch, "execution error: 找不到應用程式 (-600)")
    with pytest.raises(export.ExportError):
        export.export_pdf(deck, tmp_path / "a.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pptx"]
