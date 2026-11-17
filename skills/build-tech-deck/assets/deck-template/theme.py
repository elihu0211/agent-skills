"""簡報主題：把設計規格換成 python-pptx 的色票、卡片樣式與版面常數。

色票、語義、幾何、版面與字級都不在這裡定義：唯一真值源是同目錄的 `tokens.toml`，由 `tokens.load()` 讀進來並驗證。
本檔只負責換成 `RGBColor`、組出卡片樣式。

版面原則：全頁白底、細線、墨色主文字；顏色只表示語義——
藍＝資料與結構（system）、綠＝系統確定（certain）、琥珀＝只給候選（candidate）、
玫紅＝須人判斷或失敗（warn）、灰藍＝中性（neutral）。
"""
from __future__ import annotations

from dataclasses import dataclass

from pptx.dml.color import RGBColor

import tokens

TOKENS = tokens.load()
LAYOUT = TOKENS.deck_layout
TYPE = TOKENS.deck_type
FONT = TOKENS.font_deck.cjk


def _c(family: str, shade: str = "main") -> RGBColor:
    return RGBColor.from_string(TOKENS.hex(family, shade))


# 墨色與中性
INK = _c("ink")  # 標題、主要內文、表頭底
GRAY = _c("slate")  # 次要文字、說明
MUTED = _c("slate", "mute")  # 頁尾、一般連線
RULE = _c("slate", "rule")  # 細分隔線
WHITE = _c("white")
BG = WHITE
ROW_ALT = _c("slate", "wash")  # 表格與泳道的交錯列底
GRAY_FILL = _c("slate", "lite")  # 中性卡片底
DARK_SUB = RULE  # 墨底方塊上的次要淺字


@dataclass(frozen=True)
class Tone:
    """一個語義色：line 用於線與填滿，text 是白底小字用的深色，tint 是淡底。"""

    line: RGBColor
    text: RGBColor
    tint: RGBColor


# 簡報規格的 kind 名稱 → 語義色（kind 的 `red` 對應設計規格的 rose 色族）。
TONES = {
    kind: Tone(_c(family), _c(family, "text"), _c(family, "lite"))
    for kind, family in (("blue", "blue"), ("green", "green"), ("amber", "amber"), ("red", "rose"))
}
GREEN, ALERT = TONES["green"].line, TONES["red"].line  # 連線的語義色：成功與阻斷
ACCENT, ACCENT_TEXT = TONES["blue"].line, TONES["blue"].text  # 簡報的主色：封面細線、章節標籤、步驟序號——取「資料與結構」的藍

# 幾何：圓角與線寬取自規格（pt）
RADIUS_PT = TOKENS.geometry.radius_pt
LINE_HAIR = TOKENS.geometry.hair_pt
LINE_NORMAL = TOKENS.geometry.normal_pt
LINE_STRONG = TOKENS.geometry.strong_pt


@dataclass(frozen=True)
class Card:
    fill: RGBColor
    line: RGBColor
    ink: RGBColor  # 內文
    head: RGBColor  # 標題
    weight: float  # 框線寬（pt）


def _outlined(line: RGBColor, head: RGBColor, fill: RGBColor = WHITE) -> Card:
    return Card(fill, line, INK, head, LINE_STRONG)


# 卡片與節點樣式：kind 名稱是簡報規格的用語，對應 tokens.toml 的語義角色。
CARDS = {
    "gray": Card(GRAY_FILL, GRAY_FILL, INK, INK, LINE_NORMAL),  # neutral
    "white": Card(WHITE, RULE, INK, INK, LINE_NORMAL),
    "dark": _outlined(INK, INK),
    "solid_dark": Card(INK, INK, DARK_SUB, WHITE, LINE_STRONG),
}
for _kind, _tone in TONES.items():  # blue＝system、green＝certain、amber＝candidate、red＝warn
    CARDS[_kind] = _outlined(_tone.line, _tone.text)
    CARDS[f"{_kind}_fill"] = _outlined(_tone.line, _tone.text, _tone.tint)
