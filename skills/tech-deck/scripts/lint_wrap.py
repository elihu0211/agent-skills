# /// script
# requires-python = ">=3.11"
# dependencies = ["python-pptx>=1.0,<2"]
# ///
"""零折行靜態檢查：估算每段文字寬度，找出會折行、孤字或單行過長的段落。

用法：uv run lint_wrap.py deck.pptx [--safety 0.8] [--json]
結束碼：0 無違規；1 有違規；2 用法錯誤。估算以字級與字元寬度換算（全形 1.0 em、半形 0.55 em），
不取代轉 PDF／圖片後的逐頁目視，只負責在渲染前攔下明顯的折行。
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

DEFAULT_PT = 18.0     # run 沒指定字級時的預設
ORPHAN_CHARS = 4      # 折行後最後一行 ≤ 此字數視為孤字


def char_em(ch: str) -> float:
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    return 0.3 if ch == " " else 0.55


def para_width_pt(par) -> tuple[float, float]:
    """回傳 (段落估算寬度 pt, 代表字級 pt)。粗體多估 5%。"""
    total, size = 0.0, DEFAULT_PT
    for run in par.runs:
        size = run.font.size.pt if run.font.size else size
        em = sum(char_em(c) for c in run.text) * size
        total += em * (1.05 if run.font.bold else 1.0)
    return total, size


def frame_width_pt(shape, frame) -> float:
    left = frame.margin_left if frame.margin_left is not None else Emu(91440)
    right = frame.margin_right if frame.margin_right is not None else Emu(91440)
    return Emu(shape.width - left - right).pt


def check_frame(slide_no, label, frame, avail_pt, slide_w_pt, left_pt, safety, wraps, out):
    for par in frame.paragraphs:
        text = "".join(r.text for r in par.runs)
        if not text.strip():
            continue
        width, size = para_width_pt(par)
        if wraps:
            limit = avail_pt * safety
            if width > limit:
                lines = int(width // avail_pt) + 1
                tail = width - (lines - 1) * avail_pt
                kind = "孤字" if lines >= 2 and tail <= ORPHAN_CHARS * size else "折行"
                out.append({"slide": slide_no, "where": label, "type": kind, "text": text[:40],
                            "width_pt": round(width), "limit_pt": round(limit)})
        else:
            # 不折行的單行框（標題、分類標籤）：超過框寬（留 5% 餘裕）就會壓到版心外；不受 --safety 影響
            limit = min(avail_pt * 0.95, slide_w_pt - left_pt)
            if width > limit:
                out.append({"slide": slide_no, "where": label, "type": "單行過長", "text": text[:40],
                            "width_pt": round(width), "limit_pt": round(limit)})


def lint(path: str, safety: float) -> list[dict]:
    prs = Presentation(path)
    slide_w_pt = Emu(prs.slide_width).pt
    out: list[dict] = []
    for no, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame:
                frame = shape.text_frame
                avail = frame_width_pt(shape, frame)
                check_frame(no, shape.name, frame, avail, slide_w_pt, Emu(shape.left).pt, safety,
                            frame.word_wrap is not False, out)
            elif shape.has_table:
                for r, row in enumerate(shape.table.rows):
                    for c, cell in enumerate(row.cells):
                        width = Emu(shape.table.columns[c].width - cell.margin_left - cell.margin_right).pt
                        check_frame(no, f"表格[{r},{c}]", cell.text_frame, width, slide_w_pt, 0, safety, True, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", help="要檢查的 .pptx")
    ap.add_argument("--safety", type=float, default=0.8,
                    help="可用寬度的安全係數（預設 0.8，對應 3 欄卡片每行 ≤ 14 字；跨應用字型寬度有差異）")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出違規清單")
    args = ap.parse_args()
    if not Path(args.pptx).is_file():
        print(f"找不到檔案：{args.pptx}", file=sys.stderr)
        return 2
    issues = lint(args.pptx, args.safety)
    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        for i in issues:
            print(f"第 {i['slide']} 頁 {i['where']}：{i['type']}（估 {i['width_pt']}pt > 上限 {i['limit_pt']}pt）「{i['text']}」")
        print(f"{'違規 ' + str(len(issues)) + ' 處' if issues else '未發現折行風險'}", file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
