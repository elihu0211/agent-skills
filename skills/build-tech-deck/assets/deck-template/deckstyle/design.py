"""設計參數載入器：讀 `design.yml`、驗證完整，回傳不可變的 `Design`。

版面、字級、區塊高度上限、頁框幾何、轉場、頁尾與 lint 門檻只在 `design.yml` 定義一次；本檔只負責讀進來並擋掉
不合規格的值（缺鍵、未知鍵、型別、版面關係），錯誤訊息指出出錯的位置。顏色與字型不在這裡，見 `brand.py`。
鍵名用 YAML 慣用的 kebab-case（`slide-w`），載入時換成 dataclass 欄位的 snake_case。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, get_type_hints

from . import yamlio

DESIGN_PATH = Path(__file__).with_name("design.yml")
SCHEMA = 1
TRANSITIONS = ("fade", "none")


class DesignError(ValueError):
    """`design.yml` 不合規格；訊息帶出出錯的位置。"""


@dataclass(frozen=True)
class Geometry:
    radius_pt: float
    hair_pt: float
    normal_pt: float
    strong_pt: float


@dataclass(frozen=True)
class Layout:
    """版面（英吋）。"""

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
            raise DesignError("layout：須滿足 0 <= left < right <= slide-w")
        if not 0 <= self.top < self.bottom <= self.footer_rule < self.footer_text < self.slide_h:
            raise DesignError("layout：須滿足 0 <= top < bottom <= footer-rule < footer-text < slide-h")
        if self.side_w + self.side_gap >= self.right - self.left:
            raise DesignError("layout：side-w + side-gap 須小於內容寬")

    @property
    def width(self) -> float:
        """內容區寬度。"""
        return self.right - self.left


@dataclass(frozen=True)
class Frame:
    """頁框幾何（英吋與 pt）：各種頁面的標題、標籤與裝飾線位置。"""

    ref_y: float
    title_y: float
    title_h: float
    header_rule_y: float
    cover_category_y: float
    cover_title_y: float
    cover_title_h: float
    accent_y: float
    accent_w: float
    accent_weight_pt: float
    cover_subtitle_y: float
    cover_subtitle_h: float
    meta_rule_y: float
    meta_y: float
    meta_h: float
    divider_ref_y: float
    divider_title_y: float
    divider_title_h: float
    divider_sub_y: float
    divider_sub_h: float
    closing_title_y: float
    closing_title_h: float
    closing_sub_h: float


@dataclass(frozen=True)
class Type:
    """字級（pt）。"""

    cover_category: float
    cover_title: float
    cover_subtitle: float
    cover_meta: float
    divider_title: float
    divider_sub: float
    closing_title: float
    slide_ref: float
    slide_title: float
    footer: float
    note: float
    panel_title: float
    panel_body: float
    label: float
    kpi_value: float
    body: float


@dataclass(frozen=True)
class Limits:
    """區塊高度上限（英吋）。"""

    card_max_h: float
    row_max_h: float
    steps_max_h: float
    columns_max_h: float
    kpi_max_h: float
    chart_max_h: float
    flow_max_h: float
    caption_h: float


@dataclass(frozen=True)
class Page:
    transition: str
    footer: bool

    def __post_init__(self) -> None:
        if self.transition not in TRANSITIONS:
            raise DesignError(f"page：transition 須為 {' 或 '.join(TRANSITIONS)}：{self.transition!r}")


@dataclass(frozen=True)
class Lint:
    safety: float
    orphan_chars: float
    bold_extra: float

    def __post_init__(self) -> None:
        if not 0 < self.safety <= 1:
            raise DesignError(f"lint：safety 須在 (0, 1]：{self.safety!r}")


@dataclass(frozen=True)
class Design:
    geometry: Geometry
    layout: Layout
    frame: Frame
    type: Type
    limits: Limits
    page: Page
    lint: Lint


def _build(cls: type, table: Any, where: str) -> Any:
    """把一張 YAML 表轉成 frozen dataclass：缺鍵、未知鍵與型別不符都報錯，並指出 where。"""
    if not isinstance(table, Mapping):
        raise DesignError(f"缺少 {where} 表")
    table = {str(k).replace("-", "_"): v for k, v in table.items()}
    wanted, names = get_type_hints(cls), {f.name for f in fields(cls)}
    missing, unknown = names - table.keys(), table.keys() - names
    if missing or unknown:
        parts = ([f"缺 {', '.join(sorted(missing))}"] if missing else []) + (
            [f"未知 {', '.join(sorted(unknown))}"] if unknown else []
        )
        raise DesignError(f"{where}：{'；'.join(parts)}")
    values: dict[str, Any] = {}
    for name in names:
        raw, typ = table[name], wanted[name]
        if typ is float:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
                raise DesignError(f"{where} {name} 須為正數：{raw!r}")
            values[name] = float(raw)
        elif typ is bool:
            if not isinstance(raw, bool):
                raise DesignError(f"{where} {name} 須為 true 或 false：{raw!r}")
            values[name] = raw
        else:
            if not isinstance(raw, str) or not raw:
                raise DesignError(f"{where} {name} 須為非空字串：{raw!r}")
            values[name] = raw
    return cls(**values)


def parse(data: Any) -> Design:
    """驗證已解析的 YAML 並建出 `Design`；任何不合規格都丟 `DesignError`。"""
    if not isinstance(data, Mapping):
        raise DesignError("最上層須為對應表")
    if data.get("schema") != SCHEMA:
        raise DesignError(f"schema 須為 {SCHEMA}：{data.get('schema')!r}")
    sections = {"geometry", "layout", "frame", "type", "limits", "page", "lint"}
    if unknown := set(data) - sections - {"schema"}:
        raise DesignError(f"未知的區段 {', '.join(sorted(map(str, unknown)))}")
    design = Design(
        geometry=_build(Geometry, data.get("geometry"), "geometry"),
        layout=_build(Layout, data.get("layout"), "layout"),
        frame=_build(Frame, data.get("frame"), "frame"),
        type=_build(Type, data.get("type"), "type"),
        limits=_build(Limits, data.get("limits"), "limits"),
        page=_build(Page, data.get("page"), "page"),
        lint=_build(Lint, data.get("lint"), "lint"),
    )
    fr = design.frame
    if not (fr.ref_y < fr.title_y and fr.title_y + fr.title_h <= fr.header_rule_y < design.layout.top):
        raise DesignError("frame：須滿足 ref-y < title-y，且 title-y + title-h <= header-rule-y < layout 的 top")
    return design


def load(path: Path = DESIGN_PATH) -> Design:
    """讀 `design.yml` 並驗證。"""
    return parse(yamlio.load(path))
