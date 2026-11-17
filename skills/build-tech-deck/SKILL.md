---
name: build-tech-deck
description: >-
  以 python-pptx 與宣告式 YAML 規格（deck.yml）生成高密度技術簡報（PPTX）：白底細線圓角、藍綠琥珀玫紅語義色票（品牌讀 Quarto 的 brand.yml）、真正的 PPTX 範本與具名版面、圖表、大數字與實際畫面截圖區塊、單行不折行與白話命名，附可執行的範本與零折行 lint。
  用於製作、重排或美化技術提案、專題報告、工程架構與客戶說明投影片，把實際畫面截圖放進簡報，更換品牌色或作者，或修正既有簡報的換行雜亂、孤字、折行檢查回報、配色不一致、內容口語不聚焦與代碼名稱外露。
compatibility: 需要 uv（python-pptx、pillow、lxml、pyyaml 由 uv 依 pyproject 安裝）；`--pdf` 與 `preview` 需 macOS 的 PowerPoint（預覽另需 poppler），其餘平台只出 .pptx。
license: MIT
---

# 技術簡報排版（Tech Deck）

投影片是資訊密度的載體：白底、細線、圓角、顏色只表示語義。內容寫成宣告式規格（YAML），由引擎渲染，可重現、可 diff。

消費端 repo 的 `AGENTS.md` 若已定義簡報目錄、色票或字型，以該 repo 為準。

## 流程

1. **安裝範本**：把 [`assets/deck-template/`](assets/deck-template) 整個複製到專案（例如 `tools/deckstyle/`），再把其中的 `_brand.yml`（品牌）與 `_quarto.yml`（作者）複製到專案根（含 `.git` 的目錄）改成自己的。在要寫簡報的專案以 path 依賴引用並同步：`deckstyle = { path = "tools/deckstyle", editable = true }`，`uv sync`。三份宣告各管什麼、品牌的色票名稱約定見 [references/declarations.md](references/declarations.md)。
2. **建簡報**：`uv run deckstyle new deck/` 複製範例（`deck.yml` 與 `screens/`），只改 `deck.yml`：封面欄位加每頁一筆 `{ref, title, blocks, notes}`，範例涵蓋全部區塊與分隔頁、結語頁，替換內容、刪掉不用的頁。要改顏色與字型改 `_brand.yml`，要改作者改 `_quarto.yml`，不在 `deck.yml` 重複寫。
3. **建置**：`uv run deckstyle build deck/`（`--pdf` 另以 PowerPoint 匯出向量 PDF）。建置先驗證整份規格，欄位寫錯會指出頁碼與區塊，再自動跑零折行與白話命名檢查。
4. **lint**：有違規就改寫該行文字，不是調字級，重跑到通過。檢查既有的 .pptx（不限引擎建的）：`uv run <技能路徑>/scripts/lint.py x.pptx --deny 倉庫名,服務代號`。
5. **目視**：`uv run deckstyle preview deck/`（`--watch` 邊改邊看）轉成逐頁 PNG 與接觸表，逐頁看；沒有 PowerPoint 就自己轉 PDF 或圖片。lint 以字寬估算，字型與應用程式不同會有差異。

規格是單一真值源；不在 PowerPoint 裡手動拖曳。要用程式算數字的頁面，由專案腳本產生 `deck.yml`，或直接呼叫 `deckstyle.engine.build`；引擎不執行規格檔裡的程式。

## 設計原則

- **語義色票**：`blue` 資料與結構、`green` 系統確定、`amber` 只給候選、`red` 須人判斷或失敗、`gray` 中性，`dark`／`solid_dark` 墨色強調。規格只寫 `kind` 名稱，不寫色碼；色票只在 `_brand.yml`。配色、幾何與版式選擇見 [references/style.md](references/style.md)。
- **單行不折行**：標題、卡片、表格每行都要放得進一行；孤字（折行後末行只剩 3–4 字）一律改寫。各版面的字數上限與區塊欄位見 [references/patterns.md](references/patterns.md)。
- **內容結構**：「**四字粗體標籤**：精煉說明」，或「現象／後果」兩層；剔除口語贅字，只留作業現象、數據與管理後果。一頁一個結論，主標題寫結論句。
- **畫面用實際截圖**：用 `shots` 放示範資料的實際截圖，不手繪、不用生成的假畫面；做不到的狀態在頁面寫明，不補假圖。
- **不標進度**：頁面與講稿只描述完成後的長相，不寫「規劃中」「目標流程」「尚未實作」「待核對」；程式現況與待核對事項寫在維護者看的文件。研究與評估報告的限制與未竟之處是內容，照寫。
- **白話命名**：投影片與講稿備註不顯示倉庫名稱與代碼名稱（服務代號、路徑、設定鍵、資料表與欄位、檔名），改成白話的功能名稱。
- **講稿分流**：鋪陳、背景與口頭引導寫進備註（每頁的 `notes`），投影片只留骨架、數據與圖形；數字標明是實測、示例或估算。
- **版心**：16:9（13.333 × 7.50 in）；內容區上緣 1.70 in、下緣 6.85 in，頁尾線在 7.00（`design.yml` 的 `layout`，不在規格裡調）。

## 規則

- 標題、章節標籤、頁尾與頁碼是版面的佔位符，不手畫文字方塊；外觀改 `_brand.yml` 或範本的母片，不在規格裡逐頁調。
- 連線標籤的文字框一律透明，不用白底方塊蓋住泳道。
- 表格明確設定 `col-w` 欄寬比例；儲存格可寫 `[文字, green]`（`green`、`red`、`blue`、`amber`）做語義高亮。
- 圖片、圖表與表格有替代文字（`shots` 的 `alt` 可自訂）；所有文字標語言（`lang`）。
- lint 沒通過、或沒逐頁看過渲染結果，不回報完成。
- 需要新區塊時，依 [references/patterns.md](references/patterns.md) 的擴充守則在引擎加區塊，並同步更新範例與測試。
- 驗證本技能的腳本與範本：`bash scripts/test.sh`。
