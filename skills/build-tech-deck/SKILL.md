---
name: build-tech-deck
description: >-
  以 python-pptx 宣告式規格生成高密度技術簡報（PPTX）：白底細線圓角、藍綠琥珀玫紅語義色票、圖表與實際畫面截圖區塊、單行不折行與白話命名，附可執行的範本與零折行 lint。
  用於製作、重排或美化技術提案、專題報告、工程架構與客戶說明投影片，把實際畫面截圖放進簡報，或修正既有簡報的換行雜亂、孤字、lint_wrap 回報折行、配色不一致、內容口語不聚焦與代碼名稱外露。
compatibility: 需要 uv（或 python3 加 python-pptx、pillow）；轉 PDF 逐頁目視需 PowerPoint、Keynote 或 LibreOffice，`--pdf` 僅 macOS 的 PowerPoint。
license: MIT
---

# 技術簡報排版（Tech Deck）

投影片是資訊密度的載體：白底、細線、圓角、顏色只表示語義。內容寫成宣告式規格，由引擎渲染，可重現、可 diff。

消費端 repo 的 `AGENTS.md` 若已定義簡報目錄、色票或字型，以該 repo 為準。

## 流程

1. **複製範本**：把 [`assets/deck-template/`](assets/deck-template) 整個複製到專案的簡報目錄（引擎、`tokens.toml`、`defaults.toml`、`deck_spec.py`、`build_deck.py`、`screens/`；各檔職責見 [references/patterns.md](references/patterns.md)「引擎分層」）。
2. **只改 `deck_spec.py`**：`SPEC` 含封面與每頁一筆 `(章節標籤, 主標題, [(區塊, 欄位)], 講稿備註)`。範本十一頁涵蓋全部區塊，替換內容、刪掉不用的頁。要改色票改 `tokens.toml`，不改 `theme.py`；封面作者預設在 `defaults.toml`。
3. **建置**：`uv run build_deck.py out.pptx`（`--pdf` 另以 PowerPoint 匯出向量 PDF；`--emit-template` 匯出範本、`--template` 用自己編輯過母片的範本）。
4. **跑兩支 lint**：`uv run <技能路徑>/scripts/lint_wrap.py out.pptx`（零折行）與 `uv run <技能路徑>/scripts/lint_names.py out.pptx`（白話命名；專案的倉庫與服務代號用 `--deny` 帶入）。有違規就改寫該行文字，不是調字級，重跑到通過。
5. **目視**：轉 PDF 或圖片逐頁看。lint 以字寬估算，字型與應用程式不同會有差異。

規格是單一真值源；不在 PowerPoint 裡手動拖曳。

## 設計原則

- **語義色票**：`blue` 資料與結構、`green` 系統確定、`amber` 只給候選、`red` 須人判斷或失敗、`gray` 中性，`dark`／`solid_dark` 墨色強調。規格只寫 `kind` 名稱，不寫色碼；色票只在 `tokens.toml`。配色、幾何與版式選擇見 [references/style.md](references/style.md)。
- **單行不折行**：標題、卡片、表格每行都要放得進一行；孤字（折行後末行只剩 3–4 字）一律改寫。各版面的字數上限與區塊欄位見 [references/patterns.md](references/patterns.md)。
- **內容結構**：「**四字粗體標籤**：精煉說明」，或「現象／後果」兩層；剔除口語贅字，只留作業現象、數據與管理後果。一頁一個結論，主標題寫結論句。
- **畫面用實際截圖**：用 `shots` 放示範資料的實際截圖，不手繪、不用生成的假畫面；做不到的狀態在頁面寫明，不補假圖。
- **不標進度**：頁面與講稿只描述完成後的長相，不寫「規劃中」「目標流程」「尚未實作」「待核對」；程式現況與待核對事項寫在維護者看的文件。研究與評估報告的限制與未竟之處是內容，照寫。
- **白話命名**：投影片與講稿備註不顯示倉庫名稱與代碼名稱（服務代號、路徑、設定鍵、資料表與欄位、檔名），改成白話的功能名稱。
- **講稿分流**：鋪陳、背景與口頭引導寫進備註（規格的第四欄），投影片只留骨架、數據與圖形；數字標明是實測、示例或估算。
- **版心**：16:9（13.333 × 7.50 in）；內容寬 11.73 in，上緣 `T.TOP = 1.70`，安全底線 `T.BOTTOM = 6.60`，頁尾線在 7.00。

## 規則

- 標題、章節標籤、頁尾與頁碼是版面的佔位符，不手畫文字方塊；外觀改 `tokens.toml` 或範本的母片，不在規格裡逐頁調。
- 連線標籤的文字框一律透明，不用白底方塊蓋住泳道。
- 表格明確設定 `col_w` 欄寬比例；儲存格可寫 `(文字, "green"|"red"|"blue"|"amber")` 做語義高亮。
- 兩支 lint 沒通過、或沒逐頁看過渲染結果，不回報完成。
- 需要新版面時，依 [references/patterns.md](references/patterns.md) 的擴充守則在引擎加區塊，並同步更新範本與測試。
- 驗證本技能的腳本：`bash scripts/test.sh`。
