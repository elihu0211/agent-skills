"""簡報主題：色票、語義、線寬與版心。顏色與幾何不在這裡寫死，唯一真值源是同目錄的 tokens.toml。

版面原則：全頁白底、細線、墨色主文字；顏色只表示語義——
藍＝資料與結構（system）、綠＝系統確定（certain）、琥珀＝只給候選（candidate）、
玫紅＝須人判斷或失敗（warn）、灰藍＝中性（neutral）。要改色票，改 tokens.toml，不要改這支。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from pptx.dml.color import RGBColor

TOKENS = tomllib.loads(Path(__file__).with_name("tokens.toml").read_text(encoding="utf-8"))


def rgb(hex_str: str) -> RGBColor:
    h = hex_str.lstrip("#")
    return RGBColor(*(int(h[i : i + 2], 16) for i in (0, 2, 4)))


def _c(family: str, shade: str = "main") -> RGBColor:
    return rgb(TOKENS["palette"][family][shade])


FONT = TOKENS["font"]["deck"]["cjk"]  # macOS 預設 PingFang TC；Windows 改 tokens.toml 的 font.deck.cjk 為 Microsoft JhengHei

# 墨色與中性
INK = _c("ink")  # 標題、主要內文、表頭底
GRAY = _c("slate")  # 次要文字、說明
MUTED = _c("slate", "mute")  # 頁尾、一般連線
RULE = _c("slate", "rule")  # 細分隔線
WHITE = rgb("FFFFFF")
BG = WHITE
ROW_ALT = _c("slate", "wash")  # 表格與泳道的交錯列底
GRAY_FILL = _c("slate", "lite")  # 中性卡片底

# 語義色：主色用於線與填滿；*_TEXT 是白底小字用的深色；*_TINT 是淡底
PRIMARY = _c("blue")  # 簡報的主色：封面細線、章節標籤、步驟序號
PRIMARY_TEXT = _c("blue", "text")
BLUE, BLUE_TEXT, BLUE_TINT = PRIMARY, PRIMARY_TEXT, _c("blue", "lite")
GREEN, GREEN_TEXT, GREEN_TINT = _c("green"), _c("green", "text"), _c("green", "lite")
AMBER, AMBER_TEXT, AMBER_TINT = _c("amber"), _c("amber", "text"), _c("amber", "lite")
ALERT, ALERT_TEXT, RED_TINT = _c("rose"), _c("rose", "text"), _c("rose", "lite")

ACCENT = PRIMARY  # 裝飾用主色，不等於「綠」；語義綠一律用 GREEN
ACCENT_TEXT = PRIMARY_TEXT
CAUTION = AMBER_TEXT
DARK_SUB = _c("slate", "rule")  # 墨底方塊上的次要淺字

# 卡片樣式：fill 底色、line 框色、ink 內文色、head 標題色。kind 名稱是規格的用語。
CARDS = {
    "gray": {"fill": GRAY_FILL, "line": GRAY_FILL, "ink": INK, "head": INK, "dash": False},  # neutral
    "white": {"fill": WHITE, "line": RULE, "ink": INK, "head": INK, "dash": False},
    "blue": {"fill": WHITE, "line": BLUE, "ink": INK, "head": BLUE_TEXT, "dash": False},  # system
    "blue_fill": {"fill": BLUE_TINT, "line": BLUE, "ink": INK, "head": BLUE_TEXT, "dash": False},
    "green": {"fill": WHITE, "line": GREEN, "ink": INK, "head": GREEN_TEXT, "dash": False},  # certain
    "green_fill": {"fill": GREEN_TINT, "line": GREEN, "ink": INK, "head": GREEN_TEXT, "dash": False},
    "amber": {"fill": WHITE, "line": AMBER, "ink": INK, "head": AMBER_TEXT, "dash": False},  # candidate
    "amber_fill": {"fill": AMBER_TINT, "line": AMBER, "ink": INK, "head": AMBER_TEXT, "dash": False},
    "red": {"fill": WHITE, "line": ALERT, "ink": INK, "head": ALERT_TEXT, "dash": False},  # warn
    "red_fill": {"fill": RED_TINT, "line": ALERT, "ink": INK, "head": ALERT_TEXT, "dash": False},
    "dark": {"fill": WHITE, "line": INK, "ink": INK, "head": INK, "dash": False},
    "solid_dark": {"fill": INK, "line": INK, "ink": DARK_SUB, "head": WHITE, "dash": False},
}

# 幾何：圓角與線寬（pt）
RADIUS_PT = float(TOKENS["geometry"]["radius_pt"])
LINE_HAIR = float(TOKENS["geometry"]["hair_pt"])
LINE_NORMAL = float(TOKENS["geometry"]["normal_pt"])
LINE_STRONG = float(TOKENS["geometry"]["strong_pt"])

# 16:9 版心（英吋）：全寬 13.333、全高 7.50
SLIDE_W, SLIDE_H = 13.333, 7.50
LM, RM = 0.80, 12.53
TOP, BOTTOM = 1.70, 6.60  # 內容區上緣與安全底線；頁尾線在 7.00
W = RM - LM  # 內容寬 11.73
