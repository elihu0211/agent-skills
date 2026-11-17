"""簡報範本：由設計規格產生真正的 PPTX 範本（佈景主題、投影片主版、版面）。

與 Quarto、pandoc 的 `reference-doc` 同一個模型：範本是一份 `.pptx`，版面以名稱找，內容放進版面的佔位符。
所以產生出來的範本也能直接當 Quarto 的 `reference-doc`：版面名稱沿用它們查的七個
（Title Slide、Title and Content、Section Header、Two Content、Comparison、Content with Caption、Blank），
另加簡報自用的 Title Only。

契約（引擎依它填內容，換範本時要保留）：

| 版面 | 佔位符 idx | 內容 |
|------|-----------|------|
| Title Slide | 0 / 1 / 13 / 14 | 題名、副題、類別、作者 |
| Title Only | 0 / 13 / 11 / 12 | 標題、章節標籤、頁尾短名、頁碼 |

色票、字型、版心與字級都取自設計規格（`tokens.toml`），不在這裡寫死。
換外觀有兩條路：改 `tokens.toml`；或 `build_deck.py --emit-template out.pptx` 匯出範本，在 PowerPoint 的
「投影片母片」檢視編輯後，以 `build_deck.py --template out.pptx` 建置。
"""
from __future__ import annotations

import copy
import sys
import uuid
from pathlib import Path
from typing import Any

import theme as T
from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml import parse_xml
from pptx.util import Inches

L = T.LAYOUT
TYPE = T.TYPE

TITLE_SLIDE = "Title Slide"
TITLE_ONLY = "Title Only"
# 版面名稱沿用 Quarto／pandoc 查的七個，另加簡報自用的 Title Only。
LAYOUT_ORDER = (
    TITLE_SLIDE,
    TITLE_ONLY,
    "Title and Content",
    "Section Header",
    "Two Content",
    "Comparison",
    "Content with Caption",
    "Blank",
)

# 佔位符 idx：0 是標題，其餘沿用 Office 內建的慣例（日期 10、頁尾 11、頁碼 12），自訂的從 13 起。
IDX_TITLE, IDX_BODY, IDX_BODY2, IDX_BODY3, IDX_BODY4 = 0, 1, 2, 3, 4
IDX_DATE, IDX_FOOTER, IDX_NUMBER = 10, 11, 12
IDX_REF, IDX_META = 13, 14  # Title Only 的章節標籤；Title Slide 的類別（13）與作者（14）

_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
_EMU = 914400


def _emu(inches: float) -> int:
    return round(inches * _EMU)


def _hex(family: str, shade: str = "main") -> str:
    return T.TOKENS.hex(family, shade)


# ---- 佈景主題 ----

def _theme_colors() -> dict[str, str]:
    """色票對到佈景主題的十二個槽：PowerPoint 的色盤與新增的形狀都會用這組色。"""
    return {
        "dk1": _hex("ink"),
        "lt1": _hex("white"),
        "dk2": _hex("slate"),
        "lt2": _hex("slate", "wash"),
        "accent1": _hex("blue"),  # 資料與結構：簡報的主色
        "accent2": _hex("green"),  # 系統確定
        "accent3": _hex("amber"),  # 只給候選
        "accent4": _hex("rose"),  # 須人判斷或失敗
        "accent5": _hex("slate", "mute"),  # 頁尾與次要字
        "accent6": _hex("blue", "text"),  # 白底上的小字用深藍
        "hlink": _hex("blue", "text"),
        "folHlink": _hex("slate", "mute"),
    }


def _apply_theme(theme_xml: bytes) -> bytes:
    """改寫預設佈景主題的配色與字型；格式配置（fmtScheme）沿用。"""
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    root = etree.fromstring(theme_xml)
    root.set("name", "Tech Deck")
    elements = root.find("a:themeElements", ns)
    clr = elements.find("a:clrScheme", ns)
    for child in list(clr):
        clr.remove(child)
    clr.set("name", "Tech Deck")
    for slot, value in _theme_colors().items():
        el = etree.SubElement(clr, f"{{{ns['a']}}}{slot}")
        etree.SubElement(el, f"{{{ns['a']}}}srgbClr").set("val", value)
    fonts = elements.find("a:fontScheme", ns)
    fonts.set("name", "Tech Deck")
    for group in ("majorFont", "minorFont"):
        g = fonts.find(f"a:{group}", ns)
        for child in list(g):
            g.remove(child)
        etree.SubElement(g, f"{{{ns['a']}}}latin").set("typeface", T.FONT)
        etree.SubElement(g, f"{{{ns['a']}}}ea").set("typeface", T.FONT)
        etree.SubElement(g, f"{{{ns['a']}}}cs").set("typeface", T.FONT)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# ---- 形狀與文字樣式 ----

def _style(size: float, color: str, bold: bool = False, align: str = "l", spacing: float | None = None) -> str:
    """lvl1 的段落與字元預設：顏色用佈景主題的槽，換主題時跟著變。"""
    ln = f'<a:lnSpc><a:spcPct val="{round(spacing * 100000)}"/></a:lnSpc>' if spacing else ""
    return (
        f'<a:lvl1pPr marL="0" indent="0" algn="{align}">{ln}<a:spcBef><a:spcPts val="0"/></a:spcBef><a:buNone/>'
        f'<a:defRPr lang="zh-TW" altLang="en-US" sz="{round(size * 100)}" b="{int(bold)}">'
        f'<a:solidFill><a:schemeClr val="{color}"/></a:solidFill>'
        '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr>'
    )


def _placeholder(
    sid: int,
    name: str,
    ph_type: str | None,
    idx: int,
    box: tuple[float, float, float, float] | None,
    prompt: str,
    style: str | None = None,
    anchor: str = "t",
    size_attr: str = "",
    field: str | None = None,
) -> str:
    """一個佔位符。`box` 是 (x, y, w, h) 英吋；None 表示沿用上一層的位置。內距歸零、不自動縮字，與引擎原本的文字方塊一致。"""
    t = f' type="{ph_type}"' if ph_type else ""
    xfrm = (
        f'<a:xfrm><a:off x="{_emu(box[0])}" y="{_emu(box[1])}"/><a:ext cx="{_emu(box[2])}" cy="{_emu(box[3])}"/></a:xfrm>'
        if box
        else ""
    )
    body = f'<a:bodyPr lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr>' if box else "<a:bodyPr/>"
    lst = f"<a:lstStyle>{style}</a:lstStyle>" if style else "<a:lstStyle/>"
    if field == "slidenum":
        para = f'<a:p><a:fld id="{{{str(uuid.uuid4()).upper()}}}" type="slidenum"><a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld></a:p>'
    else:
        para = f'<a:p><a:r><a:rPr lang="zh-TW"/><a:t>{prompt}</a:t></a:r></a:p>'
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        f'<p:nvPr><p:ph{t}{size_attr} idx="{idx}"/></p:nvPr></p:nvSpPr><p:spPr>{xfrm}</p:spPr>'
        f"<p:txBody>{body}{lst}{para}</p:txBody></p:sp>"
    )


def _rule(sid: int, name: str, x: float, y: float, w: float, color: str, weight_pt: float) -> str:
    """水平細線（母片與版面的裝飾，不是佔位符）。"""
    return (
        f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvCxnSpPr/><p:nvPr userDrawn="1"/></p:nvCxnSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{_emu(x)}" y="{_emu(y)}"/><a:ext cx="{_emu(w)}" cy="0"/></a:xfrm>'
        f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
        f'<a:ln w="{round(weight_pt * 12700)}"><a:solidFill>{color}</a:solidFill></a:ln></p:spPr></p:cxnSp>'
    )


def _scheme(slot: str) -> str:
    return f'<a:schemeClr val="{slot}"/>'


def _rule_color() -> str:
    return f'<a:srgbClr val="{_hex("slate", "rule")}"/>'


def _sp_tree(shapes: str) -> str:
    return (
        '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{shapes}</p:spTree>"
    )


def _footer_placeholders(first_id: int) -> str:
    """頁尾短名與頁碼：版面的位置與字型，每頁引擎再放一份實例（python-pptx 不會自動複製）。"""
    foot = _style(TYPE.footer, "accent5")
    num = _style(TYPE.footer, "accent5", align="r")
    return _placeholder(
        first_id, "Footer Placeholder", "ftr", IDX_FOOTER, (L.left, L.footer_text, 8.0, 0.25), "", foot, size_attr=' sz="quarter"'
    ) + _placeholder(
        first_id + 1,
        "Slide Number Placeholder",
        "sldNum",
        IDX_NUMBER,
        (L.right - 1.0, L.footer_text, 1.0, 0.25),
        "",
        num,
        size_attr=' sz="quarter"',
        field="slidenum",
    )


# ---- 母片 ----

def _master_xml_parts() -> tuple[str, str]:
    """回傳（母片的 cSld，txStyles）。"""
    title_style = _style(TYPE.slide_title, "tx1", bold=True, spacing=1.05)
    title = _placeholder(2, "Title Placeholder", "title", IDX_TITLE, (L.left, 0.70, L.width, 0.82), "按一下以編輯母片標題樣式", title_style)
    body = _placeholder(
        3, "Text Placeholder", "body", IDX_BODY, (L.left, L.top, L.width, L.bottom - L.top), "按一下以編輯母片文字樣式", None
    )
    date = _placeholder(
        4, "Date Placeholder", "dt", IDX_DATE, (L.right - 3.0, L.footer_text, 1.9, 0.25), "", _style(TYPE.footer, "accent5", align="r"),
        size_attr=' sz="half"',
    )
    shapes = title + body + date + _footer_placeholders(5) + _rule(7, "Footer Rule", L.left, L.footer_rule, L.width, _rule_color(), T.LINE_HAIR)
    csld = f'<p:cSld {_NS}><p:bg><p:bgPr><a:solidFill>{_scheme("bg1")}</a:solidFill><a:effectLst/></p:bgPr></p:bg>{_sp_tree(shapes)}</p:cSld>'

    def lvl(n: int, size: float) -> str:
        return (
            f'<a:lvl{n}pPr marL="{_emu(0.22 + 0.3 * (n - 1))}" indent="{-_emu(0.22)}" algn="l"><a:lnSpc><a:spcPct val="115000"/></a:lnSpc>'
            f'<a:spcBef><a:spcPts val="400"/></a:spcBef><a:buFont typeface="Arial"/><a:buChar char="・"/>'
            f'<a:defRPr lang="zh-TW" altLang="en-US" sz="{round(size * 100)}"><a:solidFill>{_scheme("tx1")}</a:solidFill>'
            '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr>'
            f"</a:lvl{n}pPr>"
        )

    sizes = (TYPE.note + 1.5, TYPE.note, TYPE.panel_title - 1, TYPE.panel_body, TYPE.panel_body - 1)
    levels = "".join(lvl(i + 1, size) for i, size in enumerate(sizes))
    tx = (
        f'<p:txStyles {_NS}><p:titleStyle>{title_style}</p:titleStyle>'
        f"<p:bodyStyle>{levels}</p:bodyStyle>"
        '<p:otherStyle><a:defPPr><a:defRPr lang="zh-TW"/></a:defPPr></p:otherStyle></p:txStyles>'
    )
    return csld, tx


# ---- 版面 ----

def _layout(name: str, ltype: str, shapes: str, hide_master: bool = False) -> str:
    show = ' showMasterSp="0"' if hide_master else ""
    return (
        f'<p:sldLayout {_NS} type="{ltype}" preserve="1"{show}>'
        f'<p:cSld name="{name}">{_sp_tree(shapes)}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    )


def _layouts() -> dict[str, str]:
    title_box = (L.left, 0.70, L.width, 0.82)
    ref = _placeholder(
        3, "Section Label", "body", IDX_REF, (L.left, 0.46, 9.5, 0.25), "章節標籤", _style(TYPE.slide_ref, "accent6", bold=True), size_attr=' sz="quarter"'
    )
    title = _placeholder(2, "Title", "title", IDX_TITLE, title_box, "按一下以編輯標題")
    foot = _footer_placeholders(10)
    content_box = (L.left, L.top, L.width, L.bottom - L.top)
    half = (L.width - L.gap) / 2

    def body(sid: int, idx: int, box: tuple[float, float, float, float], name: str = "Content Placeholder") -> str:
        return _placeholder(sid, name, None, idx, box, "按一下以編輯文字", size_attr=' sz="half"')

    layouts: dict[str, str] = {}

    # 封面：類別、題名、細線、副題、作者；沒有頁尾
    cover_shapes = (
        _placeholder(
            2, "Category", "body", IDX_REF, (L.left, 0.6, 8.0, 0.3), "類別", _style(TYPE.cover_category, "accent6", bold=True), size_attr=' sz="quarter"'
        )
        + _placeholder(
            3, "Title", "ctrTitle", IDX_TITLE, (L.left, 2.3, L.width, 1.6), "按一下以編輯題名", _style(TYPE.cover_title, "tx1", bold=True, spacing=1.05)
        )
        + _rule(4, "Accent Rule", L.left, 3.95, 1.5, _scheme("accent1"), 3)
        + _placeholder(
            5, "Subtitle", "subTitle", IDX_BODY, (L.left, 4.25, L.width, 0.5), "按一下以編輯副題", _style(TYPE.cover_subtitle, "tx2")
        )
        + _rule(6, "Meta Rule", L.left, 6.0, L.width, _rule_color(), T.LINE_HAIR)
        + _placeholder(
            7, "Author", "body", IDX_META, (L.left, 6.15, L.width, 0.4), "作者", _style(TYPE.cover_meta, "accent5"), size_attr=' sz="quarter"'
        )
    )
    layouts[TITLE_SLIDE] = _layout(TITLE_SLIDE, "title", cover_shapes, hide_master=True)

    layouts[TITLE_ONLY] = _layout(TITLE_ONLY, "titleOnly", title + ref + foot)
    layouts["Title and Content"] = _layout("Title and Content", "obj", title + body(4, IDX_BODY, content_box) + foot)
    layouts["Section Header"] = _layout(
        "Section Header",
        "secHead",
        _placeholder(2, "Title", "title", IDX_TITLE, (L.left, 2.6, L.width, 1.2), "按一下以編輯標題", _style(TYPE.cover_title - 4, "tx1", bold=True, spacing=1.05), anchor="b")
        + _placeholder(3, "Text", "body", IDX_BODY, (L.left, 4.0, L.width, 0.8), "按一下以編輯文字", _style(TYPE.cover_subtitle, "tx2"), size_attr=' sz="quarter"')
        + foot,
    )
    layouts["Two Content"] = _layout(
        "Two Content",
        "twoObj",
        title
        + body(4, IDX_BODY, (L.left, L.top, half, L.bottom - L.top))
        + body(5, IDX_BODY2, (L.left + half + L.gap, L.top, half, L.bottom - L.top))
        + foot,
    )
    head_h = 0.5
    layouts["Comparison"] = _layout(
        "Comparison",
        "twoTxTwoObj",
        title
        + _placeholder(4, "Text Left", "body", IDX_BODY, (L.left, L.top, half, head_h), "按一下以編輯文字", _style(TYPE.panel_title, "tx1", bold=True), size_attr=' sz="quarter"')
        + body(5, IDX_BODY2, (L.left, L.top + head_h + L.gap, half, L.bottom - L.top - head_h - L.gap))
        + _placeholder(6, "Text Right", "body", IDX_BODY3, (L.left + half + L.gap, L.top, half, head_h), "按一下以編輯文字", _style(TYPE.panel_title, "tx1", bold=True), size_attr=' sz="quarter"')
        + body(7, IDX_BODY4, (L.left + half + L.gap, L.top + head_h + L.gap, half, L.bottom - L.top - head_h - L.gap))
        + foot,
    )
    side = L.side_w
    layouts["Content with Caption"] = _layout(
        "Content with Caption",
        "objTx",
        _placeholder(2, "Title", "title", IDX_TITLE, (L.left, 0.70, side, 1.2), "按一下以編輯標題")
        + body(3, IDX_BODY, (L.left + side + L.side_gap, L.top, L.width - side - L.side_gap, L.bottom - L.top))
        + _placeholder(4, "Text", "body", IDX_BODY2, (L.left, 2.1, side, 3.0), "按一下以編輯文字", _style(TYPE.panel_body + 1, "tx2"), size_attr=' sz="half"')
        + foot,
    )
    layouts["Blank"] = _layout("Blank", "blank", foot)
    return layouts


# ---- 組裝 ----

def _replace(element: Any, xml: str) -> None:
    """用 `xml` 的子節點與屬性換掉 `element` 現有的內容；保留 element 自己的身分（關聯與父子）。"""
    new = parse_xml(xml)
    for child in list(element):
        element.remove(child)
    for key in list(element.attrib):
        del element.attrib[key]
    for key, value in new.attrib.items():
        element.set(key, value)
    for child in new:
        element.append(child)


def new_presentation() -> Any:
    """由設計規格產生的空簡報：佈景主題、母片、八個版面，沒有投影片。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(L.slide_w), Inches(L.slide_h)
    master = prs.slide_master

    theme_part = master.part.part_related_by(RT.THEME)
    theme_part._blob = _apply_theme(theme_part.blob)

    csld, tx = _master_xml_parts()
    old_csld = master._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}cSld")
    old_csld.getparent().replace(old_csld, parse_xml(csld))
    old_tx = master._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}txStyles")
    old_tx.getparent().replace(old_tx, parse_xml(tx))

    layouts = _layouts()
    existing = {layout.name: layout for layout in prs.slide_layouts}
    # 預設範本沒有 Title Only 以外要新增的名稱：重用同名版面，其餘（含用不到的）移除
    spare = [layout for layout in prs.slide_layouts if layout.name not in layouts]
    for name, xml in layouts.items():
        layout = existing.get(name) or spare.pop(0)
        _replace(layout._element, xml)
    for layout in spare:
        prs.slide_layouts.remove(layout)
    # 版面順序：依 LAYOUT_ORDER 排列母片的 sldLayoutIdLst
    id_list = master._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}sldLayoutIdLst")
    by_name = {layout.name: layout for layout in prs.slide_layouts}
    rid_of = {rel.target_part: rid for rid, rel in master.part.rels.items() if rel.reltype == RT.SLIDE_LAYOUT}
    entries = {e.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"): e for e in id_list}
    ordered = [entries[rid_of[by_name[n].part]] for n in LAYOUT_ORDER]
    for e in list(id_list):
        id_list.remove(e)
    for e in ordered:
        id_list.append(e)
    return prs


def open_template(path: str | Path | None = None) -> Any:
    """`path` 給了就用那份範本（先確認引擎要的版面與佔位符都在）；沒給就由設計規格產生。"""
    if path is None:
        return new_presentation()
    prs = Presentation(str(path))
    check_contract(prs)
    return prs


def layout_named(prs: Any, name: str) -> Any:
    """依名稱找版面；同名取第一個（與 Quarto、pandoc 一致）。"""
    for layout in prs.slide_layouts:
        if layout.name == name:
            return layout
    raise ValueError(f"範本沒有名為 {name!r} 的版面（有：{', '.join(layout.name for layout in prs.slide_layouts)}）")


_CONTRACT = {TITLE_SLIDE: {IDX_TITLE, IDX_BODY, IDX_REF, IDX_META}, TITLE_ONLY: {IDX_TITLE, IDX_REF, IDX_FOOTER, IDX_NUMBER}}


def check_contract(prs: Any) -> None:
    """引擎依賴的版面與佔位符 idx 缺了就停下，並說明缺什麼。"""
    for name, needed in _CONTRACT.items():
        have = {ph.placeholder_format.idx for ph in layout_named(prs, name).placeholders}
        if needed - have:
            raise ValueError(f"範本的版面 {name!r} 缺佔位符 idx {sorted(needed - have)}（需要 {sorted(needed)}）")


def add_footer_placeholders(slide: Any, layout: Any, footer_text: str) -> None:
    """把版面的頁尾與頁碼佔位符放到這一頁（python-pptx 的 add_slide 不會複製這兩種）。"""
    for ph in layout.placeholders:
        idx = ph.placeholder_format.idx
        if idx not in (IDX_FOOTER, IDX_NUMBER):
            continue
        el = copy.deepcopy(ph._element)
        el.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr").set("id", str(slide.shapes._next_shape_id))
        sp_pr = el.find("{http://schemas.openxmlformats.org/presentationml/2006/main}spPr")
        for child in list(sp_pr):
            sp_pr.remove(child)
        tx = el.find("{http://schemas.openxmlformats.org/presentationml/2006/main}txBody")
        for child in list(tx):
            tx.remove(child)
        tx.append(parse_xml(f"<a:bodyPr {_NS}/>"))
        tx.append(parse_xml(f"<a:lstStyle {_NS}/>"))
        if idx == IDX_FOOTER:
            tx.append(parse_xml(f'<a:p {_NS}><a:r><a:rPr lang="zh-TW"/><a:t>{_esc(footer_text)}</a:t></a:r></a:p>'))
        else:
            tx.append(
                parse_xml(f'<a:p {_NS}><a:fld id="{{{str(uuid.uuid4()).upper()}}}" type="slidenum"><a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld></a:p>')
            )
        slide.shapes._spTree.append(el)  # 位置與字型沿用版面；放在最後，閱讀順序是標題、內容、頁尾


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print("用法：deck_template.py <輸出.pptx>（需 python-pptx；一般用 build_deck.py --emit-template）匯出由設計規格產生的範本。", file=sys.stderr)
        return 2
    new_presentation().save(argv[1])
    print(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
