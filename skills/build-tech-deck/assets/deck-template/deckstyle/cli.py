"""命令列入口：`deckstyle new | build | preview | lint | outline | inspect | schema | template | theme`。

    uv run deckstyle new deck/                       # 從範本建一份簡報（deck.yml 與 screens/）
    uv run deckstyle build deck/                     # 建置並跑 lint；加 --pdf 另以 PowerPoint 匯出向量 PDF
    uv run deckstyle preview deck/ --watch           # 建置、轉成逐頁 PNG 與接觸表，來源一變就重建
    uv run deckstyle lint out.pptx --deny shop-api   # 只檢查既有的 .pptx
    uv run deckstyle outline deck/                   # 規格 → Markdown 大綱（供 diff 與審稿）
    uv run deckstyle inspect deck/                   # 列出作者等中繼資料的分層來源與合併結果
    uv run deckstyle schema spec -o spec.schema.json # 輸出 JSON Schema，給編輯器補全與驗證 deck.yml
    uv run deckstyle template -o brand.pptx          # 輸出空的品牌範本（主題、母片、具名版面）
    uv run deckstyle theme                           # 驗證並列出品牌（_brand.yml）與設計參數（design.yml）

簡報來源是 `deck.yml`（YAML，鍵用 kebab-case）；傳目錄時找 `deck.yml`、`deck.yaml`。

結束碼：0 通過｜1 lint 有違規或規格有誤｜2 用法錯誤、檔案不存在或 PDF 匯出失敗。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import brand, config, design, yamlio
from .export import ExportError
from .preview import PreviewError
from .spec import SpecError, from_yaml
from .theme import Theme

TEMPLATE_DIR = Path(__file__).with_name("template")
SPEC_FILES = ("deck.yml", "deck.yaml")  # 傳目錄時依序找
SPEC_NAME = SPEC_FILES[0]


class CliError(Exception):
    """用法或環境錯誤（檔案不存在、目標已有檔案…）；訊息直接印給使用者。"""


def find_spec(path: Path) -> Path:
    """規格檔路徑：傳檔案就是它；傳目錄就依 `SPEC_FILES` 的順序找第一個存在的。"""
    path = path.resolve()
    if path.is_dir():
        found = next((path / n for n in SPEC_FILES if (path / n).is_file()), None)
        if found is None:
            raise CliError(f"{path} 裡沒有規格檔（{'、'.join(SPEC_FILES)}）")
        return found
    if not path.is_file():
        raise CliError(f"找不到規格檔：{path}")
    return path


def load_raw(path: Path) -> tuple[dict[str, Any], Path]:
    """載入 `deck.yml`，鍵由 kebab-case 換成內部的 snake_case，回傳（規格, 簡報目錄）；不做分層合併。"""
    path = find_spec(path)
    try:
        data = yamlio.load(path)
    except yamlio.YamlError as e:
        raise CliError(str(e)) from None
    if not isinstance(data, dict):
        raise CliError(f"{path.name}：最上層須為對應表")
    return from_yaml(data), path.parent


def load_spec(path: Path) -> tuple[dict[str, Any], Path]:
    """`load_raw` 再依 `_quarto.yml`／`_metadata.yml` 分層合併作者等中繼資料；建置與大綱都用這個。"""
    spec, base = load_raw(path)
    return config.resolve(spec, base), base


def _report(label: str, issues: list[dict[str, Any]], fmt: Any, ok: str) -> None:
    for i in issues:
        print(fmt(i))
    print(f"{label}：" + (f"違規 {len(issues)} 處" if issues else ok), file=sys.stderr)


def _lint_file(
    pptx: Path, deny: Sequence[str], allow: Sequence[str], safety: float | None, notes: bool, as_json: bool
) -> int:
    from . import lint

    wrap = lint.lint_wrap(pptx, safety)
    names = lint.lint_names(pptx, deny, allow, notes)
    if as_json:
        print(json.dumps({"wrap": wrap, "names": names}, ensure_ascii=False, indent=2))
    else:
        _report("折行檢查", wrap, lint.format_wrap, "未發現折行風險")
        _report("白話命名", names, lint.format_names, "未發現倉庫或代碼名稱")
    return 1 if wrap or names else 0


def _default_out(spec: dict[str, Any], base: Path) -> Path:
    return base / "_output" / f"{spec.get('output_file') or base.name}.pptx"


def cmd_build(args: argparse.Namespace) -> int:
    from . import engine
    from .outline import export

    spec, base = load_spec(args.spec)
    out = args.output or _default_out(spec, base)
    pages = engine.build(spec, out, base, Theme.load(base, spec["lang"]))
    print(f"✓ {out}（{pages} 頁）", file=sys.stderr)
    if args.outline:
        args.outline.write_text(export(spec), encoding="utf-8")
        print(f"✓ {args.outline}", file=sys.stderr)
    status = 0
    if not args.no_lint:
        cfg = spec.get("lint", {})
        status = _lint_file(out, cfg.get("deny", ()), cfg.get("allow", ()), None, True, False)
    if args.pdf:
        from .export import export_pdf

        pdf = out.with_suffix(".pdf")
        export_pdf(out, pdf)
        print(f"✓ {pdf}（{pdf.stat().st_size // 1024} KB）", file=sys.stderr)
    return status


def cmd_lint(args: argparse.Namespace) -> int:
    status = 0
    for f in args.pptx:
        if not f.is_file():
            raise CliError(f"找不到檔案：{f}")
        if len(args.pptx) > 1:
            print(f"== {f}", file=sys.stderr)
        status |= _lint_file(
            f,
            [w for w in args.deny.split(",") if w],
            [w for w in args.allow.split(",") if w],
            args.safety,
            not args.no_notes,
            args.json,
        )
    return status


def cmd_new(args: argparse.Namespace) -> int:
    dest: Path = args.dir
    if (dest / SPEC_NAME).exists() and not args.force:
        raise CliError(f"{dest / SPEC_NAME} 已存在；要覆蓋請加 --force")
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "_output"))
    print(f"✓ 範本已複製到 {dest}：改 {SPEC_NAME}，再執行 deckstyle build {dest}", file=sys.stderr)
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    from .outline import export

    spec, _ = load_spec(args.spec)
    _emit(export(spec), args.output)
    return 0


def _watched(spec_path: Path, base: Path) -> list[Path]:
    """預覽時要監看的檔案：規格、各層設定、品牌、設計參數與簡報目錄裡的圖片。"""
    images = [p for ext in ("png", "jpg", "jpeg", "gif") for p in base.rglob(f"*.{ext}") if "_output" not in p.parts]
    found = brand.find(base)
    return [spec_path, design.DESIGN_PATH, *config.layer_files(base), *([found] if found else []), *images]


def cmd_preview(args: argparse.Namespace) -> int:
    from . import engine
    from .export import export_pdf
    from .preview import contact_sheets, render_pages, watch

    spec_path = find_spec(args.spec)

    def once() -> None:
        try:
            spec, base = load_spec(spec_path)
            out = args.output or _default_out(spec, base)
            pages = engine.build(spec, out, base, Theme.load(base, spec["lang"]))
            pdf = out.with_suffix(".pdf")
            export_pdf(out, pdf)
            shots = render_pages(pdf, out.parent / "preview", args.dpi)
            sheets = contact_sheets(shots, out.parent / "preview")
            cfg = spec.get("lint", {})
            lint_status = _lint_file(out, cfg.get("deny", ()), cfg.get("allow", ()), None, True, False)
            print(
                f"✓ 預覽（{pages} 頁）：{out.parent / 'preview'}（接觸表 {', '.join(p.name for p in sheets)}）",
                file=sys.stderr,
            )
            if lint_status:
                print("lint 有違規，見上方", file=sys.stderr)
        except (
            SpecError,
            brand.BrandError,
            design.DesignError,
            CliError,
            ExportError,
            PreviewError,
            FileNotFoundError,
        ) as e:
            if not args.watch:
                raise
            print(f"✗ {e}", file=sys.stderr)  # 監看模式：印出錯誤，改好存檔後自動重試

    if not args.watch:
        once()
        return 0
    base = spec_path.parent
    print(f"監看 {spec_path}（Ctrl-C 結束）", file=sys.stderr)
    try:
        watch(once, lambda: _watched(spec_path, base), interval=args.interval)
    except KeyboardInterrupt:
        print("\n結束監看", file=sys.stderr)
    return 0


def _emit(text: str, output: Path | None) -> None:
    if output:
        output.write_text(text, encoding="utf-8")
        print(f"✓ {output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def cmd_schema(args: argparse.Namespace) -> int:
    from . import schema

    _emit(json.dumps(schema.schemas()[args.name], ensure_ascii=False, indent=2) + "\n", args.output)
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    from . import template

    prs = template.build(Theme.load(args.brand_from or Path.cwd()))
    prs.save(str(args.output))
    print(f"✓ {args.output}（品牌範本：{len(prs.slide_layouts)} 個版面，無頁面）", file=sys.stderr)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    spec, base = load_raw(args.spec)
    print(config.describe(spec, base))
    return 0


def _theme_summary(t: Theme) -> str:
    b, lay = t.brand, t.layout
    lines = [
        f"品牌：{b.name}（{b.path}）",
        f"字型：{b.font}",
        "語義色：" + "  ".join(f"{k}={v}" for k, v in b.color.items()),
    ]
    lines.append("色票：" + "  ".join(f"{k}={v}" for k, v in b.palette.items()))
    lines += [
        f"版面：{lay.slide_w:g}×{lay.slide_h:g} in，內容區 x {lay.left:g}–{lay.right:g}、y {lay.top:g}–{lay.bottom:g}",
        f"轉場：{t.page.transition}；頁尾：{'顯示' if t.page.footer else '隱藏'}",
        f"lint：安全係數 {t.lint.safety:g}、孤字 <= {t.lint.orphan_chars:g} 字",
    ]
    return "\n".join(lines)


def cmd_theme(args: argparse.Namespace) -> int:
    t = Theme.load(args.start or Path.cwd())
    print(_theme_summary(t))
    print("✓ _brand.yml 與 design.yml 驗證通過", file=sys.stderr)
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deckstyle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="由規格產出 .pptx 並跑 lint")
    b.add_argument("spec", type=Path, help="deck.yml，或含它的目錄")
    b.add_argument("-o", "--output", type=Path, help="輸出 .pptx（預設：<簡報目錄>/_output/<output-file>.pptx）")
    b.add_argument("--pdf", action="store_true", help="另以 PowerPoint 匯出同名向量 PDF（僅 macOS）")
    b.add_argument("--no-lint", action="store_true", help="不跑折行與白話命名檢查")
    b.add_argument("--outline", type=Path, metavar="FILE", help="另把 Markdown 大綱寫到 FILE")
    b.set_defaults(fn=cmd_build)

    pv = sub.add_parser("preview", help="建置並轉成逐頁 PNG 與接觸表（需 PowerPoint 與 pdftoppm）")
    pv.add_argument("spec", type=Path)
    pv.add_argument("-o", "--output", type=Path, help="輸出 .pptx（預設同 build）；PNG 在它旁邊的 preview/")
    pv.add_argument("--watch", action="store_true", help="來源（規格、圖片、品牌、設計參數）一變就重建，Ctrl-C 結束")
    pv.add_argument("--interval", type=float, default=0.5, help="監看的輪詢秒數")
    pv.add_argument("--dpi", type=int, default=72)
    pv.set_defaults(fn=cmd_preview)

    li = sub.add_parser("lint", help="檢查既有的 .pptx：零折行與白話命名")
    li.add_argument("pptx", type=Path, nargs="+")
    li.add_argument("--deny", default="", help="額外禁用的倉庫名稱與服務代號，逗號分隔")
    li.add_argument("--allow", default="", help="放行的字串，逗號分隔")
    li.add_argument("--safety", type=float, help="可用寬度的安全係數（預設取 design.yml 的 lint.safety）")
    li.add_argument("--no-notes", action="store_true", help="不檢查講稿備註")
    li.add_argument("--json", action="store_true", help="以 JSON 輸出違規清單")
    li.set_defaults(fn=cmd_lint)

    n = sub.add_parser("new", help="從範本建立簡報目錄")
    n.add_argument("dir", type=Path)
    n.add_argument("--force", action="store_true", help="目錄已有 deck.yml 時覆蓋")
    n.set_defaults(fn=cmd_new)

    o = sub.add_parser("outline", help="規格 → Markdown 大綱")
    o.add_argument("spec", type=Path)
    o.add_argument("-o", "--output", type=Path, help="寫到檔案（省略則印到標準輸出）")
    o.set_defaults(fn=cmd_outline)

    i = sub.add_parser("inspect", help="列出分層中繼資料（_quarto.yml、_metadata.yml）與合併結果")
    i.add_argument("spec", type=Path)
    i.set_defaults(fn=cmd_inspect)

    sc = sub.add_parser("schema", help="輸出 JSON Schema")
    sc.add_argument("name", choices=("spec", "metadata"))
    sc.add_argument("-o", "--output", type=Path)
    sc.set_defaults(fn=cmd_schema)

    tp = sub.add_parser("template", help="輸出空的品牌範本（主題、母片、具名版面）")
    tp.add_argument("-o", "--output", type=Path, required=True)
    tp.add_argument("--brand-from", type=Path, help="從哪個目錄往上找 _brand.yml（預設目前目錄）")
    tp.set_defaults(fn=cmd_template)

    th = sub.add_parser("theme", help="驗證並列出品牌（_brand.yml）與設計參數（design.yml）")
    th.add_argument("start", type=Path, nargs="?", help="從哪個目錄往上找 _brand.yml（預設目前目錄）")
    th.set_defaults(fn=cmd_theme)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except (SpecError, brand.BrandError, design.DesignError) as e:
        print(f"規格有誤：{e}", file=sys.stderr)
        if isinstance(e, SpecError):
            print("（欄位表：deckstyle schema spec；第 N 頁從封面算起）", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"檔案不存在：{e}", file=sys.stderr)
        return 2
    except (CliError, ExportError, PreviewError) as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
