"""doctor.py 回歸測試：python3 skills/vault-doctor/scripts/test_doctor.py（或 bash test.sh）"""

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from doctor import diagnose, parse_aliases, run_doctor, strip_code  # noqa: E402

FM = "---\ntype: moc\nupdated: 2026-01-01\ntags: [moc]\n---\n"


def quiet(*args, **kwargs) -> int:
    with redirect_stdout(io.StringIO()):
        return run_doctor(*args, **kwargs)


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
        assert quiet(root) == 0


def test_real_broken_link_still_caught():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "[[不存在的筆記]]\n")
        assert quiet(root) == 1


def test_ignore_is_relative_to_vault_root():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / ".claude" / "worktrees" / "vault"
        root.mkdir(parents=True)
        make_vault(root, "[[不存在的筆記]]\n")
        assert quiet(root) == 1  # vault 位於 .claude 之下仍須掃描
        (root / ".claude").mkdir()
        (root / ".claude" / "n.md").write_text("[[壞連結]]", encoding="utf-8")
        assert quiet(root) == 1  # vault 內的 .claude 仍被忽略（不新增斷鏈）


def test_custom_names():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "Home.md").write_text(FM + "[[Hub]]\n", encoding="utf-8")
        (root / "T").mkdir()
        (root / "T" / "Hub.md").write_text(FM, encoding="utf-8")
        (root / "T" / "Intro").mkdir()
        (root / "T" / "Intro" / "Start.md").write_text(FM, encoding="utf-8")
        names = {"index": "Home.md", "theme_home": "Hub.md", "overview_dir": "Intro", "chapter_home": "Start.md"}
        assert quiet(root, names) == 0
        assert quiet(root) == 1  # 預設名稱找不到 → 結構異常


def test_attachment_embed_not_broken():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "![[diagram.png]]\n")
        (root / "T" / "diagram.png").write_bytes(b"\x89PNG")
        assert diagnose(root)["broken_links"] == []
        (root / "T" / "diagram.png").unlink()
        assert [b["target"] for b in diagnose(root)["broken_links"]] == ["diagram.png"]


def test_parse_aliases_forms():
    assert parse_aliases("---\naliases: [a, b]\n---\n") == ["a", "b"]
    assert parse_aliases("---\naliases:\n  - x\n  - \"y\"\n---\n") == ["x", "y"]
    assert parse_aliases("---\naliases: solo\n---\n") == ["solo"]
    assert parse_aliases("沒有 frontmatter") == []


def test_alias_conflicts_and_strict_exit_code():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "[[甲]] [[乙]]\n")
        (root / "T" / "甲.md").write_text(FM.replace("tags", "aliases: [共用]\ntags"), encoding="utf-8")
        (root / "T" / "乙.md").write_text(FM.replace("tags", "aliases: [共用]\ntags"), encoding="utf-8")
        report = diagnose(root)
        assert [c["alias"] for c in report["alias_conflicts"]] == ["共用"]
        assert quiet(root) == 0  # 撞名只是警告
        assert quiet(root, strict=True) == 1


def test_orphans_only_fail_in_strict():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "")
        (root / "T" / "孤島.md").write_text(FM, encoding="utf-8")
        assert diagnose(root)["orphans"] == ["T/孤島.md"]
        assert quiet(root) == 0
        assert quiet(root, strict=True) == 1


def test_theme_filter_is_exact_name():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "")
        (root / "scripts-notes").mkdir()  # 以 scripts 開頭但不是被忽略的目錄
        errors = diagnose(root)["structure_errors"]
        assert any(e.startswith("scripts-notes") for e in errors)


def test_json_output_is_parseable_and_complete():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, "[[壞一]] [[壞二]]\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_doctor(root, as_json=True, limit=1)
        data = json.loads(buf.getvalue())
        assert code == 1 and len(data["broken_links"]) == 2  # --json 不受 limit 截斷


def test_text_limit_reports_remaining():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_vault(root, " ".join(f"[[壞{i}]]" for i in range(5)))
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_doctor(root, limit=2)
        assert "還有 3 筆" in buf.getvalue()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok  ", name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("FAIL", name, repr(exc))
    sys.exit(1 if failed else 0)
