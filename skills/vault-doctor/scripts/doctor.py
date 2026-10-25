#!/usr/bin/env python3
"""Obsidian Tech Vault 結構與健康度診斷工具（零第三方依賴）。

檢查項目：
1. 孤兒筆記（Orphan Notes）：未被 Index、MOC 或任何其他筆記引用的檔案。
2. 損壞連結（Broken Wikilinks）：[[target]] 無法對應到現存筆記或路徑。
3. 章節結構模板對稱性（Template Compliance）：
   主題目錄 -> 庫首頁.md + 00 總論/0 章首.md + 二位數章節目錄（內含 0 章首.md）。
4. Frontmatter 合規性：ISO 日期、MOC 標記（type: moc, tags: [moc]）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


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


def run_doctor(vault_dir: Path) -> int:
    vault_dir = vault_dir.resolve()
    print(f"\n🔍 開始診斷技術知識庫：{vault_dir}\n")

    md_files = [p for p in vault_dir.rglob("*.md") if ".git" not in p.parts and ".obsidian" not in p.parts and ".serena" not in p.parts]
    total_notes = len(md_files)
    print(f"📄 發現 Markdown 筆記總數：{total_notes}")

    all_relative_stems = set()
    all_stems = set()
    file_contents: dict[Path, str] = {}

    for p in md_files:
        rel = p.relative_to(vault_dir)
        rel_no_ext = str(rel.with_suffix(""))
        stem = p.stem
        all_relative_stems.add(rel_no_ext)
        all_stems.add(stem)
        try:
            file_contents[p] = p.read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️ 無法讀取檔案 {rel}: {e}")

    # 1. 檢查 Index.md
    index_file = vault_dir / "Index.md"
    has_index = index_file.is_file()
    print(f"🏠 全庫總入口 Index.md：{'✅ 存在' if has_index else '❌ 缺失'}")

    # 2. 檢查主題結構對稱性
    theme_dirs = [d for d in vault_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "scripts", "evals", "template", "node_modules"))]
    print(f"\n📦 檢查 {len(theme_dirs)} 個頂層主題目錄的模板符合度：")

    structure_errors = []
    for theme in sorted(theme_dirs):
        theme_home = theme / "庫首頁.md"
        if not theme_home.is_file():
            structure_errors.append(f"{theme.name}: 缺少 庫首頁.md")

        overview_dir = theme / "00 總論"
        overview_home = overview_dir / "0 章首.md"
        if not overview_dir.is_dir() or not overview_home.is_file():
            structure_errors.append(f"{theme.name}: 缺少 00 總論/0 章首.md")

        chapters = [c for c in theme.iterdir() if c.is_dir() and not c.name.startswith(".")]
        for c in sorted(chapters):
            c_home = c / "0 章首.md"
            if not c_home.is_file():
                structure_errors.append(f"{theme.name}/{c.name}: 缺少 0 章首.md")

    if structure_errors:
        print(f"  ❌ 發現 {len(structure_errors)} 處結構不符合統一模板：")
        for err in structure_errors[:10]:
            print(f"     - {err}")
    else:
        print("  ✅ 全庫主題均 100% 符合對稱二層模板（主題/ ➔ 庫首頁 + 00 總論 + 章節 0 章首）")

    # 3. 掃描 Wikilinks
    wikilink_pat = re.compile(r"\[\[([^\]\\\|#]+)(?:#[^\]\\\|]+)?(?:\\?\|[^\]]+)?\]\]")
    broken_links = []
    referenced_stems = set()

    for p, content in file_contents.items():
        rel = p.relative_to(vault_dir)
        # 排除說明文件中的語法範例
        if p.name in ("README.md", "AGENTS.md", "CLAUDE.md"):
            continue

        for m in wikilink_pat.finditer(content):
            raw_target = m.group(1).strip()
            # 排除 CI 筆記常見的 TOML table 表頭（例如 [[runners]]）
            if raw_target in ("runners", "runners.kubernetes.volumes.pvc", "registry", "registry.mirror"):
                continue

            referenced_stems.add(raw_target)
            referenced_stems.add(Path(raw_target).name)

            # 驗證目標
            if raw_target in all_relative_stems or raw_target in all_stems or (raw_target + ".md") in all_relative_stems:
                continue
            broken_links.append((rel, raw_target))

    print(f"\n🔗 雙向連結檢驗：")
    if broken_links:
        print(f"  ❌ 發現 {len(broken_links)} 處潛在斷鏈：")
        for f, t in broken_links[:10]:
            print(f"     - 在 {f} 中：[[{t}]]")
    else:
        print("  ✅ 全庫雙向連結 100% 解析成功，無懸空斷鏈")

    # 4. 孤兒筆記檢查
    orphans = []
    for p in md_files:
        rel = p.relative_to(vault_dir)
        rel_str = str(rel.with_suffix(""))
        stem = p.stem
        # Index.md 與特定根文件不計為孤兒
        if stem in ("Index", "README", "AGENTS", "CLAUDE", "庫首頁", "0 章首"):
            continue
        if stem not in referenced_stems and rel_str not in referenced_stems:
            orphans.append(rel)

    print(f"\n🏝️ 孤兒筆記檢查（未被任何 MOC、章首或其他筆記引用）：")
    if orphans:
        print(f"  ⚠️ 發現 {len(orphans)} 篇孤兒筆記：")
        for o in orphans[:10]:
            print(f"     - {o}")
    else:
        print("  ✅ 全庫筆記均已被結構化納入引用拓撲，無孤兒筆記")

    # 5. Frontmatter 檢驗
    missing_date = []
    missing_moc_tag = []
    for p, content in file_contents.items():
        rel = p.relative_to(vault_dir)
        meta = parse_frontmatter(content)
        if not meta.get("updated"):
            missing_date.append(rel)
        if p.name in ("Index.md", "庫首頁.md"):
            tags = meta.get("tags", "")
            if "moc" not in tags:
                missing_moc_tag.append(rel)

    print(f"\n🏷️ Frontmatter 元數據健康度：")
    if missing_date:
        print(f"  ⚠️ {len(missing_date)} 篇筆記缺少 updated 更新日期")
    else:
        print("  ✅ 所有筆記均包含 updated 日期")

    if missing_moc_tag:
        print(f"  ⚠️ {len(missing_moc_tag)} 份 MOC 首頁缺少 tags: [moc] 標記")
    else:
        print("  ✅ 所有 MOC 筆記均標記 tags: [moc]")

    # 總結
    print("\n" + "=" * 50)
    has_issues = bool(structure_errors or broken_links)
    if has_issues:
        print("🚨 診斷完成：發現結構或連結異常，需進行修復。")
        return 1
    else:
        print("🎉 診斷完成：知識庫結構健全，符合全庫統一模板與最佳實踐！")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian Tech Vault 健康度診斷工具")
    parser.add_argument("vault", nargs="?", default=".", help="知識庫根目錄路徑（預設當前目錄）")
    args = parser.parse_args()
    sys.exit(run_doctor(Path(args.vault)))


if __name__ == "__main__":
    main()
