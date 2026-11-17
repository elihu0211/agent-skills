"""簡報主題：把品牌（`_brand.yml`）與設計參數（`design.yml`）組成不可變的 `Theme`，繪圖函式都以它為第一個參數。

沒有模組層級的全域狀態：品牌由簡報目錄往上搜尋，不同目錄的簡報可以用不同品牌，測試也不必改全域設定。

版面原則：全頁白底、細線、墨色主文字；顏色只表示語義——
藍＝資料與結構（system）、綠＝系統確定（certain）、琥珀＝只給候選（candidate）、
玫紅＝須人判斷或失敗（warn）、灰藍＝中性（neutral）。規格的 `kind` 名稱對到色票名稱（`blue`、`blue-lite`、`blue-text`…）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pptx.dml.color import RGBColor

from . import brand as brand_mod
from . import design as design_mod
from .brand import Brand
from .design import Design, Frame, Layout, Limits, Lint, Page, Type

LANG = "zh-TW"
# 規格的 kind 名稱 → 色票色族（kind 的 `red` 對應 rose 色族）。
_SEMANTIC = {"blue": "blue", "green": "green", "amber": "amber", "red": "rose"}


@dataclass(frozen=True)
class Tone:
    """一個語義色：line 用於線與填滿，text 是白底小字用的深色，tint 是淡底。"""

    line: RGBColor
    text: RGBColor
    tint: RGBColor


@dataclass(frozen=True)
class Card:
    fill: RGBColor
    line: RGBColor
    ink: RGBColor  # 內文
    head: RGBColor  # 標題
    weight: float  # 框線寬（pt）


@dataclass(frozen=True)
class Theme:
    brand: Brand
    design: Design
    lang: str
    # 墨色與中性
    ink: RGBColor  # 標題、主要內文、表頭底
    gray: RGBColor  # 次要文字、說明
    muted: RGBColor  # 頁尾、一般連線
    rule: RGBColor  # 細分隔線
    white: RGBColor
    row_alt: RGBColor  # 表格與泳道的交錯列底
    gray_fill: RGBColor  # 中性卡片底
    tones: Mapping[str, Tone]
    cards: Mapping[str, Card]
    series_cycle: tuple[RGBColor, ...]  # 圖表系列的循環色

    # ---- 取自設計參數與品牌的別名 ----
    @property
    def font(self) -> str:
        return self.brand.font

    @property
    def layout(self) -> Layout:
        return self.design.layout

    @property
    def frame(self) -> Frame:
        return self.design.frame

    @property
    def type(self) -> Type:
        return self.design.type

    @property
    def limits(self) -> Limits:
        return self.design.limits

    @property
    def page(self) -> Page:
        return self.design.page

    @property
    def lint(self) -> Lint:
        return self.design.lint

    @property
    def radius_pt(self) -> float:
        return self.design.geometry.radius_pt

    @property
    def line_hair(self) -> float:
        return self.design.geometry.hair_pt

    @property
    def line_normal(self) -> float:
        return self.design.geometry.normal_pt

    @property
    def line_strong(self) -> float:
        return self.design.geometry.strong_pt

    @property
    def bg(self) -> RGBColor:
        return self.white

    @property
    def dark_sub(self) -> RGBColor:
        """墨底方塊上的次要淺字。"""
        return self.rule

    @property
    def green(self) -> RGBColor:
        return self.tones["green"].line

    @property
    def alert(self) -> RGBColor:
        return self.tones["red"].line

    @property
    def accent(self) -> RGBColor:
        """簡報的主色（封面細線、章節標籤、步驟序號）：取「資料與結構」的藍。"""
        return self.tones["blue"].line

    @property
    def accent_text(self) -> RGBColor:
        return self.tones["blue"].text

    # ---- 建構 ----
    @classmethod
    def build(cls, brand: Brand, design: Design | None = None, lang: str = LANG) -> Theme:
        design = design or design_mod.load()

        def c(name: str) -> RGBColor:
            return RGBColor.from_string(brand.hex(name))

        ink, white, gray = c("ink"), c("white"), c("slate")
        rule, gray_fill = c("slate-rule"), c("slate-lite")
        tones = {kind: Tone(c(family), c(f"{family}-text"), c(f"{family}-lite")) for kind, family in _SEMANTIC.items()}
        weight = design.geometry
        cards = {
            "gray": Card(gray_fill, gray_fill, ink, ink, weight.normal_pt),  # neutral
            "white": Card(white, rule, ink, ink, weight.normal_pt),
            "dark": Card(white, ink, ink, ink, weight.strong_pt),
            "solid_dark": Card(ink, ink, rule, white, weight.strong_pt),
        }
        for kind, tone in tones.items():  # blue＝system、green＝certain、amber＝candidate、red＝warn
            cards[kind] = Card(white, tone.line, ink, tone.text, weight.strong_pt)
            cards[f"{kind}_fill"] = Card(tone.tint, tone.line, ink, tone.text, weight.strong_pt)
        muted = c("slate-mute")
        return cls(
            brand=brand,
            design=design,
            lang=lang,
            ink=ink,
            gray=gray,
            muted=muted,
            rule=rule,
            white=white,
            row_alt=c("slate-wash"),
            gray_fill=gray_fill,
            tones=MappingProxyType(tones),
            cards=MappingProxyType(cards),
            series_cycle=(tones["blue"].line, tones["green"].line, tones["amber"].line, tones["red"].line, muted),
        )

    @classmethod
    def load(cls, start: Path | None = None, lang: str = LANG) -> Theme:
        """從 `start`（預設目前目錄）往上找 `_brand.yml`，配上套件內的 `design.yml`。"""
        return cls.build(brand_mod.discover(start or Path.cwd()), lang=lang)
