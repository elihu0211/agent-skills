# 接上守門與 CLI 合約

## 目錄

- [check.py](#checkpy)：參數、結束碼、輸出
- [編譯模式與快取](#編譯模式與快取)
- [hook.py](#hookpy)：Claude Code 的 PostToolUse hook
- [接到建置、pre-push 與 CI](#接到建置pre-push-與-ci)
- [測試與 fixture](#測試與-fixture)

## check.py

```
uv run <技能目錄>/scripts/check.py FILE_OR_DIR... [--mode auto|quarto|latex] [--preamble FILE]...
       [--engine ENGINE] [--min-gap LEN] [--max-width LEN] [--json] [--limit N] [--timeout SEC]
       [--cache-dir DIR | --no-cache] [--keep-pdf PDF | --from-pdf PDF]
```

| 參數 | 說明 |
|------|------|
| `FILE_OR_DIR` | `.qmd`（只抽 `{=latex}`／`{=tex}` raw block 裡的圖）或 `.tex`；目錄遞迴找含 `tikzpicture` 的檔案，略過 `.` 與 `_` 開頭的目錄、`node_modules`、`*_files`。底線開頭的 `_*.qmd` 片段照常檢查 |
| `--mode` | `auto`（預設）：上層有 `_quarto.yml` 用 `quarto`，否則 `latex` |
| `--preamble` | `latex` 模式的前置檔，可重複；也可給完整文件（取 `\begin{document}` 之前）。沒給時，來源本身是完整文件就用它的前置，否則只載入 `tikz` 與常用函式庫 |
| `--engine` | TeX 引擎名稱或路徑；預設 `quarto` 模式沿用專案設定（由 Quarto 產出的 PDF 判斷），`latex` 模式 `xelatex`。PATH 找不到時另找 TinyTeX 與 TeX Live 的常見位置 |
| `--min-gap` | 節點最小間距，預設 `2pt`；單位 `pt`、`bp`、`mm`、`cm`、`in` |
| `--max-width` | 圖寬上限，例如 `16cm`；不給就不檢查 |
| `--json` | 單一 JSON 物件（欄位見下） |
| `--limit` | 最多列幾個問題，預設 30；`0` 列全部 |
| `--timeout` | 每次 Quarto／TeX 執行的秒數上限，預設 300 |
| `--cache-dir`／`--no-cache` | 量測快取，預設 `${XDG_CACHE_HOME:-~/.cache}/tikz-guard` |
| `--keep-pdf`／`--from-pdf` | 除錯用：另存編出的 PDF；或不編譯、直接量存下的 PDF。只能配一個來源檔 |

**結束碼**：`0` 通過｜`1` 圖有問題（含圖本身編譯失敗）｜`2` 執行環境問題（找不到檔案、TeX 或 Quarto，前置編不過，逾時）。

**文字輸出**：問題寫到 stderr，一行一個：`✗ 檔案:行號 標籤 [規則] 訊息`，最後一行是總結；通過時 stdout 印 `✓ …：沒有壓疊`。警告（缺字、略過的圖）以 `!` 開頭。

**JSON 輸出**（stdout）：

```json
{"ok": false, "files": 2, "figures": 14, "compiled": 3, "omitted": 0, "warnings": [],
 "issues": [{"file": "docs/a.qmd", "line": 51, "figure": 1, "label": "fig:case",
             "rule": "label-on-node", "message": "…", "nodes": ["「書面初審」"]}]}
```

`line` 是 `\begin{tikzpicture}` 所在行，`figure` 是該檔第幾張圖，`label` 取同一個 figure 環境的 `\label`（優先 `fig:` 開頭），沒有時取外層 Quarto 區塊的 `#fig-…`。結束碼 `2` 時印 `{"ok": false, "error": "…"}`。

## 編譯模式與快取

- **quarto**：在來源檔旁暫放 `tikz-guard-<亂數>.qmd`（不能以 `_` 開頭，否則 Quarto 不套用專案設定），帶著來源 frontmatter 中會進 LaTeX 前置的鍵（`format`、字型、`geometry`、`include-in-header` 等），以 `quarto render --to pdf -M keep-tex:true` 取得專案實際的前置。結束時刪掉暫存檔、它的 `.tex`／PDF 與 `.quarto/` 下新出現的檔案，原本就有的檔案不動。前置依 `_quarto*.yml`、沿路的 `_metadata.yml`、它們提到的 `.tex`／`.sty` 與上述 frontmatter 的雜湊快取，設定沒變就不再呼叫 Quarto。
- **latex**：以前置檔加上大頁面設定直接編譯。
- 共用同一份前置的圖在一次 TeX 執行裡編完；某張圖編不過就記成 `compile`，拿掉它重編其餘的。
- 每張圖的量測依「前置、引擎、來源目錄、圖原始碼」的雜湊快取，只重編改過的圖：一個 118 張圖的 Quarto 文件庫冷啟動約 15 秒，全部命中快取約 0.2 秒（2026-11-26 在 Apple Silicon 筆電量測）。

## hook.py

Claude Code 的 PostToolUse hook。從 stdin 讀 hook 的 JSON，被改的檔案（`tool_input.file_path`）是 `.qmd`／`.tex` 且含 `\begin{tikzpicture}` 時，只檢查那個檔：

| 情況 | hook 的輸出 | 結束碼 |
|------|-------------|--------|
| 不是要檢查的檔、或圖都通過 | 無 | `0` |
| 圖有壓疊 | 問題清單與 `references/rules.md` 的路徑寫到 stderr，Claude Code 會回饋給 agent | `2` |
| 執行環境問題（找不到 uv、Quarto、TeX，逾時，stdin 不是 JSON） | stdout 印 `{"systemMessage": "…"}` 警告使用者，不擋編輯 | `0` |

參數：`--limit N`（回饋幾個問題，預設 20）、`--timeout SEC`（整個檢查的上限，預設 540，要小於 hook 設定的 `timeout`）；`--` 之後原樣交給 `check.py`（例如 `-- --mode latex --preamble tex/preamble.tex --max-width 16cm`）。

`.claude/settings.json`（技能以 skills CLI 裝在 `.agents/skills/` 時）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"$CLAUDE_PROJECT_DIR\"/.agents/skills/guard-tikz-figures/scripts/hook.py",
            "timeout": 600
          }
        ]
      }
    ]
  }
}
```

PostToolUse 以結束碼 2 結束時，Claude Code 把 stderr 交給 agent（工具已執行）；結束碼 0 時 stderr 不會給 agent，要提醒使用者得用 JSON 的 `systemMessage`；command hook 預設逾時 10 分鐘（[hooks 文件](https://code.claude.com/docs/en/hooks)，2026-11-26 核對）。

## 接到建置、pre-push 與 CI

三處都呼叫同一個指令，差別只在給的範圍：

```bash
uv run .agents/skills/guard-tikz-figures/scripts/check.py docs papers --max-width 16cm
```

- **建置檢查**：放在 render 之前，結束碼非 `0` 就停；結束碼 `2` 代表機器缺 TeX 或 Quarto，要修環境，不要略過。
- **pre-push**：同一個指令；快取讓沒改的圖不重編，整個文件庫通常幾秒內跑完。要只看這次推送改到的檔案時，把 `git diff --name-only @{push}.. -- '*.qmd' '*.tex'` 的結果當參數。
- **CI**：runner 要有 TeX（例如先 `quarto install tinytex`）；沒有 TeX 時 `check.py` 以結束碼 `2` 結束，不會默默通過。

## 測試與 fixture

`scripts/test.sh` 以 `assets/fixtures/` 驗證：`clean.tex` 每張圖都要通過，`rules.tex` 每條規則各有一張違規圖，`doc.qmd` 驗 raw block 抽圖、行號與標籤；每張圖以 `% expect: <規則>` 標出預期，測試比對回報的規則集合是否完全相同。有 TeX 時重新編譯並確認夾帶的 PDF 沒有過期，另驗快取、目錄掃描、hook 與 quarto 模式不留暫存檔；沒有 TeX 的 CI 改量夾帶的 PDF。改了 fixture 要重產 PDF：

```bash
uv run scripts/check.py assets/fixtures/rules.tex --mode latex --no-cache --keep-pdf assets/fixtures/rules.pdf
```
