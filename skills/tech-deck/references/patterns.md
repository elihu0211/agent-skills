# 版面字數上限、原語欄位與擴充守則

可執行的程式碼在 [`assets/deck-template/`](../assets/deck-template)，本檔只放數值、欄位與擴充規則。版面與配色見 [style.md](style.md)。

## 目錄

1. [字數上限速查表](#字數上限速查表)
2. [原語欄位速查](#原語欄位速查)
3. [規格撰寫範式](#規格撰寫範式)
4. [擴充原語的守則](#擴充原語的守則)

## 字數上限速查表

數值由 `scripts/lint_wrap.py` 以預設安全係數 0.8 實測（全形 1.0 em、半形 0.55 em、粗體多估 5%），對象是範本引擎的預設邊距與字級；每格是「單行放得進去的全形字數」。

| 版面 | 每行上限（全形） | 超過的後果 |
| :--- | :---: | :--- |
| 主標題 | 25 | 折行或壓到版心外 |
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

改字級、邊距或欄寬後，這些值會變；以 lint 實測為準，不要照表硬套。內文放不進一行時，先縮短文字或拆成「標籤＋說明」，不是調小字級；多的移進講稿備註。

## 原語欄位速查

規格每頁是 `(章節標籤, 主標題, [(原語, 欄位)], 講稿備註)`。`kind` 只用語義名稱（`gray`、`white`、`blue`、`green`、`amber`、`red`、`dark`、`solid_dark`，語義色另有 `_fill` 淡底版），不寫色碼。帶 `h`（英吋）的區塊固定高度，其餘均分剩餘高度；`note` 釘在底部。

| 原語 | 用在 | 主要欄位 |
| :--- | :--- | :--- |
| `banner` | 全寬主張或核心問題 | `kind`、`title`、`body`、`h` |
| `cards` | 並列的語義卡片 | `items[{kind,title,body}]`、`h`、`bullet` |
| `steps` | 大號序號的步驟或摘要數字 | `items[{num,title,body}]` |
| `columns` | 頂線標題加短條列（對比、結論） | `cols[{title,kind,items}]` |
| `flow` | 水平流程與管線 | `items[{kind,title,body}]`、`caption`、`numbered`、`edge_labels`、`h` |
| `swimlane` | 跨角色時序 | `lanes[{name,sub}]`、`steps[{lane,title,sub,kind,edge}]`、`thesis` |
| `arch_graph` | 系統拓撲、狀態圖 | `nodes[{id,col,row,kind,title,sub}]`、`edges[{from,to,kind,label}]`、`cols`、`rows`、`col_headers`、`zones`、`side_thesis` |
| `timeline_diagram` | 多軌時間軸 | `tracks[{title,phases[{time,kind,title,body}]}]` |
| `bench_chart` | 量化長條圖加論證面板 | `groups[{title,bars[{label,ratio,value,kind}]}]`、`thesis` |
| `table` | 比較與對照 | `rows`、`col_w`、`h`；儲存格可寫 `(文字, "green"\|"red"\|"blue"\|"amber")` |
| `layers` | 分層金字塔（責任分界） | `tiers[{name,sub,kind,title,body}]`、`left_w` |
| `shots` | 實際畫面截圖列 | `items[{image,title,body,crop}]`、`side`、`side_w`、`cap_h` |
| `note` | 底部一行總結（對策、取捨） | `lines` |

邊的 `kind`：`forward`（一般）、`green`（確定）、`dashed`（候選）、`blocked`（攔截，帶 ✕）。`arch_graph` 的節點兩行副標在 `rows=4` 時會頂到框外，列數多就寫單行；`zones` 的標題會壓到第一列節點，自己留一列。

## 規格撰寫範式

- 卡片內文三行為宜，每行「**標籤**：說明」；標籤四字。
- 表格首列是欄名；儲存格只寫短詞，需要高亮才用 `(文字, kind)`。
- 一頁一個結論：主標題寫結論句，不寫主題名。
- `note` 放對策或取捨，一行結束；多的話進講稿備註。
- 圖說用白話描述畫面，不寫路徑與代號；數字標明是實測、示例或估算，未驗證的部分也要寫出來。

## 擴充原語的守則

引擎目前的原語如上表。要加新的版面時：

1. 簽章維持 `(slide, y, height=…, **規格欄位) -> 佔用高度`，並登記進 `BLOCKS`（`PRIMITIVES` 是同一個字典）。
2. 顏色、字型、圓角、線寬一律取自 `theme.py`（再取自 `tokens.toml`），不在原語內寫死色碼；連線標籤的文字框透明，直角連線，線寬取 `LINE_*`。
3. 在 `deck_spec.py` 範本加一頁示範；`scripts/test_lint.py` 的 `test_every_primitive_is_exercised_by_sample` 會在範本漏掉原語時失敗，並補上對應測試。
4. 圖片放在消費端專案，引擎只收路徑，不內嵌二進位資料；缺檔要在建置時停下。
5. 改了引擎行為就重測上面的字數上限表。
