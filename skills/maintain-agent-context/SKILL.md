---
name: maintain-agent-context
description: >-
  決定 agent 指示寫進哪個檔並維護這些檔：預設只用與廠商無關的 AGENTS.md、不建 CLAUDE.md 或 CLAUDE.local.md，個人偏好放 ~/.claude/CLAUDE.md，已安裝的技能改來源、不改副本。
  用於要把建置、測試指令或規範寫進 CLAUDE.md、AGENTS.md、.cursorrules 或 .cursor/rules，新增、搬移或整理這些指示檔，或修正 .agents/skills 下已安裝的技能（含錯字；skills-lock.json 所列的技能要改來源）時。
license: MIT
---

# 維護 agent 脈絡

## 唯一來源

分層定義在 **`AGENTS.md` →「分層」**：先讀它，其他地方只連結、不重述。技能格式：[Agent Skills 規格](https://agentskills.io/specification)。

## 規則

1. **預設不放 `CLAUDE.md`。** 工作目錄及其上層都沒有 `CLAUDE.md`、`.claude/CLAUDE.md`、`CLAUDE.local.md` 時，Claude Code 直接讀 `AGENTS.md`（進子目錄時也讀巢狀 `AGENTS.md`），需 v2.1.277 以上。任何一份 `CLAUDE.md` 都讓它停讀，上層目錄（如容器目錄）的也算；`~/.claude/CLAUDE.md` 與 `.claude/rules/` 不算，照常載入（2026-11-17 對[官方文件](https://code.claude.com/docs/en/memory#agents-md)核對）。
   - 個人覆寫放 `~/.claude/CLAUDE.md` 與 `.claude/settings.local.json`，不放 `CLAUDE.local.md`。
   - 只有必須支援 v2.1.277 之前、或讀不到 `AGENTS.md` 的 session（例如停用內建外掛）時才放 `CLAUDE.md`：以 `@AGENTS.md` 開頭、其餘只放 Claude 專屬備註，每個有巢狀 `AGENTS.md` 的目錄各放一份。
2. **Cursor 只用 `.cursor/rules/*.mdc`**，且僅在需要 Cursor 專屬範圍時；`.cursorrules` 是舊制。
3. **`AGENTS.md` 是單一基準**：規則與技能用連結或引用它，不複製。
4. **技能放 `.agents/skills/`**。Claude Code 只掃 `.claude/skills/`，所以逐一連結：`.claude/skills/<name>` → `../../.agents/skills/<name>`。連的是 `<name>` 項目，不是 `skills` 目錄本身（[官方文件](https://code.claude.com/docs/en/skills)只涵蓋技能項目的 symlink）；技能只存在 `.agents/skills/` 一份。
5. **共用技能預設全域安裝**：單人單機用 `npx skills add <來源> --skill <name> -g -a codex -y` 裝到 `~/.agents/skills`，以 `npx skills update -g -y` 更新；個人技能對本機所有專案生效、同名時蓋過專案層，專案層不放副本。只有團隊共用或雲端 session（讀不到 `~/.claude/skills/`）才裝進專案：技能列在 `skills-lock.json`，來源由其 `source` 欄位指定，要改就去來源改，經排程的 skills-update pipeline（或手動 `npx skills update -p -y`）取得變更。
6. **合併技能更新前審 diff**：技能以 agent 的完整權限執行；更新 pipeline 只開合併請求，不推到預設分支。

## 內容該放哪裡

| 內容 | 去處 |
|------|------|
| 確切的安裝／測試／lint 指令 | `AGENTS.md` 的指令區 |
| 該 repo 專屬的流程 | 該 repo 的 `.agents/skills/` 技能 |
| 跨 repo 重用的流程 | 共用技能 repo 的技能，用 `npx skills add` 安裝 |
| 依檔案類型或路徑限定的 Cursor 指引 | 帶 `globs:` 的 `.cursor/rules/*.mdc`（優先 `alwaysApply: false`） |
| 套件層級的覆寫 | 該套件旁的巢狀 `AGENTS.md` |
| 個人覆寫（不入庫） | `~/.claude/CLAUDE.md`、`.claude/settings.local.json` |

## 技能檢核

- 目錄名 == frontmatter `name`；`description` 寫明做什麼 + 何時用，關鍵用途與觸發詞放前段（規格上限 1,024 字；Claude Code 的技能清單把 `description` 與 `when_to_use` 合併後截在 1,536 字元，2026-11-17 對[技能文件](https://code.claude.com/docs/en/skills)核對）。
- `SKILL.md` 控制在 500 行內；細節放 `references/`（只連一層，超過 100 行加目錄）、可執行的放 `scripts/`、範本放 `assets/`。
- 腳本要能在 agent 的非互動 shell 執行：不開提示、有 `--help`、失敗時 stderr 說明原因、輸出長度可控（`--limit`）、需要解析時提供 `--json`。
- 連結權威來源（`AGENTS.md`、官方文件），不複製會漂移的事實。
