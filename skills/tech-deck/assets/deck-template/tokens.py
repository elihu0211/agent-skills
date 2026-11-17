"""設計規格載入器（純標準庫）。

唯一真值源是同目錄的 `tokens.toml`，`load()` 讀進來、驗證完整後回傳不可變的 `Tokens`，`theme.py` 在匯入時讀它。
同專案另有專論（TikZ）要共用色票時，另寫產生器，不放在這支。

本檔刻意不用 `from __future__ import annotations`：檢查工具以 `spec_from_file_location` 載入本檔、
不登記 `sys.modules`，字串註記下 dataclass 會找不到所屬模組而失敗。
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
TOKENS_PATH = HERE / "tokens.toml"

_HEX = re.compile(r"^[0-9A-F]{6}$")

SCHEMA = 1
# 色階名單：只有這些名字合法。值是 TikZ 色名的後綴（main 無後綴）。
_SUFFIX = {"main": "", "lite": "Lite", "text": "Text", "mute": "Mute", "rule": "Rule", "wash": "Wash"}


class TokensError(ValueError):
    """`tokens.toml` 不合規格；訊息帶出出錯的位置。"""


@dataclass(frozen=True)
class Role:
    palette: str
    meaning: str
    tikz: str


@dataclass(frozen=True)
class Geometry:
    radius_pt: float
    hair_pt: float
    normal_pt: float
    strong_pt: float


@dataclass(frozen=True)
class DeckLayout:
    """簡報版面（英吋）。"""

    slide_w: float
    slide_h: float
    left: float
    right: float
    top: float
    bottom: float
    footer_rule: float
    footer_text: float
    note_h: float
    gap: float
    side_w: float
    side_gap: float
    stack_gap: float

    def __post_init__(self) -> None:
        if not 0 <= self.left < self.right <= self.slide_w:
            raise TokensError("deck.layout：須滿足 0 <= left < right <= slide_w")
        if not 0 <= self.top < self.bottom <= self.footer_rule < self.footer_text < self.slide_h:
            raise TokensError("deck.layout：須滿足 0 <= top < bottom <= footer_rule < footer_text < slide_h")

    @property
    def width(self) -> float:
        """內容區寬度。"""
        return self.right - self.left


@dataclass(frozen=True)
class DeckType:
    """簡報字級（pt）。"""

    cover_category: float
    cover_title: float
    cover_subtitle: float
    cover_meta: float
    slide_ref: float
    slide_title: float
    footer: float
    note: float
    panel_title: float
    panel_body: float
    label: float


@dataclass(frozen=True)
class FontPaper:
    serif: str
    sans: str
    mono: str
    cjk_serif: str
    cjk_sans: str


@dataclass(frozen=True)
class FontDeck:
    cjk: str


@dataclass(frozen=True)
class Tokens:
    palette: Mapping[str, Mapping[str, str]]
    role: Mapping[str, Role]
    geometry: Geometry
    deck_layout: DeckLayout
    deck_type: DeckType
    font_paper: FontPaper
    font_deck: FontDeck

    def hex(self, family: str, shade: str = "main") -> str:
        return self.palette[family][shade]


def _table(data: Mapping, key: str, where: str = "") -> Mapping:
    path = f"{where}{key}"
    value = data.get(key)
    if not isinstance(value, dict):
        raise TokensError(f"缺少 [{path}] 表")
    return value


def _build(cls, table: Mapping, where: str):
    """把一張 TOML 表轉成 frozen dataclass：缺鍵、未知鍵與型別不符都報錯，並指出 [where]。"""
    if not isinstance(table, dict):
        raise TokensError(f"[{where}] 須為表")
    wanted = {f.name: f.type for f in fields(cls)}
    missing, unknown = wanted.keys() - table.keys(), table.keys() - wanted.keys()
    if missing or unknown:
        parts = ([f"缺 {', '.join(sorted(missing))}"] if missing else []) + (
            [f"未知 {', '.join(sorted(unknown))}"] if unknown else []
        )
        raise TokensError(f"[{where}]：{'；'.join(parts)}")
    values = {}
    for name, typ in wanted.items():
        raw = table[name]
        if typ is float:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
                raise TokensError(f"[{where}] {name} 須為正數：{raw!r}")
            values[name] = float(raw)
        else:
            if not isinstance(raw, str) or not raw:
                raise TokensError(f"[{where}] {name} 須為非空字串：{raw!r}")
            values[name] = raw
    return cls(**values)


def _palette(raw: Mapping) -> Mapping[str, Mapping[str, str]]:
    out = {}
    for family, shades in raw.items():
        if "main" not in shades:
            raise TokensError(f"[palette.{family}] 缺 main")
        for shade, value in shades.items():
            if shade not in _SUFFIX:
                raise TokensError(f"[palette.{family}] 未知色階 {shade}（可用：{', '.join(_SUFFIX)}）")
            if not isinstance(value, str) or not _HEX.match(value):
                raise TokensError(f"palette.{family}.{shade} 不是六位大寫十六進位色碼：{value!r}")
        out[family] = MappingProxyType(dict(shades))
    return MappingProxyType(out)


def load(path: Path = TOKENS_PATH) -> Tokens:
    """讀 `tokens.toml` 並驗證；任何不合規格都丟 `TokensError`（是 `ValueError`）。"""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise TokensError(f"schema 須為 {SCHEMA}：{data.get('schema')!r}")
    palette = _palette(_table(data, "palette"))
    roles = {}
    for name, raw in _table(data, "role").items():
        role = _build(Role, raw, f"role.{name}")
        if role.palette not in palette:
            raise TokensError(f"[role.{name}] palette 指向不存在的色族：{role.palette}")
        roles[name] = role
    deck, font = _table(data, "deck"), _table(data, "font")
    return Tokens(
        palette=palette,
        role=MappingProxyType(roles),
        geometry=_build(Geometry, _table(data, "geometry"), "geometry"),
        deck_layout=_build(DeckLayout, _table(deck, "layout", "deck."), "deck.layout"),
        deck_type=_build(DeckType, _table(deck, "type", "deck."), "deck.type"),
        font_paper=_build(FontPaper, _table(font, "paper", "font."), "font.paper"),
        font_deck=_build(FontDeck, _table(font, "deck", "font."), "font.deck"),
    )
