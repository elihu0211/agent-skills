"""品牌：讀 Quarto 官方的 `_brand.yml`（brand.yml 規格），簡報的顏色與字型只從這裡來。

`_brand.yml` 是品牌的唯一真值：Quarto 文件（HTML、Typst、reveal.js）與簡報讀同一份，不再各維護一套。
搜尋規則同 Quarto：從簡報目錄往上，找到的第一份 `_brand.yml`（或 `_brand/_brand.yml`）；上到專案根為止。

引擎對色票名稱有約定（缺了簡報畫不出來，載入時就擋）：`ink`、`white`，與每個色族 `slate`（另需 `-lite`、`-mute`、
`-rule`、`-wash`）、`blue`、`green`、`amber`、`rose`（各需 `-lite`、`-text`）。語義色（`foreground`、`primary`…）
可寫色票名稱或 `#RRGGBB`；字型取 `typography.base`。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import yamlio

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
REQUIRED_PALETTE = (
    "ink",
    "white",
    "slate",
    "slate-lite",
    "slate-mute",
    "slate-rule",
    "slate-wash",
    *(f"{f}{s}" for f in ("blue", "green", "amber", "rose") for s in ("", "-lite", "-text")),
)
REQUIRED_COLORS = (
    "foreground",
    "background",
    "primary",
    "secondary",
    "tertiary",
    "success",
    "warning",
    "danger",
    "light",
    "dark",
    "link",
)


class BrandError(ValueError):
    """`_brand.yml` 不合規格；訊息帶出出錯的位置。"""


@dataclass(frozen=True)
class Brand:
    name: str
    palette: Mapping[str, str]  # 色票名稱 → 六位大寫色碼（不含 #）
    color: Mapping[str, str]  # 語義色名稱 → 六位大寫色碼
    font: str  # typography.base 的字型家族
    path: Path | None = None

    def hex(self, palette_name: str) -> str:
        return self.palette[palette_name]


def _hex(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _HEX.match(value):
        raise BrandError(f"{where} 須為 #RRGGBB：{value!r}")
    return value[1:].upper()


def parse(data: Any, path: Path | None = None) -> Brand:
    """驗證已解析的 `_brand.yml` 並建出 `Brand`。"""
    if not isinstance(data, Mapping):
        raise BrandError("最上層須為對應表")
    color = data.get("color")
    if not isinstance(color, Mapping) or not isinstance(color.get("palette"), Mapping):
        raise BrandError("缺 color.palette")
    palette = {str(k): _hex(v, f"color.palette.{k}") for k, v in color["palette"].items()}
    if missing := [n for n in REQUIRED_PALETTE if n not in palette]:
        raise BrandError(f"color.palette 缺引擎必要的色票：{', '.join(missing)}")
    semantic: dict[str, str] = {}
    for key in REQUIRED_COLORS:
        if key not in color:
            raise BrandError(f"color 缺語義色 {key}")
        ref = color[key]
        semantic[key] = palette[ref] if isinstance(ref, str) and ref in palette else _hex(ref, f"color.{key}")
    typography = data.get("typography")
    base = typography.get("base") if isinstance(typography, Mapping) else None
    if isinstance(base, Mapping):  # brand.yml 的 base 可寫成 {family: ..., size: ...}
        base = base.get("family")
    if not isinstance(base, str) or not base:
        raise BrandError("缺 typography.base（字型家族）")
    meta = data.get("meta")
    name = meta.get("name") if isinstance(meta, Mapping) else None
    return Brand(
        name=str(name or "brand"),
        palette=MappingProxyType(palette),
        color=MappingProxyType(semantic),
        font=base,
        path=path,
    )


def find(start: Path) -> Path | None:
    """從 `start` 往上找第一份 `_brand.yml`（或 `_brand/_brand.yml`）；找不到回傳 None。"""
    start = start.resolve()
    for d in (start, *start.parents):
        for candidate in (d / "_brand.yml", d / "_brand" / "_brand.yml"):
            if candidate.is_file():
                return candidate
        if (d / ".git").exists():  # 專案根：不再往上，避免誤讀別人的品牌
            return None
    return None


def load(path: Path) -> Brand:
    try:
        return parse(yamlio.load(path), path)
    except BrandError as e:
        raise BrandError(f"{path}：{e}") from None


def discover(start: Path) -> Brand:
    """依 Quarto 的搜尋規則找並載入品牌；找不到就丟 `BrandError`，說明該放哪。"""
    path = find(start)
    if path is None:
        raise BrandError(
            f"{start} 往上找不到 _brand.yml：在專案根放一份 Quarto 的 brand.yml（色票、語義色、typography）"
        )
    return load(path)
