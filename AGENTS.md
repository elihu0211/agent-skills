# AGENTS.md

本 repo 是跨專案共用技能的唯一來源。結構、安裝、新增技能步驟與發布：見 [`README.md`](README.md)。

## 指令

```bash
uv run scripts/validate.py   # 規格與 repo 規則（marketplace 登記、evals 數量、連結）；開 PR 前必須通過
```

## 規則

- **遵循 [Agent Skills 規格](https://agentskills.io/specification)。** `description` 先寫技能做什麼，再寫「用於…」的使用時機。
- **漸進揭露。** `SKILL.md` 放步驟與規則；細節放 `references/`，從 `SKILL.md` 直接連結、只深一層。agent 要執行的程式碼放 `scripts/`；範本與資料放 `assets/`。
- **與專案無關。** 技能裡的指令、路徑與技術棧一律交給消費端 repo 的 `AGENTS.md` 決定；技能本文只寫通用流程，也不提本 repo 名稱（消費端透過 `skills-lock.json` 找到來源）。
- **公開 repo。** 內容限於可公開的通用知識：機密、內部網址、客戶或專案細節一律不放。
- **寫入事實前先查證。** 法規、標準、論文要回到原始來源核對，並記錄核對程度（全文、摘要、書目）與日期。會漂移的值（版本、筆數、修正日期）寫成「於某日核對」並附可重查的來源。
- **語言：繁體中文。** 技能本文、參考文件、評估與文件都用繁體中文；指令、程式碼識別字與技術名詞保留原文。
- **CI 範本是公開介面。** `ci/` 與 `.github/workflows/skills-update.yml` 以 `v1` 標籤被消費端引用；變更要向後相容，破壞性變更改發 `v2`（見 README → 發布）。
- **分支要落地。** 變更一律經 PR squash 合併進 `main`。session 結束時，分支須已落地（PR 已合併、worktree 與本機分支已移除）或已交接（推上並開 draft PR，寫明卡點）。
