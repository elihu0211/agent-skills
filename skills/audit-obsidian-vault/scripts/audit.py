#!/usr/bin/env python3
"""Obsidian 技術知識庫結構與健康度診斷（唯讀、零第三方依賴）。

檢查項目：
1. 結構模板：主題目錄 → 庫首頁.md + 00 總論/0 章首.md + 各章節目錄的 0 章首.md。
   主題可直接放在根目錄，或放在「分區」資料夾下（根目錄的子資料夾沒有庫首頁.md、
   但其子資料夾有，該資料夾即為分區，只負責分組，不要求庫首頁與總論）。
2. 斷鏈：[[target]] 找不到對應的筆記或附件（程式碼區塊內的 [[ ]] 不計）。
   路徑連結以尾綴解析，與 Obsidian 一致：[[RAG/庫首頁]] 可對應 10 知識工程/RAG/庫首頁.md。
3. 孤兒筆記：沒被任何其他筆記引用。
4. Frontmatter：ISO 格式 updated、MOC 的 type/tags 標記、aliases 撞名。

結束碼：0 無結構或斷鏈問題；1 有（--strict 時孤兒、Frontmatter 與撞名也算）；2 用法錯誤。
輸出：預設人類可讀文字；--json 輸出結構化結果，方便 agent 與腳本解析。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
WIKILINK = re.compile(r"\[\[([^\]\\\|#]+)(?:#[^\]\\\|]+)?(?:\\?\|[^\]]+)?\]\]")
ALWAYS_IGNORED = {".git", ".obsidian", ".serena", ".agents", ".claude", "node_modules"}
ROOT_IGNORED = {"scripts", "evals"}
NOT_THEMES = ALWAYS_IGNORED | ROOT_IGNORED | {"template"}
DOC_FILES = {"README.md", "AGENTS.md", "CLAUDE.md", "LICENSE"}

DEFAULTS = {
    "index": "Index.md",
    "theme_home": "庫首頁.md",
    "overview_dir": "00 總論",
    "chapter_home": "0 章首.md",
}


def parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    head, sep, _ = content[4:].partition("\n---\n")
    if not sep:
        return {}
    meta = {}
    for line in head.splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def parse_aliases(content: str) -> list[str]:
    """支援 `aliases: [a, b]`、`aliases: a` 與多行 `- a` 清單。"""
    if not content.startswith("---\n"):
        return []
    head, sep, _ = content[4:].partition("\n---\n")
    if not sep:
        return []
    lines = head.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"^aliases\s*:", line):
            continue
        value = line.split(":", 1)[1].strip()
        if value:
            items = value.strip("[]").split(",")
        else:
            items = []
            for nxt in lines[i + 1 :]:
                m = re.match(r"^\s+-\s*(.+)$", nxt)
                if not m:
                    break
                items.append(m.group(1))
        return [a.strip().strip("\"'") for a in items if a.strip().strip("\"'")]
    return []


def is_ignored(rel: Path) -> bool:
    """依相對於 vault 根的路徑判斷是否忽略，避免 vault 本身位於 .claude 等目錄下時全數被排除。"""
    parts = rel.parts
    return any(part in ALWAYS_IGNORED for part in parts[:-1]) or parts[0] in ROOT_IGNORED


def strip_code(content: str) -> str:
    """移除 fenced code（``` 與 ~~~）與 inline code，避免 `[[ -t 1 ]]` 之類被誤判為 wikilink。"""
    out = []
    fence = None
    for line in content.splitlines():
        m = FENCE_OPEN.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                continue
            out.append(INLINE_CODE.sub("", line))
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and line.strip() == m.group(1):
            fence = None
    return "\n".join(out)


def path_suffixes(rel_stem: str) -> set[str]:
    """`a/b/c` → {`a/b/c`, `b/c`, `c`}：Obsidian 以路徑尾綴解析 wikilink。"""
    parts = rel_stem.split("/")
    return {"/".join(parts[i:]) for i in range(len(parts))}


def find_themes(vault_dir: Path, theme_home: str) -> tuple[list[Path], list[Path]]:
    """回傳 (分區, 主題)。

    根目錄的子資料夾若自己有庫首頁，就是主題；沒有庫首頁、但其子資料夾有者是分區，
    分區下所有子資料夾都視為主題（缺庫首頁的會被結構檢查抓出來）；其餘照舊視為主題並回報缺漏。
    """
    areas: list[Path] = []
    themes: list[Path] = []

    def visible(parent: Path) -> list[Path]:
        return sorted(d for d in parent.iterdir() if d.is_dir() and not d.name.startswith("."))

    for d in visible(vault_dir):
        if d.name in NOT_THEMES:
            continue
        if not (d / theme_home).is_file() and any((c / theme_home).is_file() for c in visible(d)):
            areas.append(d)
            themes.extend(c for c in visible(d) if c.name not in NOT_THEMES)
        else:
            themes.append(d)
    return areas, themes


def diagnose(vault_dir: Path, names: dict[str, str] | None = None) -> dict:
    """掃描 vault，回傳結構化結果；不輸出、不改檔。"""
    n = {**DEFAULTS, **(names or {})}
    vault_dir = vault_dir.resolve()

    md_files = [p for p in vault_dir.rglob("*.md") if not is_ignored(p.relative_to(vault_dir))]
    attachments: set[str] = set()
    for p in vault_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() != ".md" and not is_ignored(p.relative_to(vault_dir)):
            attachments.update({p.name, p.relative_to(vault_dir).as_posix()})

    unreadable: list[str] = []
    contents: dict[Path, str] = {}
    all_relative_stems: set[str] = set()
    all_suffixes: set[str] = set()
    all_stems: set[str] = set()
    for p in md_files:
        rel = p.relative_to(vault_dir)
        all_relative_stems.add(str(rel.with_suffix("")))
        all_suffixes |= path_suffixes(rel.with_suffix("").as_posix())
        all_stems.add(p.stem)
        try:
            contents[p] = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{rel}: {exc}")

    # 結構模板
    structure_errors: list[str] = []
    area_dirs, theme_dirs = find_themes(vault_dir, n["theme_home"])
    for theme in theme_dirs:
        label = theme.relative_to(vault_dir).as_posix()
        if not (theme / n["theme_home"]).is_file():
            structure_errors.append(f"{label}: 缺少 {n['theme_home']}")
        overview = theme / n["overview_dir"]
        if not overview.is_dir() or not (overview / n["chapter_home"]).is_file():
            structure_errors.append(f"{label}: 缺少 {n['overview_dir']}/{n['chapter_home']}")
        for chapter in sorted(c for c in theme.iterdir() if c.is_dir() and not c.name.startswith(".")):
            if not (chapter / n["chapter_home"]).is_file():
                structure_errors.append(f"{label}/{chapter.name}: 缺少 {n['chapter_home']}")

    # 斷鏈與被引用集合
    broken_links: list[dict[str, str]] = []
    referenced: set[str] = set()
    for p, content in contents.items():
        if p.name in DOC_FILES:  # 說明文件常含語法範例
            continue
        for m in WIKILINK.finditer(strip_code(content)):
            target = m.group(1).strip()
            referenced.update({target, Path(target).name})
            if target in all_suffixes or target in all_stems or target + ".md" in all_relative_stems:
                continue
            if Path(target).suffix and (target in attachments or Path(target).name in attachments):
                continue  # ![[image.png]] 之類的附件嵌入
            broken_links.append({"file": str(p.relative_to(vault_dir)), "target": target})

    # 孤兒
    exempt = {Path(n["index"]).stem, Path(n["theme_home"]).stem, Path(n["chapter_home"]).stem, "README", "AGENTS", "CLAUDE"}
    orphans = [
        str(p.relative_to(vault_dir))
        for p in md_files
        if p.stem not in exempt and p.stem not in referenced and str(p.relative_to(vault_dir).with_suffix("")) not in referenced
    ]

    # Frontmatter 與 aliases
    missing_updated: list[str] = []
    missing_moc: list[str] = []
    alias_owners: dict[str, list[str]] = {}
    for p, content in contents.items():
        if p.name in DOC_FILES:
            continue
        rel = str(p.relative_to(vault_dir))
        meta = parse_frontmatter(content)
        if not ISO_DATE.match(meta.get("updated", "").strip("\"'")):
            missing_updated.append(rel)
        if p.name in (n["index"], n["theme_home"]) and ("moc" not in meta.get("tags", "") or meta.get("type") != "moc"):
            missing_moc.append(rel)
        for alias in parse_aliases(content):
            alias_owners.setdefault(alias.casefold(), []).append(rel)
    stem_owners: dict[str, list[str]] = {}
    for p in contents:
        stem_owners.setdefault(p.stem.casefold(), []).append(str(p.relative_to(vault_dir)))
    alias_conflicts = []
    for alias, owners in sorted(alias_owners.items()):
        clash = sorted(set(owners) | {f for f in stem_owners.get(alias, []) if f not in owners})
        if len(owners) > 1 or any(f not in owners for f in stem_owners.get(alias, [])):
            alias_conflicts.append({"alias": alias, "files": clash})

    return {
        "vault": str(vault_dir),
        "notes": len(md_files),
        "has_index": (vault_dir / n["index"]).is_file(),
        "themes": len(theme_dirs),
        "areas": len(area_dirs),
        "structure_errors": structure_errors,
        "broken_links": broken_links,
        "orphans": sorted(orphans),
        "missing_updated": sorted(missing_updated),
        "missing_moc": sorted(missing_moc),
        "alias_conflicts": alias_conflicts,
        "unreadable": unreadable,
    }


def _section(title: str, rows: list[str], limit: int, level: str) -> None:
    if not rows:
        print(f"[ok]   {title}：0")
        return
    print(f"[{level}] {title}：{len(rows)}")
    shown = rows if limit == 0 else rows[:limit]
    for row in shown:
        print(f"         - {row}")
    if len(shown) < len(rows):
        print(f"         … 還有 {len(rows) - len(shown)} 筆（--limit 0 顯示全部）")


def render_text(r: dict, limit: int, index_name: str) -> None:
    areas = f"、分區 {r['areas']} 個" if r.get("areas") else ""
    print(f"知識庫：{r['vault']}\n筆記 {r['notes']} 篇、主題 {r['themes']} 個{areas}")
    print(f"[{'ok' if r['has_index'] else 'FAIL'}] 總入口 {index_name}：{'存在' if r['has_index'] else '缺失'}")
    _section("結構模板缺漏", r["structure_errors"], limit, "FAIL")
    _section("斷鏈", [f"{b['file']} → [[{b['target']}]]" for b in r["broken_links"]], limit, "FAIL")
    _section("孤兒筆記", r["orphans"], limit, "warn")
    _section("缺少 ISO updated", r["missing_updated"], limit, "warn")
    _section("MOC 缺 type: moc 或 tags: [moc]", r["missing_moc"], limit, "warn")
    _section("aliases 撞名", [f"{c['alias']}：{', '.join(c['files'])}" for c in r["alias_conflicts"]], limit, "warn")
    _section("無法讀取的檔案", r["unreadable"], limit, "warn")


def failed(r: dict, strict: bool) -> bool:
    hard = bool(r["structure_errors"] or r["broken_links"])
    soft = bool(r["orphans"] or r["missing_updated"] or r["missing_moc"] or r["alias_conflicts"])
    return hard or (strict and soft)


def run_audit(vault_dir: Path, names: dict[str, str] | None = None, *, limit: int = 20, as_json: bool = False, strict: bool = False) -> int:
    report = diagnose(vault_dir, names)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render_text(report, limit, (names or {}).get("index", DEFAULTS["index"]))
        print("結果：" + ("需要修復" if failed(report, strict) else "通過"))
    return 1 if failed(report, strict) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vault", nargs="?", default=".", help="知識庫根目錄（預設當前目錄）")
    for key, default in DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", default=default, help=f"預設 {default}")
    parser.add_argument("--json", action="store_true", help="輸出 JSON（不受 --limit 影響，列出全部）")
    parser.add_argument("--limit", type=int, default=20, help="每類最多列出幾筆（預設 20；0 為全部）")
    parser.add_argument("--strict", action="store_true", help="孤兒、Frontmatter 缺漏與 aliases 撞名也視為失敗")
    args = parser.parse_args()
    root = Path(args.vault)
    if not root.is_dir():
        print(f"找不到目錄：{root}", file=sys.stderr)
        sys.exit(2)
    names = {k: getattr(args, k) for k in DEFAULTS}
    sys.exit(run_audit(root, names, limit=args.limit, as_json=args.json, strict=args.strict))


if __name__ == "__main__":
    main()
