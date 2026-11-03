---
name: vault-doctor
description: >-
  用於檢核、診斷、修復或維護 Obsidian 技術知識庫（Tech Vault）的結構健康度時：
  稽核孤兒筆記、損壞斷鏈（broken wikilinks）、Frontmatter 與別名合規性、
  章節模板對稱性（二層目錄與 0 章首）、wikilink 誤報（如程式碼區塊裡的 [[ ]]），並輸出健康報告與修復建議（腳本唯讀）。
compatibility: 需要 python3（僅標準函式庫）；搬移檔案修復時需要 git。
license: MIT
---

# 知識庫健檢與結構治理（Vault Doctor）

維護 Markdown 技術知識庫（Obsidian Vault）的結構對稱性、引用拓撲與元數據衛生。確保知識庫維持「弱資料夾、強連結、對稱章節模板與動態檢索」的工程標準。

## 先讀

- 消費端 repo 的 `AGENTS.md`：知識庫若已定義自己的章節模板、檔名或 frontmatter 欄位，以它為準；本技能的檔名（`Index.md`、`庫首頁.md`、`00 總論`、`0 章首.md`）是預設慣例，可用 `--index`、`--theme-home`、`--overview-dir`、`--chapter-home` 覆寫。

## 核心稽核維度

1. **章節結構對稱性（Template Compliance）**：
   - 頂層根目錄必須具備 `Index.md`（總入口 MOC）。
   - 每個主題目錄必須具備 `庫首頁.md`（主題總 MOC）。
   - 每個主題必須具備 `00 總論/0 章首.md`，定義該主題架構、控制迴圈與全景圖。
   - 所有次級目錄採二位數序號命名（`01 <名詞>`、`02 <名詞>`），且內部必須包含 `0 章首.md` 作為章節導覽。
2. **雙向連結完整性（Wikilink Integrity）**：
   - 檢查所有 `[[wikilink]]` 參照目標是否存在。
   - 跨主題引用使用帶路徑形式（`[[主題/庫首頁|別名]]`），避免共用檔名撞名。
   - 表格內部若有 Wikilink pipe，必須正確轉義（`\|`）。
3. **孤兒筆記掃描（Orphan Notes Detection）**：
   - 檢查是否有未被任何 MOC、章首或關聯筆記引用的孤立原子筆記。
   - 孤兒筆記應及時收納至對應章節並於 `0 章首.md` 或 `庫首頁.md` 補上連結。
4. **元數據合規性（Frontmatter Hygiene）**：
   - 每篇筆記必須具備 ISO 格式的 `updated: YYYY-MM-DD`。
   - MOC 筆記必須包含 `type: moc` 與 `tags: [moc]`。
   - 新增 `aliases` 時確認不與全庫其他筆記或首頁撞名。

## 執行健檢

執行內建診斷腳本（路徑相對於本技能目錄；腳本唯讀，有結構斷鏈時結束碼為 1）：

```bash
python3 scripts/doctor.py [vault-path]
```

腳本會依序掃描並回報：
- 筆記總數與主題數量
- 結構模板符合度（是否有缺少 `庫首頁.md` 或 `0 章首.md` 的目錄）
- 損壞的雙向連結清單
- 孤兒筆記清單
- Frontmatter 缺少日期或 MOC 標記的筆記清單

掃描連結前會先剝除 fenced code（` ``` `、`~~~`）與 inline code，故程式碼中的 `[[ ... ]]`（如 shell 條件式）不計為斷鏈；忽略目錄（`.git`、`.claude`、`scripts`、`evals` 等）以相對於 vault 根的路徑比對。回歸測試：`python3 scripts/test_doctor.py`。

## 修復流程

當診斷出異常時，遵循以下順序修復：

1. **修正目錄與章首**：
   - 缺少章節層時，依主題範疇建立二位數序號目錄，並建立 `0 章首.md`。
   - 搬移既有筆記至子目錄時，一律使用 `git mv` 保留版本歷史。
2. **修復雙向連結**：
   - 搬移包含同名檔案（如 `庫首頁`、`0 章首`）的目錄後，搜尋全庫並批次更新引用路徑。
   - 執行腳本再次確認 0 斷鏈。
3. **消除孤兒筆記**：
   - 將孤兒筆記之 Wikilink 補入該章節 `0 章首.md` 的「筆記索引」區塊。
4. **校正元數據**：
   - 補齊缺失的 `updated` 日期與 `tags: [moc]` 標籤。

## 規則

- 診斷腳本不改檔；修復由 agent 依上述流程手動進行，搬移一律 `git mv`。
- 修復後必須重跑腳本，斷鏈為 0 才算完成。
