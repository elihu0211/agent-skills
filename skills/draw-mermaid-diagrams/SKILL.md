---
name: draw-mermaid-diagrams
description: >-
  在 Markdown 文件撰寫與優化支援深／淺色主題自動切換的 Mermaid 圖表（frontmatter look: neo、subgraph 以 fill:transparent 配語意邊框、零寫死字色與背景色），並附離線 lint 腳本驗證。
  用於新增或優化 Mermaid 架構圖、時序圖（sequenceDiagram）、ER 圖（erDiagram）、狀態圖（stateDiagram）與類別圖，或修正 Mermaid 在暗黑模式紫底藍字撞色、黑字配黑底看不見與語法錯誤時。
license: MIT
---

# 撰寫現代 Mermaid 圖表（draw-mermaid-diagrams）

產出在 GitHub、VS Code、Obsidian 與文件網站的深／淺色模式下皆清晰可讀的 Mermaid 圖表，不寫死破壞自動主題切換的色碼，並以離線腳本驗證每個圖表區塊。

## 先讀

- 消費端 repo 的 `AGENTS.md`：它的圖表規範、色票與檢查指令優先於本技能。
- 需要各類圖表完整範本（流程圖、時序圖、ER 圖、狀態圖、類別圖、靜態雙色 `<picture>`）時，讀 [references/patterns.md](references/patterns.md)。

## 步驟

1. **決定圖表類型與閱讀方向**：依訊息結構選型（系統分層用 `flowchart LR` 或 `TB`、呼叫流程用 `sequenceDiagram`、資料表關聯用 `erDiagram`、生命週期用 `stateDiagram-v2`、物件關係用 `classDiagram`）；超過三層的分層架構優先用水平 `flowchart LR` 並於各 `subgraph` 內設 `direction TB`，避免畫面拉成過長直條。完成：確定每張圖的類型與主軸方向。
2. **套用現代 Frontmatter 與原生主題切換**：以新版 YAML frontmatter（`---` 包裹 `config:`）宣告 `look: neo` 與間距參數，保留閱讀器深／淺色主題自動切換（Mermaid 11/12 官方配對 `default`↔`dark`、`redux-color`↔`redux-dark-color`、`neo`↔`neo-dark`，於 2026-11-23 核對官方 `docs/config/theming.md`）。完成：每個圖表區塊皆使用 YAML frontmatter，無任何寫死的 `theme` 或文字／背景色碼。
3. **為所有 `subgraph` 加上透明底與語意邊框**：每個 `subgraph <id>` 一律配對 `style <id> fill:transparent,stroke:<語意色>,stroke-width:1.5px`（延伸或虛線項目可加 `stroke-dasharray: 5 5`），消除暗黑模式預設紫色底與藍字標題撞色。完成：每個 `subgraph` 皆有對應的透明底色與語意邊框宣告。
4. **執行離線驗證腳本**：執行 `uv run <技能目錄>/scripts/lint_mermaid.py <目標檔案或目錄>`（若環境已裝 `mmdc`，加 `--check-mmdc` 驗證語法）；修完所有回報項目後重跑一次。完成：腳本回傳退出碼 `0` 且零錯誤。

## 規則

- **主題交給宿主自動切換**：把色彩與對比交給 GitHub／VS Code／Obsidian 原生深／淺色主題；禁止在 Markdown 圖表內寫死 `theme: 'base'`、`themeVariables` 色碼、`classDef`／`style` 的固定 `fill:#...` 或 `color:#...`（會鎖死切換並在暗黑模式導致黑字配黑底），改以 `fill:transparent` 與語意 `stroke` 區分層級。
- **使用 YAML frontmatter 取代舊指令**：版面與外觀設定一律寫在頂端 `---` `config:` 區塊（如 `look: neo`、`flowchart.curve: basis`），不用已過時的 `%%{init: ...}%%`。
- **節點標籤含特殊字元時加雙引號**：標籤內含括號、方括號、冒號或全形符號時以 `"..."` 包裹，避免解析失敗。
- **時序圖不加零碎 `rect` 色塊**：需要步驟編號時直接加 `autonumber`，不用參差不齊的 `rect rgb(...)` 填色（在暗黑模式會形成破碎白塊）；分支改用原生 `alt`／`else`。
- **需要固定品牌色票時改用靜態雙圖**：若文件必須呈現精確品牌色而非跟隨主題，輸出深／淺兩張 SVG 並以 HTML `<picture>` 與 `prefers-color-scheme` 切換（見 [references/patterns.md](references/patterns.md)）。
