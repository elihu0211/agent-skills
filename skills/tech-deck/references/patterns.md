# 簡報樣式與程式碼範本（Tech Deck Patterns）

本檔提供技術簡報風格（Tech Deck）的完整程式碼實作範本，包含主題配置、佈局引擎與宣告式規格定義。

## 目錄

1. [設計標籤與色票範本（theme.py）](#設計標籤與色票範本themepy)
2. [佈局引擎核心原語（deck_engine.py）](#佈局引擎核心原語deck_enginepy)
3. [宣告式投影片規格定義（deck_spec.py）](#宣告式投影片規格定義deck_specpy)
4. [字數限制與零折行速查表](#字數限制與零折行速查表)

---

## 設計標籤與色票範本（theme.py）

```python
"""簡報主題配置：集中管理色票、框線語義與版心網格。"""
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

def rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(*(int(hex_str[i:i+2], 16) for i in (0, 2, 4)))

FONT = "PingFang TC"

# 基礎黑白灰
INK = rgb("111111")          # 標題、主要內文、表頭黑底
GRAY = rgb("555555")         # 次要文字、說明
MUTED = rgb("8A8A8A")        # 頁尾、一般連線
RULE = rgb("DDDDDD")         # 細分隔線（0.75-1.0pt）
WHITE = rgb("FFFFFF")        # 白底背景
ROW_ALT = rgb("F6F6F6")      # 表格交錯列淺灰底
GRAY_FILL = rgb("F3F3F3")    # 灰底卡片填色

# 語義強調色
ACCENT = rgb("76B900")       # 強調綠（NVIDIA 綠），用於綠框與重點細線
ACCENT_TEXT = rgb("5A8F00")  # 白底上的深綠字，確保對比度
ALERT = rgb("B91C1C")        # 防錯攔截、核心問題、違規告警（紅）
CAUTION = rgb("B45309")      # 待定判斷節點（琥珀）

# 卡片樣式字典
CARDS = {
    "gray":  {"fill": GRAY_FILL, "line": GRAY_FILL, "ink": INK, "head": INK, "dash": False},
    "green": {"fill": WHITE,     "line": ACCENT,    "ink": INK, "head": ACCENT_TEXT, "dash": False},
    "amber": {"fill": WHITE,     "line": MUTED,     "ink": INK, "head": GRAY, "dash": True},
    "red":   {"fill": WHITE,     "line": ALERT,     "ink": INK, "head": ALERT, "dash": False},
    "dark":  {"fill": WHITE,     "line": INK,       "ink": INK, "head": INK, "dash": False},
}

# 16:9 寬螢幕版心尺寸（英吋）
# 投影片全寬 13.333 in，全高 7.50 in
LM, RM = 0.80, 12.53
TOP, BOTTOM = 1.70, 6.60
W = RM - LM  # 內容區寬度 11.73 in
```

---

## 佈局引擎核心原語（deck_engine.py）

```python
"""佈局引擎：封裝八大版面佈局原語，解析宣告式規格並產生 PPTX。"""
import re
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
import theme as T

def _runs(par, text: str, size: float, color, bold: bool = False):
    """支援 **粗體** 標記解析。"""
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        r = par.add_run()
        r.text = part
        r.font.name = T.FONT
        r.font.size = Pt(size)
        r.font.bold = bold or (i % 2 == 1)
        r.font.color.rgb = (T.INK if color == T.ACCENT_TEXT else color) if i % 2 == 1 else color

def _draw_card(slide, x, y, w, h, kind, title, body, tfs=16.5, bfs=13.5, bullet=False, valign=MSO_ANCHOR.MIDDLE):
    """繪製單一語義矩形卡片。"""
    spec = T.CARDS[kind]
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = spec["fill"]
    sh.line.color.rgb = spec["line"]
    sh.line.width = Pt(1.5)
    sh.shadow.inherit = False

    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = valign
    tf.margin_left = tf.margin_right = Inches(0.14)
    tf.margin_top = tf.margin_bottom = Inches(0.10)

    items = body.split("\n") if isinstance(body, str) else (list(body) if body else [])
    if title:
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.LEFT
        p0.space_after = Pt(6 if items else 0)
        p0.line_spacing = 1.15
        _runs(p0, title, tfs, spec["head"], bold=True)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if (i == 0 and not title) else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(4 if i < len(items) - 1 else 0)
        p.line_spacing = 1.18
        _runs(p, ("・" + item) if bullet else item, bfs, spec["ink"], bold=False)
    return sh

def cards(slide, y, items, h=2.80, tfs=16.5, bfs=13.5, bullet=True, valign=MSO_ANCHOR.MIDDLE):
    """水平語義卡片列（自動依數量等分寬度）。"""
    n = len(items)
    gap = 0.30
    cw = (T.W - gap * (n - 1)) / n
    for i, it in enumerate(items):
        x = T.LM + i * (cw + gap)
        _draw_card(slide, x, y, cw, h, it["kind"], it["title"], it.get("body"), tfs=tfs, bfs=bfs, bullet=bullet, valign=valign)
    return h

def note(slide, y, lines, size=14, bold=False):
    """底部細線分隔重點總結列。"""
    # 頂部分隔細線
    c = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(T.LM), Inches(y), Inches(T.W), Pt(0.75))
    c.fill.solid()
    c.fill.fore_color.rgb = T.RULE
    c.line.fill.background()
    # 說明文字
    tb = slide.shapes.add_textbox(Inches(T.LM), Inches(y + 0.12), Inches(T.W), Inches(0.50))
    p = tb.text_frame.paragraphs[0]
    p.line_spacing = 1.15
    for line in lines:
        _runs(p, line, size, T.INK if bold else T.GRAY, bold=bold)
    return 0.60
```

---

## 宣告式投影片規格定義（deck_spec.py）

```python
"""純資料宣告投影片規格，頁面內容集中定義。"""
SLIDES = [
    (
        "(2) 現況與問題",
        "現場三大結構性問題：工時失真、防錯真空、追溯斷鏈",
        [
            ("cards", {
                "h": 2.80,
                "tfs": 16.5,
                "bfs": 13.5,
                "bullet": True,
                "items": [
                    {
                        "kind": "red",
                        "title": "① 工時失真（事後補登）",
                        "body": [
                            "**起訖失真**：下班憑記憶手寫補登",
                            "**工時不純**：換模待料混入切削工時",
                            "**標準失準**：缺乏客觀數據無從排程",
                        ],
                    },
                    {
                        "kind": "red",
                        "title": "② 防錯真空（撞單跳站）",
                        "body": [
                            "**撞單衝突**：前單未出站即插排新單",
                            "**跳站漏刷**：跨機台移轉致工序重疊",
                            "**防呆失效**：現場無互斥隔天方知錯",
                        ],
                    },
                    {
                        "kind": "red",
                        "title": "③ 追溯斷鏈（原地覆寫）",
                        "body": [
                            "**抹除軌跡**：紙本塗改覆蓋過往歷程",
                            "**時序中斷**：缺乏時間戳記事件流水",
                            "**責任難明**：品質交期異常無法溯源",
                        ],
                    },
                ],
            }),
            ("note", {
                "lines": ["對策：相機掃機台與工單雙碼，由雲端重播判定進出站、攔截違規並秒算工時"],
            }),
        ],
        "講稿備註：此處放置詳細的口頭報告論據，頁面上只保留高密度骨架。",
    ),
]
```

---

## 字數限制與零折行速查表

在 16:9（寬度 13.333 英吋）畫布中，各佈局原語的單行安全字數上限如下：

| 版面佈局 | 卡片數量 | 單卡可用寬度 | 推薦字級（`bfs`） | **每行最大字數（含標記）** | 違規表現（必須重構） |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **3 欄卡片列** (`cards`) | 3 卡 | 3.71 in | 13.5 pt | **$\le$ 14 字元** | 18–20 字導致末尾 3–4 字被迫折行 |
| **4 欄卡片列** (`cards`) | 4 卡 | 2.70 in | 12.5 pt | **$\le$ 10 字元** | 12–14 字造成多行破碎 |
| **2 欄對比框** (`columns`) | 2 欄 | 5.60 in | 14.5 pt | **$\le$ 22 字元** | 長句自然斷開破壞整齊感 |
| **主標題** (`title`) | 1 行 | 11.73 in | 28–32 pt | **$\le$ 24 字元** | 大標題折行會破壞視覺衝擊 |
| **底部重點** (`note`) | 1 行 | 11.73 in | 14.0 pt | **$\le$ 45 字元** | 底部總結超過單行會壓迫頁尾線 |
