# 版面字數上限、區塊欄位與擴充守則

可執行的程式碼在 [`assets/deck-template/`](../assets/deck-template)，本檔只放數值、欄位與擴充規則。三份宣告見 [declarations.md](declarations.md)，版面與配色見 [style.md](style.md)。

## 目錄

1. [字數上限速查表](#字數上限速查表)
2. [區塊欄位速查](#區塊欄位速查)
3. [規格撰寫範式](#規格撰寫範式)
4. [引擎分層](#引擎分層)
5. [範本：佈景主題、母片、版面](#範本佈景主題母片版面)
6. [擴充區塊的守則](#擴充區塊的守則)

## 字數上限速查表

數值由零折行 lint 以預設安全係數 0.8 實測（全形 1.0 em、半形 0.55 em、粗體多估 5%），對象是範本引擎的預設邊距與字級；每格是「單行放得進去的全形字數」。範本的 `tests/test_limits.py` 逐格驗證「上限放得進、多一字被抓到」，改了字級、邊距或欄寬會失敗，提醒同步更新本表。

| 版面 | 每行上限（全形） | 超過的後果 |
| :--- | :---: | :--- |
| 主標題 | 24 | 折行或壓到版心外 |
| `note` 單行 | 46 | 壓迫頁尾線 |
| `banner` 標題／內文 | 38／48 | 折行 |
| `cards` 2 欄（含條列符號） | 20 | 長句破壞整齊 |
| `cards` 3 欄 | 12 | 末尾 1–4 字落單成孤字 |
| `cards` 4 欄 | 10 | 多行破碎 |
| `cards` 5 欄 | 7 | 多行破碎 |
| `columns` 2 欄／3 欄 | 21／14 | 長句自然斷開 |
| `flow` 3／4／5／6 個節點的標題 | 12／8／7／6 | 標題折行 |
| `flow` 3／4／5／6 個節點的內文 | 16／11／9／7 | 內文折行 |
| `table` 3／4／5 欄的儲存格 | 15／11／9 | 儲存格折行，列高被撐開 |

內文放不進一行時，先縮短文字或拆成「標籤＋說明」，不是調小字級；多的移進講稿備註。標題以明確換行排成兩行時，各行分開估寬，每行各自守上限；表格儲存格與文字框裡以 `\n` 分行的文字也一樣，各行各自守上限。

## 區塊欄位速查

鍵用 kebab-case（`col-w`、`arch-graph`）。每頁的區塊是 `{block: 名稱, ...欄位}`。`kind` 只用語義名稱（`gray`、`white`、`blue`、`green`、`amber`、`red`、`dark`、`solid_dark`，語義色另有 `_fill` 淡底版），不寫色碼。帶 `h`（英吋）的區塊固定高度，其餘均分剩餘高度；`note` 釘在底部，單一區塊的頁面垂直置中。

| 區塊 | 用在 | 主要欄位 |
| :--- | :--- | :--- |
| `banner` | 全寬主張或核心問題 | `kind`、`title`、`body`、`h` |
| `cards` | 並列的語義卡片 | `items[{kind,title,body}]`、`h`、`bullet` |
| `kpi` | 大數字列 | `items[{value,label,sub,kind}]` |
| `chart` | 原生圖表（可在 PowerPoint 編輯資料） | `type`（`column`、`bar`、`line`、`pie`）、`categories`、`series[{name,values,kind}]`、`fmt`、`legend`、`labels`、`vmin`、`vmax`、`side` |
| `steps` | 大號序號的步驟或摘要數字 | `items[{num,title,body}]` |
| `columns` | 頂線標題加短條列（對比、結論） | `cols[{title,kind,items}]` |
| `flow` | 水平流程與管線 | `items[{kind,title,body}]`、`caption`、`numbered`、`edge-labels`、`h` |
| `swimlane` | 跨角色時序 | `lanes[{name,sub}]`、`steps[{lane,title,sub,kind,edge}]`、`thesis` |
| `arch-graph` | 系統拓撲、狀態圖 | `nodes[{id,col,row,kind,title,en,sub}]`、`edges[{from,to,kind,label}]`、`cols`、`rows`、`col-headers`、`zones`、`side-thesis` |
| `timeline-diagram` | 多軌時間軸 | `tracks[{title,phases[{time,kind,title,body}]}]` |
| `bench-chart` | 量化長條圖加論證面板 | `groups[{title,bars[{label,ratio,value,kind}]}]`、`thesis` |
| `table` | 比較與對照 | `rows`、`col-w`、`aligns`、`highlight`、`h`（高度上限）；儲存格可寫 `[文字, green]` |
| `layers` | 分層金字塔（責任分界） | `tiers[{name,sub,kind,title,body}]`、`left-w` |
| `shots` | 實際畫面截圖列 | `items[{image,title,body,alt,crop}]`、`side`、`side-w`、`cap-h` |
| `references` | 參考文獻（書目自動折行、懸掛縮排） | `items`（每筆一個字串）、`title`、`size` |
| `note` | 底部一行總結（對策、取捨） | `lines` |

邊的 `kind`：`forward`（一般）、`green`（確定）、`dashed`（候選）、`blocked`（攔截，帶 ✕）。`arch-graph` 的節點兩行副標在 `rows: 4` 時會頂到框外，列數多就寫單行；`zones` 的標題會壓到第一列節點，自己留一列。節點的 `en` 是標題下一行小字英文（中英並列的專有名詞），整張圖要嘛每個節點都寫、要嘛都不寫；有 `en` 的節點副標寫一行。

表格列高依內容估算：首列（欄名）緊湊，只留字高加少許上下空白；內容列單行的等高，儲存格以 `\n` 分成兩三行的列自動撐高，總高照實際列高加總，置中與結論列位置都算得準；放不進可用高度時建置報錯，不會壓到結論列。`references` 的書目照原文寫成一整行，不要手動斷行：折在哪裡交給 PowerPoint，零折行檢查不管這個區塊；字串裡有半形逗號，YAML 要用 `- "..."` 逐行寫或整段加引號，不要寫進方括號清單。完整欄位表在引擎的 `deckstyle/spec.py`（`BLOCK_SCHEMA`），`deckstyle schema spec` 輸出同一份的 JSON Schema。

## 規格撰寫範式

```yaml
slides:
  - ref: 02 架構
    title: 三層架構：現場掃碼、雲端判定、資料留存
    blocks:
      - {block: arch-graph, cols: 3, rows: 2, nodes: [...], edges: [...]}
      - {block: note, lines: [規則只在雲端一份]}
    notes: 講稿
  - {type: divider, title: 系統怎麼運作, sub: 架構、流程與跨角色時序}
  - {type: closing, title: 謝謝，歡迎提問, meta: 聯絡方式}
```

- 卡片內文三行為宜，每行「**標籤**：說明」；標籤四字。
- 表格首列是欄名；儲存格只寫短詞，需要高亮才用 `[文字, kind]`。
- 一頁一個結論：主標題寫結論句，不寫主題名。
- `note` 放對策或取捨，一行結束；多的話進講稿備註。
- 圖說用白話描述畫面，不寫路徑與代號；數字標明是實測、示例或估算，未驗證的部分也要寫出來。

## 引擎分層

用語：規格裡的 `{block: …}` 叫**區塊**（`blocks.py`、`BLOCKS`）；`draw.py` 的文字、線、卡片這些繪製動作叫**繪圖原語**。繪圖函式與區塊的第一個參數都是 `t: Theme`，沒有模組層級的全域設定。

| 檔案 | 職責 | 何時改 |
| :--- | :--- | :--- |
| `brand.py`、`design.py`、`design.yml` | 讀品牌（`_brand.yml`）與設計參數並驗證 | 改約定的色票名稱、版面或字級 |
| `theme.py` | 品牌加設計參數組成不可變的 `Theme`（色、卡片樣式、線寬） | 新增 `kind` |
| `draw.py` | 繪圖原語：文字、線、圓角卡片、徽章、表格框線 | 新的畫法 |
| `blocks.py` | 區塊與其高度規劃，`BLOCKS` 把區塊名對到函式 | 新增區塊 |
| `template.py` | 由 `Theme` 產生真正的 PPTX 範本：佈景主題、母片、六個具名版面 | 新增版面、換母片結構 |
| `engine.py` | 逐頁版面配置（`Deck`）與由規格產出整份簡報（`render`、`build`） | 版型變動 |
| `spec.py`、`schema.py` | 規格的欄位表與驗證、由同一份欄位表產生 JSON Schema | 規格欄位變動 |
| `config.py`、`yamlio.py` | 讀 `_quarto.yml`／`_metadata.yml` 的分層合併；YAML 1.2 載入 | 分層規則變動 |
| `lint.py`、`outline.py`、`preview.py`、`export.py`、`cli.py` | 零折行與白話命名、規格轉 Markdown 大綱、逐頁預覽與監看、PDF 匯出、命令列 | 工具變動 |

`spec.py`、`design.py`、`config.py`、`outline.py`、`schema.py`、`yamlio.py` 不匯入 python-pptx，沒有簡報套件的環境（守門）也載得進來；測試會檢查。

## 範本：佈景主題、母片、版面

與 Quarto、pandoc 的 `reference-doc` 同一個模型：範本是一份 `.pptx`，版面以名稱找，內容放進版面的佔位符。標題、章節標籤、頁尾與頁碼是佔位符，不是文字方塊，所以大綱檢視、閱讀順序、「重設投影片」與換佈景主題都照 PowerPoint 的規矩運作；頁碼是欄位，換頁序自動更新。

| 版面 | 佔位符 idx | 說明 |
| :--- | :--- | :--- |
| `Title Slide` | 標題 0、副標 1、類別 13、底部說明 14 | 封面，沒有頁尾；底部說明預設印作者 |
| `Title Only` | 標題 0、章節標籤 13、頁尾 11、頁碼 12 | 內容頁；內容區是自由畫布，區塊畫在上面 |
| `Section Header` | 標題 0、說明 1、章節標籤 13、頁尾與頁碼 | 章節分隔頁（`type: divider`） |
| `Closing` | 標題 0、副標 1、底部說明 14 | 結語頁（`type: closing`） |
| `Title and Content`、`Blank` | Office 慣例 | 名稱與 Quarto、pandoc 查的相同，範本可直接當它們的 `reference-doc`，也供在 PowerPoint 手工加頁 |

- 配色與字型進佈景主題的槽（見 [declarations.md](declarations.md)「品牌」），在 PowerPoint 新增形狀與圖表也用這組色；文字不在每個 run 寫字型名稱，由佈景主題決定。
- 換外觀：改 `_brand.yml`（顏色與字型）或 `design.yml`（版面）；或 `uv run deckstyle template -o 範本.pptx` 匯出空範本在 PowerPoint 手工做頁面。
- 零折行 lint 會解析佔位符從版面與母片繼承的字級、粗體與內距，標題也檢查。
- 無障礙：每頁標題是標題佔位符；圖片、圖表與表格有替代文字；文字標 `lang`。

## 擴充區塊的守則

引擎目前的區塊如上表。要加新的區塊時，同步改這幾處並在範例加一頁示範；測試會在任一處漏掉時失敗：

1. `blocks.py`：函式簽章 `(t, slide, y, height=…, **欄位) -> 佔用高度`，登記進 `BLOCKS`；高度要特別算時補 `planned_height`。
2. `spec.py`：`BLOCK_SCHEMA` 的欄位表（必填、選填、`kind` 欄位、列舉）。
3. `schema.py`：欄位型別沒列在 `_TYPES` 的就補上（沒補只是編輯器不檢查該欄型別）。
4. `outline.py`：`_block` 加一個分支。
5. `deckstyle/template/deck.yml`：加一頁示範。

其餘規則：

- 顏色、字型、圓角、線寬一律取自 `Theme`（品牌來自 `_brand.yml`，其餘來自 `design.yml`），不在區塊內寫死色碼（測試會擋）；連線標籤的文字框透明，直角連線。
- 圖片放在消費端專案，引擎只收路徑，不內嵌二進位資料；缺檔要在建置時停下。
- 改了引擎行為就跑 `tests/test_limits.py`，字數上限表跟著更新。
- 改執行期依賴前，先想用到這個引擎的專案的鎖定檔會跟著變。
