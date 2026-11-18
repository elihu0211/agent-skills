"""PPTX 範本：由 `Theme` 產生主題、母片與具名版面，簡報的每一頁都建在它上面。

做法同 Quarto／Pandoc 的 `reference-doc`：版面有固定名稱，頁面的標題、章節標籤、頁尾與頁碼是真正的
placeholder，不是漂在空白頁上的文字框。這樣 PowerPoint 的大綱檢視與輔助工具讀得到每頁標題，
「重設版面」會回到範本，頁碼是欄位（換頁序自動更新），主題色與字型出現在 PowerPoint 的色票與字型選單。

版面（沿用 Pandoc 的名稱，另加 `Closing`）：

| 名稱 | 用途 | placeholder |
| --- | --- | --- |
| `Title Slide` | 封面 | 標題、副標、類別（idx 13）、底部說明（idx 14） |
| `Title and Content` | 一般內容頁 | 標題、章節標籤（idx 13）、內文（idx 1）、頁尾、頁碼 |
| `Section Header` | 章節分隔頁 | 標題、章節標籤（idx 13）、說明（idx 1）、頁尾、頁碼 |
| `Title Only` | 區塊圖表頁（引擎畫在上面） | 標題、章節標籤（idx 13）、頁尾、頁碼 |
| `Closing` | 結語頁 | 標題、副標、底部說明（idx 14） |
| `Blank` | 空白 | 頁尾、頁碼 |

色票、字型、版心、字級與頁框幾何全部取自 `Theme`（品牌來自 `_brand.yml`，其餘來自 `design.yml`）；本檔不寫死數值。
`build(t)` 每次回傳全新的空簡報，`deckstyle template` 可把它存成檔案，讓人在 PowerPoint 裡手工做出同一套品牌的頁面。
"""

from __future__ import annotations

from typing import Any

from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.presentation import Presentation as PresentationType
from pptx.util import Inches

from .theme import Theme

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_NSDECL = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())

# 版面名稱 → 借用的預設版面索引（python-pptx 預設範本）。其餘預設版面移除。
_SOURCES = {
    "Title Slide": 0,
    "Title and Content": 1,
    "Section Header": 2,
    "Title Only": 5,
    "Blank": 6,
    "Closing": 7,
}
IDX_REF = 13  # 章節標籤（內容頁、分隔頁）／封面的類別
IDX_META = 14  # 封面與結語頁底部的說明（作者、聯絡方式）
IDX_SUB = 1  # 副標（封面、結語）／說明（分隔頁）
IDX_BODY = 1  # 「標題與內容」版面的內文
IDX_FTR, IDX_SLDNUM = 11, 12  # 頁尾文字與頁碼（版面上的 placeholder idx，頁面上沿用）


def _emu(inches: float) -> int:
    return round(inches * 914400)


def _fill(color: str | None) -> str:
    """文字色：None 用主題的 tx1（＝品牌 foreground）。"""
    if color is None:
        return '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
    return f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'


def _lvl(
    n: int,
    sz: float,
    color: str | None = None,
    *,
    bold: bool = False,
    algn: str = "l",
    line: int | None = None,
    bullet: str | None = None,
    indent_in: float = 0.0,
    font: str = "mn",
    before_pt: float = 0,
) -> str:
    """一個層級的段落與字元預設（`a:lvlNpPr`）。bullet 是項目符號字元，None 表示無符號。"""
    lnspc = f'<a:lnSpc><a:spcPct val="{int(line * 1000)}"/></a:lnSpc>' if line else ""
    bu = f'<a:buFont typeface="+mj-lt"/><a:buChar char="{bullet}"/>' if bullet else "<a:buNone/>"
    marl = _emu(indent_in) if bullet else 0
    return (
        f'<a:lvl{n}pPr marL="{marl}" indent="{-marl}" algn="{algn}">{lnspc}'
        f'<a:spcBef><a:spcPts val="{int(before_pt * 100)}"/></a:spcBef>{bu}'
        f'<a:defRPr sz="{int(sz * 100)}" b="{int(bold)}" kern="1200">{_fill(color)}'
        f'<a:latin typeface="+{font}-lt"/><a:ea typeface="+{font}-ea"/><a:cs typeface="+{font}-cs"/></a:defRPr></a:lvl{n}pPr>'
    )


def _xfrm(x: float, y: float, w: float, h: float) -> str:
    return f'<a:xfrm><a:off x="{_emu(x)}" y="{_emu(y)}"/><a:ext cx="{_emu(w)}" cy="{_emu(h)}"/></a:xfrm>'


_BODY_PR = (
    '<a:bodyPr vert="horz" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="0" anchor="{anchor}"><a:normAutofit/></a:bodyPr>'
)


class _Ids:
    """同一個 spTree 內的 shape id 遞增。"""

    def __init__(self) -> None:
        self.n = 1

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _sp(
    t: Theme,
    ids: _Ids,
    name: str,
    ph: str,
    prompt: str,
    *,
    geom: tuple[float, float, float, float] | None = None,
    lst: str = "",
    anchor: str | None = None,
    field: tuple[str, str] | None = None,
) -> str:
    """一個 placeholder。geom 省略就繼承上一層（版面繼承母片）；field 是欄位（型別, 顯示文字），頁碼用 `slidenum`。"""
    sp_pr = f"<p:spPr>{_xfrm(*geom)}</p:spPr>" if geom else "<p:spPr/>"
    body_pr = _BODY_PR.format(anchor=anchor) if anchor else "<a:bodyPr/>"
    if field:
        kind, shown = field
        text = f'<a:fld id="{{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}}" type="{kind}"><a:rPr lang="{t.lang}"/><a:t>{shown}</a:t></a:fld>'
    else:
        text = f'<a:r><a:rPr lang="{t.lang}"/><a:t>{prompt}</a:t></a:r>' if prompt else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{ids()}" name="{name}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        f"<p:nvPr><p:ph {ph}/></p:nvPr></p:nvSpPr>{sp_pr}"
        f'<p:txBody>{body_pr}<a:lstStyle>{lst}</a:lstStyle><a:p>{text}<a:endParaRPr lang="{t.lang}"/></a:p></p:txBody></p:sp>'
    )


def _line(ids: _Ids, name: str, x: float, y: float, w: float, color: str, weight_pt: float) -> str:
    return (
        f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{ids()}" name="{name}"/><p:cNvCxnSpPr/><p:nvPr userDrawn="1"/></p:nvCxnSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{_emu(x)}" y="{_emu(y)}"/><a:ext cx="{_emu(w)}" cy="0"/></a:xfrm>'
        f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="{int(weight_pt * 12700)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f"</a:ln></p:spPr></p:cxnSp>"
    )


def _parse(fragment: str) -> list[Any]:
    root = etree.fromstring(f"<r {_NSDECL}>{fragment}</r>")
    return list(root)


def _replace_tree(sp_tree: Any, fragment: str) -> None:
    """spTree 只留開頭的 nvGrpSpPr 與 grpSpPr，其後換成 fragment。"""
    for child in list(sp_tree)[2:]:
        sp_tree.remove(child)
    sp_tree.extend(_parse(fragment))


def _hex(t: Theme, palette_name: str) -> str:
    return t.brand.hex(palette_name)


# ---- 主題 ----


def _theme_xml(t: Theme, blob: bytes) -> bytes:
    """把品牌語義色與字型寫進主題：dk1=foreground、lt1=background、accent1~6=primary、success、warning、danger、secondary、tertiary。"""
    c = t.brand.color
    slots = (
        ("dk1", c["foreground"]),
        ("lt1", c["background"]),
        ("dk2", c["dark"]),
        ("lt2", c["light"]),
        ("accent1", c["primary"]),
        ("accent2", c["success"]),
        ("accent3", c["warning"]),
        ("accent4", c["danger"]),
        ("accent5", c["secondary"]),
        ("accent6", c["tertiary"]),
        ("hlink", c["link"]),
        ("folHlink", c["secondary"]),
    )
    clr = "".join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in slots)
    face = f'<a:latin typeface="{t.font}"/><a:ea typeface="{t.font}"/><a:cs typeface="{t.font}"/>'
    root = etree.fromstring(blob)
    name = t.brand.name
    root.set("name", name)
    for tag, xml in (
        ("clrScheme", f'<a:clrScheme name="{name}">{clr}</a:clrScheme>'),
        (
            "fontScheme",
            f'<a:fontScheme name="{name}"><a:majorFont>{face}</a:majorFont><a:minorFont>{face}</a:minorFont></a:fontScheme>',
        ),
    ):
        old = root.find(f".//a:{tag}", NS)
        assert old is not None, f"預設主題缺 {tag}"
        parent = old.getparent()
        assert parent is not None
        parent.replace(old, _parse(xml)[0])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# ---- 母片 ----


def _tx_styles(t: Theme) -> str:
    """母片的文字樣式：標題、內文五層、其他。標題與內文的字級、粗細、行距都在這裡，頁面上的 placeholder 繼承。"""
    body = "".join(
        _lvl(
            i + 1,
            max(t.type.body - 2 * i, 12),
            None if i == 0 else _hex(t, "slate"),
            line=120,
            bullet="・",
            indent_in=0.28 + 0.04 * i,
            before_pt=8 if i == 0 else 4,
        )
        for i in range(5)
    )
    other = "".join(_lvl(i, 18) for i in range(1, 10))
    return (
        f"<p:txStyles><p:titleStyle>{_lvl(1, t.type.slide_title, bold=True, line=105, font='mj')}</p:titleStyle>"
        f"<p:bodyStyle>{body}</p:bodyStyle><p:otherStyle>{other}</p:otherStyle></p:txStyles>"
    )


def _footer_phs(t: Theme, ids: _Ids, *, with_geom: bool) -> str:
    """日期、頁尾文字、頁碼三個 placeholder。母片給位置與字樣，版面與頁面繼承。"""
    mute = _hex(t, "slate-mute")
    lay, size = t.layout, t.type.footer
    y, h = lay.footer_text, 0.25
    geoms = (
        ((lay.right - 4.4, y, 3.2, h), (lay.left, y, 8.0, h), (lay.right - 1.0, y, 1.0, h))
        if with_geom
        else (None, None, None)
    )
    anchor = "ctr" if with_geom else None

    def ph(name: str, spec: str, i: int, algn: str, field: tuple[str, str] | None = None) -> str:
        lst = _lvl(1, size, mute, algn=algn) if with_geom else ""
        return _sp(t, ids, name, spec, "", geom=geoms[i], anchor=anchor, lst=lst, field=field)

    return (
        ph("日期", 'type="dt" sz="half" idx="10"', 0, "r", ("datetimeFigureOut", "2026/1/1"))
        + ph("頁尾", f'type="ftr" sz="quarter" idx="{IDX_FTR}"', 1, "l")
        + ph("頁碼", f'type="sldNum" sz="quarter" idx="{IDX_SLDNUM}"', 2, "r", ("slidenum", "‹#›"))
    )


def _master(t: Theme, prs: PresentationType) -> None:
    master = prs.slide_master
    lay, fr = t.layout, t.frame
    ids = _Ids()
    title = _sp(
        t,
        ids,
        "標題",
        'type="title"',
        "按一下以編輯母片標題樣式",
        geom=(lay.left, fr.title_y, lay.width, fr.title_h),
        anchor="t",
    )
    body = _sp(
        t,
        ids,
        "內文",
        'type="body" idx="1"',
        "按一下以編輯母片文字樣式",
        geom=(lay.left, lay.top, lay.width, lay.bottom - lay.top),
        anchor="t",
    )
    parts = [title, body, _footer_phs(t, ids, with_geom=True)]
    if t.page.footer:
        parts.append(_line(ids, "頁尾細線", lay.left, lay.footer_rule, lay.width, _hex(t, "slate-rule"), t.line_hair))
    tree = master._element.find("p:cSld/p:spTree", NS)
    _replace_tree(tree, "".join(parts))
    old = master._element.find("p:txStyles", NS)
    assert old is not None
    master._element.replace(old, _parse(_tx_styles(t))[0])


# ---- 版面 ----


def _ref_ph(t: Theme, ids: _Ids, y: float, size: float, w: float = 9.5, prompt: str = "章節標籤") -> str:
    """章節標籤：主色粗體小字，內容頁在標題上方。"""
    lst = _lvl(1, size, _hex(t, "blue-text"), bold=True)
    return _sp(
        t,
        ids,
        "章節標籤",
        f'type="body" sz="quarter" idx="{IDX_REF}"',
        prompt,
        geom=(t.layout.left, y, w, 0.25),
        lst=lst,
        anchor="t",
    )


def _sub_ph(t: Theme, ids: _Ids, ptype: str, y: float, h: float, size: float, prompt: str) -> str:
    lst = _lvl(1, size, _hex(t, "slate"))
    return _sp(
        t,
        ids,
        "副標",
        f'type="{ptype}" idx="{IDX_SUB}"',
        prompt,
        geom=(t.layout.left, y, t.layout.width, h),
        lst=lst,
        anchor="t",
    )


def _meta_ph(t: Theme, ids: _Ids, prompt: str) -> str:
    fr = t.frame
    lst = _lvl(1, t.type.cover_meta, _hex(t, "slate-mute"))
    return _sp(
        t, ids, "底部說明", f'type="body" sz="quarter" idx="{IDX_META}"', prompt,
        geom=(t.layout.left, fr.meta_y, t.layout.width, fr.meta_h), lst=lst, anchor="t",
    )  # fmt: skip


def _header_rule(t: Theme, ids: _Ids) -> str:
    """內容頁的標題區分隔線：把章節標籤與標題（上）同內容區（下）明確分開。"""
    return _line(
        ids, "標題分隔線", t.layout.left, t.frame.header_rule_y, t.layout.width, _hex(t, "slate-rule"), t.line_hair
    )


def _accent(t: Theme, ids: _Ids) -> str:
    fr = t.frame
    return _line(ids, "主色細線", t.layout.left, fr.accent_y, fr.accent_w, _hex(t, "blue"), fr.accent_weight_pt)


def _layout_trees(t: Theme) -> dict[str, tuple[str, str, bool]]:
    """版面名稱 → (type 屬性, spTree 內容, 是否顯示母片的頁尾細線與裝飾)。"""
    lay, fr, ty = t.layout, t.frame, t.type
    out: dict[str, tuple[str, str, bool]] = {}

    def ink_title(size: float) -> str:
        return _lvl(1, size, bold=True, line=105, font="mj")

    ids = _Ids()  # 封面
    out["Title Slide"] = (
        "title",
        "".join([
            _sp(t, ids, "標題", 'type="ctrTitle"', "按一下以編輯標題",
                geom=(lay.left, fr.cover_title_y, lay.width, fr.cover_title_h), lst=ink_title(ty.cover_title), anchor="t"),
            _sub_ph(t, ids, "subTitle", fr.cover_subtitle_y, fr.cover_subtitle_h, ty.cover_subtitle, "按一下以編輯副標"),
            _ref_ph(t, ids, fr.cover_category_y, ty.cover_category, 8, "類別"),
            _meta_ph(t, ids, "作者與單位"),
            _accent(t, ids),
        ]),
        False,
    )  # fmt: skip

    ids = _Ids()  # 結語
    out["Closing"] = (
        "cust",
        "".join([
            _sp(t, ids, "標題", 'type="ctrTitle"', "謝謝，歡迎提問",
                geom=(lay.left, fr.closing_title_y, lay.width, fr.closing_title_h), lst=ink_title(ty.closing_title), anchor="t"),
            _sub_ph(t, ids, "subTitle", fr.cover_subtitle_y, fr.closing_sub_h, ty.cover_subtitle, "下一步或聯絡方式"),
            _meta_ph(t, ids, "單位與聯絡資訊"),
            _accent(t, ids),
        ]),
        False,
    )  # fmt: skip

    ids = _Ids()  # 分隔頁
    out["Section Header"] = (
        "secHead",
        "".join([
            _sp(t, ids, "標題", 'type="title"', "按一下以編輯章名",
                geom=(lay.left, fr.divider_title_y, lay.width, fr.divider_title_h), lst=ink_title(ty.divider_title), anchor="t"),
            _sub_ph(t, ids, "body", fr.divider_sub_y, fr.divider_sub_h, ty.divider_sub, "一句說明"),
            _ref_ph(t, ids, fr.divider_ref_y, ty.slide_ref + 1, 8, "章節標籤"),
            _accent(t, ids),
            _footer_phs(t, ids, with_geom=False),
        ]),
        True,
    )  # fmt: skip

    ids = _Ids()  # 區塊圖表頁
    out["Title Only"] = (
        "titleOnly",
        "".join(
            [
                _sp(t, ids, "標題", 'type="title"', "按一下以編輯標題"),
                _ref_ph(t, ids, fr.ref_y, ty.slide_ref),
                _header_rule(t, ids),
                _footer_phs(t, ids, with_geom=False),
            ]
        ),
        True,
    )

    ids = _Ids()  # 標題與內容
    out["Title and Content"] = (
        "obj",
        "".join(
            [
                _sp(t, ids, "標題", 'type="title"', "按一下以編輯標題"),
                _ref_ph(t, ids, fr.ref_y, ty.slide_ref),
                _header_rule(t, ids),
                _sp(t, ids, "內容", f'idx="{IDX_BODY}"', "按一下以編輯文字"),
                _footer_phs(t, ids, with_geom=False),
            ]
        ),
        True,
    )

    ids = _Ids()
    out["Blank"] = ("blank", _footer_phs(t, ids, with_geom=False), True)
    return out


def _layouts(t: Theme, prs: PresentationType) -> None:
    layouts = list(prs.slide_layouts)
    keep = {name: layouts[i] for name, i in _SOURCES.items()}
    for layout in layouts:
        if layout not in keep.values():
            prs.slide_layouts.remove(layout)
    for name, (kind, tree, show_master) in _layout_trees(t).items():
        root = keep[name]._element
        root.set("type", kind)
        root.set("preserve", "1")
        root.set("showMasterSp", "1" if show_master else "0")
        c_sld = root.find("p:cSld", NS)
        assert c_sld is not None
        c_sld.set("name", name)
        _replace_tree(c_sld.find("p:spTree", NS), tree)


def build(t: Theme) -> PresentationType:
    """全新的空簡報：16:9、品牌主題、母片與六個具名版面。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(t.layout.slide_w), Inches(t.layout.slide_h)
    theme_part = prs.slide_master.part.part_related_by(RT.THEME)
    theme_part._blob = _theme_xml(t, theme_part.blob)  # type: ignore[attr-defined]
    _master(t, prs)
    _layouts(t, prs)
    prs.core_properties.language = t.lang
    return prs
