---
name: tech-deck
description: >-
  以 python-pptx 宣告式規格生成高密度技術簡報（PPTX）：白底極簡、語義色票、單行不折行，附可執行的範本與零折行 lint。
  用於製作、重排或美化技術提案、專題報告、工程架構投影片，或修正既有簡報的換行雜亂、孤字、內容口語不聚焦。
compatibility: 需要 uv（或 python3 加 python-pptx）；轉 PDF 逐頁目視需 PowerPoint、Keynote 或 LibreOffice。
license: MIT
---

# 技術簡報排版（Tech Deck）

投影片是資訊密度的載體：白底、直角細線、單一語義強調色。內容寫成宣告式規格，由引擎渲染，可重現、可 diff。

消費端 repo 的 `AGENTS.md` 若已定義簡報目錄、色票或字型，以該 repo 為準。

## 流程

1. **複製範本**：把 [`assets/deck-template/`](assets/deck-template) 整個複製到專案的簡報目錄（`theme.py`、`deck_engine.py`、`deck_spec.py`、`build_deck.py`）。
2. **只改 `deck_spec.py`**：每頁一筆 `(分類標籤, 主標題, [(原語, 欄位)], 講稿備註)`。範本三頁各示範不同原語，替換內容、刪掉不用的頁。
3. **建置**：`uv run build_deck.py out.pptx`（`python-pptx` 由檔頭的 inline 依賴自動安裝）。
4. **跑零折行檢查**：`uv run <技能路徑>/scripts/lint_wrap.py out.pptx`。有違規就改寫該行文字（不是調字級），重跑到通過。
5. **目視**：轉 PDF 或圖片逐頁看。lint 以字寬估算，字型與應用程式不同會有差異；改版後第二輪再確認。

規格是單一真值源；不在 PowerPoint 裡手動拖曳。

## 設計原則

- **語義色票**：墨黑 `#111111` 是標題與內文；強調綠 `#76B900`（字用 `#5A8F00`）只表示正面與確定；警戒紅 `#B91C1C` 表示攔截、痛點與違規；灰階放次要資訊；虛線灰框表示待判斷。色票全在 `theme.py`。
- **單行不折行**：標題、卡片、表格每行都要放得進一行；孤字（折行後末行只剩 3–4 字）一律改寫。各版面的字數上限見 [references/patterns.md](references/patterns.md)。
- **內容結構**：「**四字粗體標籤**：精煉說明」，或「現象／後果」兩層；剔除口語贅字，只留作業現象、數據與管理後果。
- **講稿分流**：鋪陳、背景與口頭引導寫進備註（規格的第四欄），投影片只留骨架、數據與圖形。
- **版心**：16:9（13.333 × 7.50 in）；內容寬 11.73 in，上緣 `T.TOP = 1.70`，安全底線 `T.BOTTOM = 6.60`，頁尾線在 7.00。

## 已實作的原語

`cards`（水平語義卡片列）、`table`（首列黑底、奇偶交錯、`(文字, "green"|"red")` 語義高亮）、`steps`（序號步驟）、`columns`（頂線標題＋條列）、`banner`（全寬主張框）、`note`（底部單行總結，釘在安全底線）。各自的欄位見 `deck_engine.py` 的 docstring。

需要流程圖或圖文並排時，依 [references/patterns.md](references/patterns.md) 的擴充守則在引擎加原語，並同步更新範本與測試。

## 規則

- 連線標籤的文字框一律透明，不用白底方塊蓋住泳道。
- 表格明確設定 `col_w` 欄寬比例；儲存格邊距已在引擎內統一。
- lint 沒通過、或沒逐頁看過渲染結果，不回報完成。
- 驗證本技能的腳本：`bash scripts/test.sh`。
