---
name: guard-tikz-figures
description: >-
  把 .qmd／.tex 裡的每張 TikZ 圖單獨編譯（Quarto 專案沿用它的 LaTeX 前置），從 PDF 量出節點、連線與邊標籤的實際位置；節點互壓、連線穿過節點、label 蓋住節點或箭頭、字溢出節點、連線共線重疊或圖太寬，就列出位置與修法並以非零結束碼擋下；附 Claude Code hook 與建置、pre-push 接法。
  用於畫或修改 TikZ 的流程、架構、狀態與序列圖，修正 check.py 或 hook 回報的 node-overlap、edge-through-node、label-on-node、label-on-arrow、text-overflow 等問題，或替用 TikZ 的 LaTeX／Quarto 文件專案接上圖版面檢查時。
license: MIT
compatibility: 需要 uv（pymupdf、shapely 由腳本的 PEP 723 宣告安裝）與 TeX（xelatex 等，TeX Live 或 TinyTeX）；quarto 模式另需 Quarto。
---

# TikZ 圖版面守門（guard-tikz-figures）

`scripts/check.py` 把每張 `tikzpicture` 抽出來單獨編譯，量的是 PDF 裡真正畫出來的方框、線、箭頭和字，所以抓得到原始碼看不出的壓疊：標籤比線段長、菱形撐不住字、曲線切過別的節點。任何一條不過就以結束碼 1 擋下，訊息寫出檔案、行號、`\label{fig:…}`、相關節點的字與修法。守門是畫圖的回饋迴圈，不是畫完再補的檢查：每改一次圖就跑一次。

## 先讀

- 消費端 repo 的 `AGENTS.md`：它的建置指令、前置檔與圖的慣例優先於本技能。
- 修某一條訊息、想知道門檻與哪些情況不報：[references/rules.md](references/rules.md)。
- 接上建置檢查、pre-push、Claude Code hook，或需要 CLI 與 JSON 合約：[references/integration.md](references/integration.md)。

## 步驟

1. **照版面原則畫**：照下一節〈怎麼畫才不會壓疊〉寫圖。完成：每個節點都以相對定位或 `fit` 放置，每條線的走向都寫得出從哪個錨點到哪個錨點。
2. **檢查**：`uv run <技能目錄>/scripts/check.py <檔案或目錄>`。上層有 `_quarto.yml` 會自動用 quarto 模式（沿用專案前置）；純 LaTeX 專案加 `--mode latex --preamble <前置檔>`。完成：結束碼 `0`，或拿到結束碼 `1` 的問題清單。
3. **逐條修**：照〈每種訊息的修法〉改圖，重跑到結束碼 `0`。改的是圖的版面，門檻與 `--min-gap` 保持預設。完成：結束碼 `0`，而且沒有為了過關新增 `% tikz-guard: allow`。
4. **目視**：結束碼 `0` 只代表沒有壓疊；打開建置出的 PDF 看一遍閱讀順序與箭頭方向。完成：每張改過的圖都看過。
5. **接上守門**（每個 repo 一次）：建置檢查、pre-push 與 Claude Code hook 照 [references/integration.md](references/integration.md) 接。完成：故意把一張圖的兩個節點疊在一起，三處都擋得下。

## 怎麼畫才不會壓疊

- **相對定位**：節點用 `positioning`（`below=of a`、`right=8mm of a`），間距集中在 `node distance`；不寫絕對座標。外框用 `fit` 包住所有成員，成員以外的節點放到外框外。`\resizebox` 只做最後縮放，縮放不會讓重疊消失（守門量的是原尺寸）。
- **連線繞開節點**：直線只接相鄰的節點；中間隔著別的節點就用 `-|`／`|-` 經轉折點走外側，例如 `(a.north) -- ++(0,4mm) -| (c.north)`。曲線（`to[out=…,in=…]`、`bend left`）要確認整條弧都不經過第三個節點。兩條線要錯開接點（`.north east`、`.south west`）或轉折位置，不共用同一條通道；從同一個錨點分岔、匯入同一個錨點的共用線段是刻意的，不算疊。
- **標籤放置**：線上的字一律用帶白底的標籤樣式，放在夠長的線段中段（`pos=0.4`～`0.6`），線段長度至少是「標籤寬 ＋ 箭頭長 ＋ 兩側留白」，不夠就拉開節點，不縮字。不要把 `pos` 放到 `0.85` 以上：那裡是箭頭。上下堆疊的節點之間，標籤放線的一側（`right`），並讓垂直段夠長。標籤寫的是目標節點的身分時（角色名、分支名），改成節點的粗體標題，連線不帶字。
- **字放得下**：長句加 `text width` 並以 `\\` 換行；菱形用 `aspect` 2.4 以上、`inner sep` 至少 2pt，判斷句太長就改成兩行。

## 每種訊息的修法

| 規則 | 意思 | 修法 |
|------|------|------|
| `node-overlap` | 兩個節點相交或間距不到 `--min-gap`（預設 2pt）；外框切過不屬於它的節點；兩個外框交疊 | 加大 `node distance` 或改相對定位的基準；外框把節點放進 `fit` 清單，或把節點移出外框 |
| `edge-through-node` | 連線穿過兩端以外節點的內部 | 改用 `-|`／`|-` 經轉折點走外側；曲線改 `out`／`in` 或改成折線 |
| `label-on-node` | 邊標籤（含沒有白底的裸字）壓到節點 | 標籤移到線段中段或線的另一側；拉開兩端節點；身分型標籤改成節點標題 |
| `label-on-label` | 兩個標籤疊在一起 | 錯開 `pos`，或放到線的兩側（`above`／`below`） |
| `label-on-arrow` | 標籤蓋住箭頭四分之一以上 | `pos` 往中段移；加長線段；標籤放到線的一側 |
| `text-overflow` | 字超出節點外形（菱形以多邊形判斷） | 縮短字句、`\\` 換行或加 `text width`；菱形加大 `aspect`、`inner sep` |
| `edge-overlap` | 兩條連線有超過 6pt 共線重疊 | 錯開接點或轉折位置 |
| `figure-width` | 圖寬超過 `--max-width`（有給才檢查） | 縮小 `node distance`、文字換行，或改直向排列 |
| `compile` | 這張圖單獨編譯失敗 | 修 LaTeX 錯誤；圖用到正文裡定義的巨集時，把巨集移進前置檔 |

每條規則的量法、例外與 TikZ 範例見 [references/rules.md](references/rules.md)。

## 規則

- **修圖，不放寬門檻**：守門擋下就改圖；門檻是量過真實文件後定的，放寬會讓下一張圖帶著同樣的問題過關。
- **放行要寫在圖上**：只有刻意的疊放（角標貼在卡片上之類）才在 `\begin{tikzpicture}` 上方或圖裡加 `% tikz-guard: allow <規則>`，同一行寫原因；它只放行該圖的那條規則。
- **圖要能單獨編譯**：守門把每張圖抽出來單獨編，圖依賴的樣式、顏色與巨集都要在前置檔裡；回報 `compile` 而文件本身編得過，就是這個原因。
