---
name: audit-obsidian-vault
description: >-
  唯讀稽核 Obsidian 技術知識庫：章節模板對稱性、斷鏈、孤兒筆記、Frontmatter 與 aliases 撞名，輸出文字或 JSON 健康報告與修復順序。
  用於檢查、診斷、修復知識庫結構，或健檢誤報 wikilink（如程式碼區塊裡的 `[[ ]]`）、搬移章節後連結失效時。
compatibility: 需要 python3（僅標準函式庫）；搬移檔案修復時需要 git。
license: MIT
---

# 稽核 Obsidian 知識庫

維持 Markdown 知識庫「弱資料夾、強連結、對稱章節模板」的結構。腳本唯讀，修復由你依下方流程手動做。

知識庫若在消費端 `AGENTS.md` 定義了自己的章節模板、檔名或 frontmatter 欄位，以它為準；本技能的檔名是預設，可用旗標覆寫。

## 稽核維度

1. **章節模板**：根目錄有 `Index.md`；每個主題目錄有 `庫首頁.md` 與 `00 總論/0 章首.md`；其餘章節目錄採二位數序號（`01 <名詞>`），各含 `0 章首.md`。主題可直接放根目錄，也可放在**分區資料夾**下（例：`10 知識工程/RAG/`）：根目錄的子資料夾沒有 `庫首頁.md`、但其子資料夾有，就視為分區，只負責分組，不要求自己有庫首頁與總論。
2. **連結**：每個 `[[wikilink]]` 的目標存在（筆記或附件）；跨主題引用用帶路徑形式 `[[主題/庫首頁|別名]]`，避免撞名；路徑以**尾綴**解析（與 Obsidian 相同），所以主題搬進分區資料夾後，`[[RAG/庫首頁]]` 仍指向 `10 知識工程/RAG/庫首頁.md`，不必改寫；表格內的 pipe 要轉義 `\|`。
3. **孤兒筆記**：沒被任何筆記引用的檔案，補進所屬章節 `0 章首.md` 的索引區塊。
4. **Frontmatter**：每篇有 ISO 格式 `updated: YYYY-MM-DD`；MOC 有 `type: moc` 與 `tags: [moc]`；`aliases` 不與其他筆記的檔名或別名撞名。
5. **詞彙規則（選用）**：知識庫自訂的 frontmatter 詞彙，預設全關，開了只產生警告（`--strict` 才算失敗）。見下節。

## 執行

```bash
python3 scripts/audit.py [vault-path] [--json] [--limit N] [--strict]
```

路徑相對於本技能目錄。`--help` 列出全部旗標。

| 旗標 | 作用 |
|------|------|
| `--json` | 輸出結構化結果（全部列出，不截斷），給程式解析 |
| `--limit N` | 文字輸出每類最多列 N 筆（預設 20，`0` 為全部），超過會註明剩餘數量 |
| `--strict` | 孤兒、Frontmatter 缺漏與 aliases 撞名也算失敗 |
| `--index` `--theme-home` `--overview-dir` `--chapter-home` | 覆寫預設檔名（`Index.md`、`庫首頁.md`、`00 總論`、`0 章首.md`） |

結束碼：`0` 通過；`1` 有結構缺漏或斷鏈（加 `--strict` 時含警告類）；`2` 用法錯誤（例如目錄不存在）。

掃描連結前先剝除 fenced code（` ``` `、`~~~`）與 inline code，所以程式碼裡的 `[[ -t 1 ]]` 不計為斷鏈；帶副檔名的附件嵌入（`![[diagram.png]]`）以檔案是否存在判斷。忽略目錄（`.git`、`.obsidian`、`.claude`、`scripts`、`evals` 等）以相對於 vault 根的路徑比對，所以 vault 本身放在 `.claude/worktrees/` 底下也會被掃。

## 詞彙規則

在 vault 放 `.agents/audit.json`（或用 `--config` 指定）即啟用，沒有檔案就不檢查。欄位都可省略：

```json
{
  "types": ["moc", "architecture", "concept", "guide", "reference"],
  "allowed_keys": ["tags", "type", "updated", "layer", "area", "aliases"],
  "min_tag_uses": 2,
  "require_topic_tag": true,
  "home_keys": ["layer", "area"]
}
```

| 欄位 | 檢查 |
|------|------|
| `types` | 每篇 `type` 必須在清單內（缺 `type` 也算） |
| `allowed_keys` | frontmatter 只能出現清單內的欄位 |
| `min_tag_uses` | 標籤至少被這麼多篇筆記使用；主題資料夾名與 `moc` 不算 |
| `require_topic_tag` | 主題內的筆記（庫首頁除外）`tags` 要含所屬主題資料夾名 |
| `home_keys` | 每個主題的 `庫首頁` 必須有這些欄位 |

規則寫在 vault 裡（隨版控），所以 pre-commit 不必另加旗標。

## 修復順序

1. **目錄與章首**：缺章節層時建立二位數序號目錄與 `0 章首.md`；搬移既有筆記一律 `git mv` 保留歷史。
2. **連結**：搬移同名檔（`庫首頁`、`0 章首`）後，全庫搜尋並批次更新引用路徑。
3. **孤兒**：把 wikilink 補進所屬章節的 `0 章首.md`。
4. **元數據**：補 `updated` 日期與 `tags: [moc]`；撞名的 `aliases` 改成唯一。
5. **重跑腳本**：斷鏈與結構缺漏為 0 才算完成。

## 規則

- 腳本不改檔；不要為了讓報告通過而刪掉有內容的孤兒筆記，先補連結。
- 驗證本技能的腳本：`bash scripts/test.sh`。
