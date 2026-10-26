"""doctor.py 回歸測試：uv run skills/vault-doctor/scripts/test_doctor.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from doctor import run_doctor, strip_code  # noqa: E402

FM = "---\nupdated: 2026-01-01\ntags: [moc]\n---\n"


def make_vault(root: Path, body: str) -> None:
    (root / "Index.md").write_text(FM + "[[庫首頁]]\n" + body, encoding="utf-8")
    (root / "T").mkdir()
    (root / "T" / "庫首頁.md").write_text(FM, encoding="utf-8")
    (root / "T" / "00 總論").mkdir()
    (root / "T" / "00 總論" / "0 章首.md").write_text(FM, encoding="utf-8")


def test_code_stripped():
    text = "a\n```bash\nif [[ -t 1 ]]; then :; fi\n```\n~~~\n[[x]]\n~~~\n`[[y]]` ok [[z]]\n"
    out = strip_code(text)
    assert "[[ -t 1 ]]" not in out and "[[x]]" not in out and "[[y]]" not in out
    assert "[[z]]" in out


def test_fenced_no_false_broken_link():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "```bash\n[[ -t 1 ]] && echo tty\n```\n行內 `[[ -f a ]]`\n")
        assert run_doctor(root) == 0


def test_real_broken_link_still_caught():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "[[不存在的筆記]]\n")
        assert run_doctor(root) == 1


def test_ignore_is_relative_to_vault_root():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / ".claude" / "worktrees" / "vault"
        root.mkdir(parents=True)
        make_vault(root, "[[不存在的筆記]]\n")
        assert run_doctor(root) == 1  # vault 位於 .claude 之下仍須掃描
        (root / ".claude").mkdir()
        (root / ".claude" / "n.md").write_text("[[壞連結]]", encoding="utf-8")
        assert run_doctor(root) == 1  # vault 內的 .claude 仍被忽略（不新增斷鏈）


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
