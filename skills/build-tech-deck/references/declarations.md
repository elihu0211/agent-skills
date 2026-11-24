# 宣告：品牌、作者、簡報內容與設計參數

簡報由四份宣告決定外觀與內容，各管一件事，都用官方或通行的格式，沒有自訂的設定語言。範本的實作在 [`assets/deck-template/`](../assets/deck-template)。

## 目錄

1. [四份宣告](#四份宣告)
2. [品牌：`_brand.yml`](#品牌_brandyml)
3. [作者與中繼資料：`_quarto.yml`、`_metadata.yml`](#作者與中繼資料_quartoyml_metadatayml)
4. [簡報內容：`deck.yml`](#簡報內容deckyml)
5. [設計參數：`design.yml`](#設計參數designyml)

## 四份宣告

| 要宣告什麼 | 檔案 | 格式 |
| :--- | :--- | :--- |
| 品牌：色票、語義色、字型 | 專案根的 `_brand.yml` | Quarto 的 [brand.yml](https://quarto.org/docs/authoring/brand.html) |
| 作者、日期、語言、lint 名單 | 專案根的 `_quarto.yml`，往下各層的 `_metadata.yml` | Quarto 的專案中繼資料，同一套分層合併規則 |
| 簡報內容 | 簡報目錄的 `deck.yml` | YAML（1.2 的布林），鍵用 kebab-case，附 JSON Schema |
| 版面、字級、區塊高度、lint 門檻 | 引擎內的 `deckstyle/design.yml` | YAML，載入時逐項驗證 |

品牌與作者讓 Quarto 文件與簡報讀同一份，顏色、字型與署名不必維護兩套。引擎沒有全域設定：每個繪圖函式明確收一個不可變的 `Theme`，品牌由簡報目錄往上搜尋，不同目錄的簡報可以有不同品牌。

## 品牌：`_brand.yml`

搜尋規則同 Quarto：從簡報目錄往上第一份 `_brand.yml`（或 `_brand/_brand.yml`），到含 `.git` 的專案根為止；找不到就報錯並說明該放哪。

引擎對色票名稱有約定，缺了簡報畫不出來，載入時就擋（`deckstyle/brand.py`）：

- `color.palette`：`ink`、`white`；色族 `slate`（另需 `-lite`、`-mute`、`-rule`、`-wash`）；色族 `blue`、`green`、`amber`、`rose`（各需 `-lite`、`-text`）。值寫 `"#RRGGBB"`。
- 語義色：`foreground`、`background`、`primary`、`secondary`、`tertiary`、`success`、`warning`、`danger`、`light`、`dark`、`link`，寫色票名稱或 `#RRGGBB`。
- `typography.base`：字型家族（PPTX 只能引用檢視端已安裝的字型；macOS 用 PingFang TC，Windows 改 Microsoft JhengHei）。

品牌同時寫進 PPTX 的佈景主題：`dk1`＝foreground、`lt1`＝background、`accent1`＝primary、`accent2`＝success、`accent3`＝warning、`accent4`＝danger、`accent5`＝secondary、`accent6`＝tertiary，PowerPoint 的色票與字型選單就是品牌色與品牌字型。`deckstyle template -o brand.pptx` 輸出空的品牌範本，在 PowerPoint 裡手工做頁面時用同一套主題、母片與版面。

## 作者與中繼資料：`_quarto.yml`、`_metadata.yml`

規則與 Quarto 相同：越靠近文件的優先；物件逐鍵合併、陣列串接、純量由較近的一層覆蓋。

```text
<專案根>/_quarto.yml            專案層：全專案共用的作者與單位
<專案根>/<目錄>/_metadata.yml   目錄層：這個目錄要加的作者（選用，可再往下一層）
<簡報目錄>/deck.yml             文件層：deck.yml 裡的 author、date、lang、lint 最後合併
```

作者用 Quarto 的結構寫法，封面印「單位 姓名」：

```yaml
author:
  - name: 範例作者
    affiliation: 範例單位   # 字串或清單；也可寫 affiliations: [..., {name: ...}]
```

- 簡報讀 `author`、`date`、`lang`、`lint`；Quarto 自己的鍵（`project`、`format`、`bibliography`…）與作者的其他欄位（`email`、`orcid`…）忽略。
- 搜尋範圍是簡報目錄往上到含 `.git` 的目錄；找不到就只看簡報目錄自己，不會誤讀無關的上層檔案。
- 陣列是串接不是取代：下層加一位作者是在上層作者後面加人（小組報告用），同名的作者合併成一位；相鄰且單位相同的作者併成一組：`範例單位 作者甲　作者乙`。
- `lang` 預設 `zh-TW`，標在所有文字與文件屬性。`lint.deny`／`lint.allow` 是白話命名檢查的專案專屬名單，也可以放在這幾層。
- `uv run deckstyle inspect deck/` 列出參與合併的檔案與合併後的結果。

### 在 deck.yml 取用其他鍵：`{{< meta 鍵 >}}`

課程名稱、專案代號這類每份簡報都會出現、又不該各寫一次的值，寫在分層設定裡，deck.yml 用 Quarto 官方的 meta 短代碼取用：

```yaml
# <課程>/_metadata.yml
course-name: 範例課程

# <課程>/deck/deck.yml（含短代碼的值要加引號，否則 YAML 把 { 當成對應表）
category: "{{< meta course-name >}}｜期末報告"
```

- 取的是 `_quarto.yml`／`_metadata.yml` 分層合併後的任一個鍵（不限上面四個），鍵照 YAML 原樣，`a.b` 取巢狀鍵；deck.yml 自己的鍵不是來源。
- 任何字串欄位都可用（`category`、頁面的 `ref`、區塊文字…），建置、大綱、預覽與 lint 看到的都是換好的文字。
- `{{< meta author >}}` 是例外：作者是清單，取用時排成封面預設的作者行（「單位 姓名」，含 deck.yml 自己加的作者）。要在封面底部接上其他文字時用它，作者就不必在 `meta` 重寫一次：`meta: "{{< meta author >}}；指導教授 {{< meta advisor >}}"`。
- 找不到鍵或值不是字串、數字就報錯，不會把佔位字原樣印上投影片。

## 簡報內容：`deck.yml`

鍵用 kebab-case（`short-title`、`col-w`），讀進來後換成內部的 snake_case；只有一種寫法，沒有別名與相容形式。

- 最上層：`title`、`subtitle`、`category`、`short-title`、`slides` 必填；`output-file`、`meta`（封面底部，預設印作者）、`notes`（封面講稿）選填；`author`、`date`、`lang`、`lint` 可來自分層設定。
- 每頁是一個 mapping：`type`（`content` 預設、`divider`、`closing`）、`ref`、`title`、`sub`、`meta`、`notes`，內容頁另有 `blocks`；每個區塊是 `{block: 名稱, ...欄位}`，表格儲存格的語義高亮寫成 `[文字, green]`。
- YAML 的布林只認 `true`／`false`（YAML 1.2，同 Quarto）：`no`、`on` 不會被吃成布林。
- 引擎不執行規格檔。要用程式算數字的頁面，寫一支專案腳本產生 `deck.yml`，或直接呼叫 `deckstyle.engine.build(spec, out, base_dir, theme)`。
- 編輯器補全與即時驗證：`uv run deckstyle schema spec -o spec.schema.json`，在 `deck.yml` 檔頭加 `# yaml-language-server: $schema=spec.schema.json`。schema 與建置時的驗證出自同一份欄位表。
- 圖片路徑相對於簡報目錄，缺檔就停，不留空框。

## 設計參數：`design.yml`

版面（版心、區塊間距、頁尾）、頁框幾何（各種頁面的標題與裝飾線位置）、字級、區塊高度上限、轉場、頁尾開關、線寬與圓角、lint 門檻。載入時逐項驗證：缺鍵、未知鍵、型別與版面關係（`left < right`、`side-w + side-gap` 小於內容寬…）不合就停下並指出位置。改這裡就改全部簡報，改完重建要交付的簡報，並重測字數上限（見 [patterns.md](patterns.md)）。
