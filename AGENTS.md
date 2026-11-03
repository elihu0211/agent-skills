# AGENTS.md

跨專案共用技能的唯一來源。結構、安裝、新增技能與發布步驟：[`README.md`](README.md)。

開 PR 前，`uv run scripts/validate.py` 必須通過（規格、marketplace 登記、evals 數量、連結）。

## 技能內容

- **規格**：遵循 [Agent Skills 規格](https://agentskills.io/specification)；`description` 先寫做什麼，再寫「用於…」的觸發時機。
- **漸進揭露**：`SKILL.md` 放步驟與規則；細節放 `references/`，由 `SKILL.md` 直接連結、只深一層；agent 執行的程式碼放 `scripts/`；範本與資料放 `assets/`。
- **通用且可公開**：指令、路徑與技術棧交給消費端 repo 的 `AGENTS.md`，技能本文只寫通用流程，不出現本 repo 名稱（消費端經 `skills-lock.json` 找到來源）。內容限於可公開的知識，不含機密、內部網址、客戶或專案細節。
- **事實先核對**：法規、標準、論文回到原始來源，記錄核對程度（全文、摘要、書目）與日期；會漂移的值（版本、筆數、修正日期）寫成「於某日核對」並附可重查的來源。
- **繁體中文**：本文、參考文件、評估與文件皆用繁體中文；指令、程式碼識別字與技術名詞保留原文。

## 發布與合併

- **CI 範本是公開介面**：`ci/` 與 `.github/workflows/skills-update.yml` 以 `v1` 標籤被消費端引用，變更保持向後相容；破壞性變更改發 `v2`（見 README → 發布）。
- **分支落地**：變更經 PR squash 合併進 `main`。session 結束時，分支已合併且 worktree 與本機分支已移除，或已推上並開 draft PR、寫明卡點。
