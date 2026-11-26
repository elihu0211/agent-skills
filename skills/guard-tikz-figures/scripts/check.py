#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf>=1.24", "shapely>=2"]
# ///
"""把文件來源裡的每張 TikZ 圖單獨編譯，量出節點、連線與標籤的實際位置，有任何壓疊就列出並擋下。

量的是編譯後 PDF 裡真正畫出來的東西（PyMuPDF 讀圖形與文字），不是猜原始碼：
  節點互壓或太近｜連線穿過兩端以外的節點｜邊標籤壓到節點、其他標籤或箭頭｜字超出節點外形｜
  兩條連線有一段疊在一起｜（指定 --max-width 時）圖寬超過上限。
規則與修法見 ../references/rules.md。

用法：
  uv run check.py docs/                         遞迴檢查目錄下含 tikzpicture 的 .qmd／.tex
  uv run check.py a.qmd b.tex --json            JSON 輸出
  uv run check.py fig.tex --mode latex --preamble styles.tex
兩種編譯模式（--mode auto 依來源判斷：上層有 _quarto.yml 就用 quarto，否則 latex）：
  quarto  在來源檔旁暫放 .qmd，以 quarto render 取得專案實際的 LaTeX 前置（繼承 _quarto.yml 與 _metadata.yml），
          之後每張圖用同一份前置直接編譯；暫存檔與產出在結束時刪除，前置依設定檔雜湊快取。
  latex   以 --preamble（可多個）當前置；沒給時，來源本身是完整文件就用它自己的前置，否則只載入 tikz。
每張圖依「前置＋圖原始碼」的雜湊快取量測結果，只重編改過的圖。

結束碼：0 通過｜1 圖有問題（含圖本身編譯失敗）｜2 執行環境問題（找不到 TeX、Quarto、檔案，或前置編不過）。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MEASURE_VERSION = 3  # 量測輸出格式變更時加一，讓舊快取失效

PAGE = "paperwidth=150cm,paperheight=150cm,margin=5cm"
SKIP_DIRS = {"node_modules", "site_libs"}
TEX_HOMES = ("~/Library/TinyTeX/bin/*", "~/.TinyTeX/bin/*", "/Library/TeX/texbin", "/usr/local/texlive/*/bin/*",
             "~/AppData/Roaming/TinyTeX/bin/*")
DEFAULT_PREAMBLE = (
    "\\usepackage{tikz}\n"
    "\\usetikzlibrary{arrows.meta,positioning,fit,calc,shapes.geometric,shapes.misc,backgrounds}\n"
)
# 只從來源 frontmatter 帶走會進 LaTeX 前置的鍵（Pandoc／Quarto 的 LaTeX 範本變數），
# 其餘（標題、日期、自訂欄位）每份文件都不同，帶了會讓每份文件各 render 一次前置
FRONTMATTER_KEEP = re.compile(
    r"format|pdf-engine(-opts)?|documentclass|classoption|fontsize|geometry|papersize|margin-\w+|\w*fonts?(options)?"
    r"|CJK\w*|fontfamily(options)?|linestretch|lang|dir|header-includes|include-in-header|colorlinks|\w+color"
    r"|indent|block-headings|pagestyle|template(-partials)?|latex-\w+|mathspec|microtypeoptions|hyperrefoptions")

# 判斷門檻（PDF 點，約等於 TeX pt）
END_TOL = 4.0        # 線端離節點外形這麼近，就算接到該節點
SHRINK = 2.0         # 判斷「穿過」時節點先內縮，接在邊界上的起訖點不算穿過
OVERLAP_MIN = 6.0    # 兩條線共線重疊超過這個長度才算疊在一起
COLLINEAR = 0.8      # 平行線段相距這麼近就算共線
SAME_PORT = 1.5      # 兩條線的端點這麼近算同一接點（分岔、匯流）
TIP_MAX = 14.0       # 箭頭與圓點的最大尺寸
LABEL_TOL = 0.5      # 標籤框先內縮這麼多再判斷壓疊（貼邊不算）
LABEL_AREA = 2.0     # 標籤框和節點重疊面積超過這個才算（角落擦過一點不算）
TEXT_TOL = 0.5       # 字可以壓進框線多少
TIP_COVER = 0.25     # 標籤蓋住箭頭面積超過這個比例才算（標籤貼著自己的線、擦過翼尖不算）
RECT_LIKE = 0.9      # 面積／外框面積達此比例就以外框判斷（圓角矩形、膠囊）

RULES = ("node-overlap", "edge-through-node", "label-on-node", "label-on-label", "label-on-arrow",
         "text-overflow", "edge-overlap", "figure-width", "compile")
ALLOW = re.compile(r"%\s*tikz-guard:\s*allow\s+([a-z-]+(?:\s*,\s*[a-z-]+)*)")


class EnvError(Exception):
    """執行環境問題：結束碼 2。"""


# ---------- 來源 ----------


@dataclass
class Figure:
    file: Path
    line: int
    index: int
    code: str
    label: str | None = None
    allow: set[str] = field(default_factory=set)

    @property
    def where(self) -> str:
        tag = f" {self.label}" if self.label else ""
        return f"{self.file}:{self.line}{tag}"


def mask_comments(text: str) -> str:
    """把 LaTeX 註解換成空白（保留位置），找環境時才不會把註解裡的字當真。"""
    return re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*", lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), text)


BEGIN_FIG = re.compile(r"\\begin\{(figure|wrapfigure|subfigure|SCfigure|marginfigure)\*?\}")


def scan_latex(text: str, file: Path, line0: int, div_label: str | None, start_index: int) -> list[Figure]:
    """在一段 LaTeX 裡找最外層的 tikzpicture；line0 是 text 第一行在檔案裡的行號。"""
    masked = mask_comments(text)
    figures, depth, start = [], 0, 0
    for m in re.finditer(r"\\(begin|end)\{tikzpicture\}", masked):
        if m.group(1) == "begin":
            if depth == 0:
                start = m.start()
            depth += 1
            continue
        if depth == 0:
            continue
        depth -= 1
        if depth:
            continue
        code = text[start : m.end()]
        if re.search(r"(?<!\\)#[1-9]", mask_comments(code)):
            continue  # 巨集定義裡的圖（含 #1 參數）無法單獨編譯
        above = re.search(r"(?:^[ \t]*%[^\n]*\n)*[ \t]*\Z", text[:start], re.MULTILINE)
        marks = ALLOW.findall(code) + ALLOW.findall(above.group(0) if above else "")
        allow = {r.strip() for found in marks for r in found.split(",") if r.strip()}
        figures.append(Figure(file, line0 + text.count("\n", 0, start), start_index + len(figures) + 1, code,
                              _figure_label(masked, start, m.end()) or div_label, allow))
    return figures


def _figure_label(masked: str, start: int, end: int) -> str | None:
    """同一個 figure 環境裡的 \\label；優先取 fig: 開頭的。"""
    opens = [m for m in BEGIN_FIG.finditer(masked, 0, start)]
    for env in reversed(opens):
        name = env.group(0)[len("\\begin{") : -1]
        if f"\\end{{{name}}}" in masked[env.end() : start]:
            continue
        close = masked.find(f"\\end{{{name}}}", end)
        span = masked[env.start() : close if close >= 0 else len(masked)]
        labels = re.findall(r"\\label\{([^}]+)\}", span)
        return next((x for x in labels if x.startswith("fig")), labels[0] if labels else None)
    return None


FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*\{=(latex|tex)\}\s*$")
DIV = re.compile(r"^\s*(:{3,})\s*(.*)$")


def scan_qmd(text: str, file: Path) -> list[Figure]:
    """從 {=latex} raw block 抽圖；Quarto 的 ::: {#fig-…} 區塊當圖標籤的後備。"""
    figures: list[Figure] = []
    lines = text.split("\n")
    divs: list[str | None] = []
    i = 0
    while i < len(lines):
        fence = FENCE.match(lines[i])
        if fence:
            mark = fence.group(2)
            j = i + 1
            while j < len(lines) and not re.match(rf"^\s*{re.escape(mark[0])}{{{len(mark)},}}\s*$", lines[j]):
                j += 1
            label = next((d for d in reversed(divs) if d), None)
            figures += scan_latex("\n".join(lines[i + 1 : j]), file, i + 2, label, len(figures))
            i = j + 1
            continue
        div = DIV.match(lines[i])
        if div and lines[i].lstrip().startswith(":::"):
            rest = div.group(2).strip()
            if rest:
                found = re.search(r"#(fig-[\w-]+)", rest)
                divs.append(found.group(1) if found else None)
            elif divs:
                divs.pop()
        i += 1
    return figures


def scan_file(path: Path) -> list[Figure]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise EnvError(f"讀不到 {path}：{e}") from e
    if path.suffix == ".qmd":
        return scan_qmd(text, path)
    return scan_latex(text, path, 1, None, 0)


def find_sources(paths: list[Path]) -> list[Path]:
    """展開目錄：遞迴找含 tikzpicture 的 .qmd／.tex，略過 . 與 _ 開頭的目錄（輸出、快取、外掛）。"""
    out: list[Path] = []
    for path in paths:
        if not path.exists():
            raise EnvError(f"找不到 {path}")
        if path.is_file():
            out.append(path)
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")) and d not in SKIP_DIRS
                             and not d.endswith("_files"))
            for name in sorted(files):
                p = Path(root) / name
                if p.suffix in (".qmd", ".tex") and not name.startswith("tikz-guard-"):
                    try:
                        if "tikzpicture" in p.read_text(encoding="utf-8", errors="ignore"):
                            out.append(p)
                    except OSError:
                        continue
    return list(dict.fromkeys(out))


# ---------- 工具鏈 ----------


def find_tool(name: str) -> str | None:
    """PATH 上找不到時，再找 TinyTeX 與 TeX Live 的常見安裝位置。"""
    if os.sep in name or (os.altsep and os.altsep in name):
        return name if Path(name).is_file() else None
    found = shutil.which(name)
    if found:
        return found
    for pattern in TEX_HOMES:
        for d in sorted(glob.glob(os.path.expanduser(pattern))):
            for cand in (Path(d) / name, Path(d) / f"{name}.exe"):
                if cand.is_file():
                    return str(cand)
    return None


def engine_binary(engine: str) -> str:
    binary = find_tool(engine)
    if not binary:
        raise EnvError(f"找不到 {engine}：安裝 TeX Live 或 TinyTeX（quarto install tinytex），或以 --engine 指定路徑")
    return binary


def project_root(path: Path) -> Path | None:
    for d in [path.parent, *path.parent.parents]:
        if (d / "_quarto.yml").is_file() or (d / "_quarto.yaml").is_file():
            return d
    return None


def frontmatter(text: str) -> str:
    """來源 .qmd 的 frontmatter，去掉與 LaTeX 前置無關的頂層鍵。"""
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return ""
    keep, out = False, []
    for line in m.group(1).split("\n"):
        key = re.match(r"^([A-Za-z][\w-]*)\s*:", line)
        if key:
            keep = bool(FRONTMATTER_KEEP.fullmatch(key.group(1)))
        elif not line.startswith((" ", "\t", "-")):
            keep = False
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def config_files(root: Path, src_dir: Path) -> list[Path]:
    """影響前置的設定檔：_quarto*.yml、沿路的 _metadata.yml，以及它們提到的 .tex／.sty／.cls。"""
    files = sorted(root.glob("_quarto*.y*ml"))
    d = src_dir
    chain = []
    while True:
        for name in ("_metadata.yml", "_metadata.yaml"):
            if (d / name).is_file():
                chain.append(d / name)
        if d == root or d.parent == d:
            break
        d = d.parent
    files += reversed(chain)
    extra = []
    for f in files:
        for token in re.findall(r"[\w./-]+\.(?:tex|sty|cls|ya?ml)", f.read_text(encoding="utf-8", errors="ignore")):
            for base in (f.parent, root):
                cand = (base / token).resolve()
                if cand.is_file() and cand not in extra and cand not in files:
                    extra.append(cand)
                    break
    return files + extra


def snapshot(root: Path) -> set[Path]:
    seen = set()
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        seen.update(Path(r) / x for x in dirs + files)
    return seen


def cleanup_quarto(root: Path, before: set[Path], stem: str) -> None:
    """刪掉 quarto render 為暫存檔留下的東西：檔名含 stem 的新檔、.quarto/ 下新出現的檔案（索引、快取）、
    交叉引用索引裡的條目，以及因此變空的新目錄。原本就有的檔案不動。"""
    index = root / ".quarto" / "xref" / "INDEX"
    if index.is_file():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            for key in [k for k in data if stem in k]:
                for ref in (data.pop(key) or {}).values():
                    (index.parent / str(ref)).unlink(missing_ok=True)
            if data or index in before:
                index.write_text(json.dumps(data), encoding="utf-8")
            else:
                index.unlink()
        except (OSError, ValueError):
            pass
    cache = root / ".quarto"
    new = snapshot(root) - before
    for p in sorted(new, key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_dir() and not p.is_symlink():
                if stem in p.name:
                    shutil.rmtree(p, ignore_errors=True)
                elif not any(p.iterdir()):
                    p.rmdir()
            elif stem in p.name or cache in p.parents:
                p.unlink(missing_ok=True)
        except OSError:
            continue


@dataclass
class Context:
    """一組共用前置的編譯環境。"""
    engine: str
    preamble: str
    body_head: str
    inputs: list[Path]
    key: str


def run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=False, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        raise EnvError(f"{Path(cmd[0]).name} 超過 {timeout} 秒沒有結束（--timeout 可調）") from e
    except OSError as e:
        raise EnvError(f"無法執行 {cmd[0]}：{e}") from e


PROBES: dict[str, dict] = {}  # 本次執行已取得的 Quarto 前置（--no-cache 時也不重複 render）


def quarto_context(src: Path, args, cache: Path | None) -> Context:
    root = project_root(src) or src.parent
    text = src.read_text(encoding="utf-8") if src.suffix == ".qmd" else ""
    front = frontmatter(text)
    h = hashlib.sha256(f"quarto|{MEASURE_VERSION}|{front}".encode())
    for f in config_files(root, src.parent):
        h.update(f"{f.relative_to(root) if f.is_relative_to(root) else f}".encode())
        h.update(f.read_bytes())
    key = h.hexdigest()
    found = PROBES.get(key) or _cache_read(cache, "preamble", key)
    if found is None:
        found = quarto_probe(src, root, front, args.timeout)
        _cache_write(cache, "preamble", key, found)
    PROBES[key] = found
    engine = args.engine or found["engine"]
    return Context(engine_binary(engine), found["preamble"], found["body_head"], [src.parent.resolve(), root.resolve()], key)


def quarto_probe(src: Path, root: Path, front: str, timeout: int) -> dict:
    """在來源旁 render 一份空白 .qmd，留下 .tex 取前置與正文開頭，PDF 的 Producer 告訴我們用哪個引擎。"""
    quarto = find_tool("quarto")
    if not quarto:
        raise EnvError("找不到 quarto：安裝 Quarto，或改用 --mode latex --preamble …")
    stem = f"tikz-guard-{uuid.uuid4().hex[:8]}"
    probe = src.parent / f"{stem}.qmd"
    before = snapshot(root)
    try:
        probe.write_text(f"---\n{front}\n---\n\n```{{=latex}}\n% TIKZGUARD-BODY\n\\null\n```\n", encoding="utf-8")
        done = run([quarto, "render", probe.name, "--to", "pdf", "-M", "keep-tex:true", "--quiet"], src.parent, timeout)
        tex = src.parent / f"{stem}.tex"
        if done.returncode != 0 or not tex.is_file():
            tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-12:])
            raise EnvError(f"quarto render 失敗，取不到專案的 LaTeX 前置：\n{tail}")
        latex = tex.read_text(encoding="utf-8")
        pdfs = [p for p in snapshot(root) - before if p.name == f"{stem}.pdf"]
        producer = ""
        if pdfs:
            import pymupdf

            with pymupdf.open(pdfs[0]) as doc:
                producer = (doc.metadata or {}).get("producer", "") or ""
    finally:
        cleanup_quarto(root, before, stem)
    m = re.search(r"^\\begin\{document\}", latex, re.MULTILINE)
    if not m:
        raise EnvError("quarto 產生的 .tex 沒有 \\begin{document}")
    head = latex[m.end() :].split("% TIKZGUARD-BODY", 1)[0]
    engine = "lualatex" if "LuaTeX" in producer else "pdflatex" if "pdfTeX" in producer else "xelatex"
    return {"preamble": latex[: m.start()], "body_head": head, "engine": engine}


def latex_context(src: Path, args) -> Context:
    if args.preamble:
        parts = []
        for p in args.preamble:
            if not p.is_file():
                raise EnvError(f"找不到前置檔 {p}")
            body = p.read_text(encoding="utf-8")
            if re.search(r"^\s*\\documentclass", mask_comments(body), re.MULTILINE):
                parts.append(body.split("\\begin{document}", 1)[0])
            else:
                parts.append(f"\\input{{{p.resolve().as_posix()}}}\n% {hashlib.sha256(body.encode()).hexdigest()}")
        preamble = "\n".join(parts)
        if not re.search(r"^\s*\\documentclass", mask_comments(preamble), re.MULTILINE):
            preamble = "\\documentclass{article}\n" + preamble
        inputs = [src.parent.resolve(), *(p.resolve().parent for p in args.preamble)]
    else:
        text = src.read_text(encoding="utf-8")
        masked = mask_comments(text)
        own = re.search(r"^\s*\\documentclass", masked, re.MULTILINE)
        cut = masked.find("\\begin{document}")
        if own and cut > 0:
            preamble = text[own.start() : cut]
        else:
            preamble = "\\documentclass{article}\n" + DEFAULT_PREAMBLE
        inputs = [src.parent.resolve()]
    engine = args.engine or "xelatex"
    key = hashlib.sha256(f"latex|{MEASURE_VERSION}|{engine}|{preamble}".encode()).hexdigest()
    return Context(engine_binary(engine), preamble, "", inputs, key)


# ---------- 編譯 ----------

MARK = r"""
\makeatletter
\@ifpackageloaded{geometry}{\geometry{%(page)s}}{\usepackage[%(page)s]{geometry}}
\makeatother
\newcommand\tikzguardmark[2]{\definecolor{tikzguardmark}{RGB}{1,#1,#2}%%
  \path[draw=tikzguardmark,line width=0.1pt,solid,-,fill=none,draw opacity=1]
  (current bounding box.south west) rectangle (current bounding box.north east);}
"""


def document(ctx: Context, figures: list[tuple[int, Figure]]) -> str:
    """每張圖一頁；記號框的顏色帶著圖在整批裡的序號 k，重編時序號不變。"""
    pages = []
    for k, fig in figures:
        cut = fig.code.rfind("\\end{tikzpicture}")
        code = f"{fig.code[:cut]}\\tikzguardmark{{{k // 256}}}{{{k % 256}}}\n{fig.code[cut:]}"
        pages.append(f"\\clearpage\\thispagestyle{{empty}}\\typeout{{TIKZGUARD-BEGIN {k}}}%\n"
                     f"\\noindent{code}\\par\n\\typeout{{TIKZGUARD-END {k}}}%\n")
    return (f"{ctx.preamble}\n{MARK % {'page': PAGE}}\n\\begin{{document}}\n{ctx.body_head}\n"
            f"\\pagestyle{{empty}}\n{''.join(pages)}\\end{{document}}\n")


def compile_batch(ctx: Context, figures: list[Figure], timeout: int, keep_pdf: Path | None) -> dict[int, dict]:
    """編譯一批圖，回傳「序號 k（從 1 起）→ 量測或錯誤」；某張圖編不過就記下錯誤、拿掉它重編其餘的。"""
    results: dict[int, dict] = {}
    pending = list(range(1, len(figures) + 1))
    env = {**os.environ, "max_print_line": "10000",
           "TEXINPUTS": os.pathsep.join([".", *(str(p) for p in ctx.inputs)]) + os.pathsep}
    with tempfile.TemporaryDirectory(prefix="tikz-guard-") as tmp:
        tmpdir = Path(tmp)
        while pending:
            batch = [(k, figures[k - 1]) for k in pending]
            (tmpdir / "tikz-guard.tex").write_text(document(ctx, batch), encoding="utf-8")
            done = run([ctx.engine, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "./tikz-guard.tex"],
                       tmpdir, timeout, env)
            logfile = tmpdir / "tikz-guard.log"
            log = logfile.read_text(encoding="utf-8", errors="replace") if logfile.is_file() else done.stdout
            pdf = tmpdir / "tikz-guard.pdf"
            if done.returncode == 0 and pdf.is_file():
                if keep_pdf:
                    shutil.copyfile(pdf, keep_pdf)
                measured = measure_pdf(pdf)
                missing = missing_glyphs(log)
                for k in pending:
                    results[k] = measured.get(k) or {"skip": "圖沒有畫出內容（overlay 或空白圖），略過"}
                    if k in missing and "raw" in results[k]:
                        chars = "".join(sorted(missing[k]))[:12]
                        results[k]["warn"] = f"字型缺字（{chars}）：前置的字型沒有這些字，它們不會印出來，字寬也量不準"
                break
            failed, message = failing_figure(log)
            if failed not in pending:
                raise EnvError(f"LaTeX 前置編譯失敗（{Path(ctx.engine).name}）：\n{message}")
            pending.remove(failed)
            results[failed] = {"error": message}
    return results


def missing_glyphs(log: str) -> dict[int, set[str]]:
    """log 的 Missing character 警告，依出現位置歸到整批的第 k 張圖。"""
    found: dict[int, set[str]] = {}
    marks = [(m.start(), int(m.group(1))) for m in re.finditer(r"TIKZGUARD-BEGIN (\d+)", log)]
    for m in re.finditer(r"Missing character: There is no (\S+)", log):
        before = [k for pos, k in marks if pos < m.start()]
        if before:
            found.setdefault(before[-1], set()).add(m.group(1))
    return found


def failing_figure(log: str) -> tuple[int | None, str]:
    """log 裡第一個錯誤落在哪張圖（整批的序號 k），以及錯誤摘要。"""
    err = re.search(r"^(?:\S*:\d+: |! ).*$", log, re.MULTILINE)
    if not err:
        return None, "\n".join(log.strip().splitlines()[-8:])
    lines = log[err.start() :].splitlines()
    context = [re.sub(r"^l\.\d+\s*", "", line).strip() for line in lines[1:8] if re.match(r"^l\.\d+", line)]
    message = (lines[0] + (f"（出錯處：{context[0]}）" if context else "")).strip()
    begins = list(re.finditer(r"TIKZGUARD-BEGIN (\d+)", log[: err.start()]))
    if not begins:
        return None, message
    k = int(begins[-1].group(1))
    if f"TIKZGUARD-END {k}" in log[begins[-1].end() : err.start()]:
        return None, message  # 錯在兩張圖之間，不是圖本身
    return k, re.sub(r"^\S*tikz-guard\.tex:\d+: ", "", message)


# ---------- 量測 ----------


def _bezier(p0, p1, p2, p3, steps=8):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t**2, t**3
        out.append((a * p0.x + b * p1.x + c * p2.x + d * p3.x, a * p0.y + b * p1.y + c * p2.y + d * p3.y))
    return out


def _subpaths(items) -> list[dict]:
    subs: list[dict] = []
    cur = None
    for it in items:
        op = it[0]
        if op in ("re", "qu"):
            q = it[1].quad if op == "re" else it[1]
            pts = [(p.x, p.y) for p in (q.ul, q.ur, q.lr, q.ll, q.ul)]
            subs.append({"pts": pts, "straight": [True] * 4, "closed": True})
            cur = None
            continue
        start = (it[1].x, it[1].y)
        if cur is None or math.dist(cur["pts"][-1], start) > 0.05:
            cur = {"pts": [start], "straight": [], "closed": False}
            subs.append(cur)
        if op == "l":
            cur["pts"].append((it[2].x, it[2].y))
            cur["straight"].append(True)
        elif op == "c":
            bez = _bezier(*it[1:5])
            cur["pts"] += bez
            cur["straight"] += [False] * len(bez)
    for s in subs:
        if not s["closed"]:
            s["closed"] = len(s["pts"]) >= 4 and math.dist(s["pts"][0], s["pts"][-1]) < 0.05
    return subs


def measure_pdf(pdf: Path) -> dict[int, dict]:
    """每頁找出記號框（圖的外框），只留框內的圖形與文字，座標改成以框左上角為原點。"""
    import pymupdf

    out: dict[int, dict] = {}
    flags = pymupdf.TEXTFLAGS_RAWDICT | getattr(pymupdf, "TEXT_ACCURATE_BBOXES", 0)
    with pymupdf.open(pdf) as doc:
        for page in doc:
            drawings = page.get_drawings()
            marks = [(d, _mark_index(d)) for d in drawings]
            for mark, k in marks:
                if k is None:
                    continue
                frame = mark["rect"]
                if frame.width < 0.5 and frame.height < 0.5:
                    continue
                clip = pymupdf.Rect(frame.x0 - 2, frame.y0 - 2, frame.x1 + 2, frame.y1 + 2)
                ox, oy = frame.x0, frame.y0

                def rel(pts, ox=ox, oy=oy):
                    return [[round(x - ox, 2), round(y - oy, 2)] for x, y in pts]

                paths = []
                for d in drawings:
                    r = d["rect"]  # 水平、垂直線的外框寬或高是 0，Rect.intersects 會當成空的，先撐開一點
                    if _mark_index(d) is not None or not pymupdf.Rect(r.x0 - 0.1, r.y0 - 0.1, r.x1 + 0.1, r.y1 + 0.1).intersects(clip):
                        continue
                    stroke = d.get("color") if d["type"] in ("s", "fs") and (d.get("stroke_opacity") or 1) > 0 and (d.get("width") or 0) > 0 else None
                    fill = d.get("fill") if d["type"] in ("f", "fs") and (d.get("fill_opacity") or 1) > 0 else None
                    if stroke is None and fill is None:
                        continue
                    subs = [{**s, "pts": rel(s["pts"])} for s in _subpaths(d["items"])]
                    paths.append({"seq": d.get("seqno", 0), "stroke": stroke and [round(c, 3) for c in stroke],
                                  "fill": fill and [round(c, 3) for c in fill], "lw": round(d.get("width") or 0, 3),
                                  "dash": bool(d.get("dashes") and d["dashes"] not in ("[] 0", "[] 0.0")),
                                  "subs": subs})
                spans = []
                for block in page.get_text("rawdict", flags=flags, clip=clip)["blocks"]:
                    for n, line in enumerate(block.get("lines", [])):
                        for s in line["spans"]:
                            rect = _ink_rect(s["chars"])
                            if rect:
                                x0, y0, x1, y1 = rect
                                spans.append({"text": "".join(c["c"] for c in s["chars"]),
                                              "rect": [round(x0 - ox, 2), round(y0 - oy, 2), round(x1 - ox, 2), round(y1 - oy, 2)],
                                              "line": f"{block['number']}.{n}"})
                out[k] = {"raw": {"size": [round(frame.width, 2), round(frame.height, 2)], "paths": paths, "spans": spans}}
    return out


def _ink_rect(chars) -> tuple | None:
    """一段字的外框。全形標點只有半個字寬有墨跡，xeCJK 的標點擠壓會讓空的那半邊伸出節點，
    所以行首、行尾的全形標點只算有墨跡的半邊。"""
    chars = [c for c in chars if c["c"].strip()]
    if not chars:
        return None
    x0 = min(c["bbox"][0] for c in chars)
    x1 = max(c["bbox"][2] for c in chars)
    first, last = chars[0], chars[-1]
    if CJK_PUNCT.match(first["c"]):
        x0 = max(x0, (first["bbox"][0] + first["bbox"][2]) / 2)
    if CJK_PUNCT.match(last["c"]):
        x1 = min(x1, (last["bbox"][0] + last["bbox"][2]) / 2)
    return x0, min(c["bbox"][1] for c in chars), x1, max(c["bbox"][3] for c in chars)


CJK_PUNCT = re.compile("[\u3000-\u303f\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65\u2018-\u201f]")


def _mark_index(d) -> int | None:
    c = d.get("color")
    if d["type"] != "s" or not c or abs((d.get("width") or 1) - 0.0996) > 0.02 or round(c[0] * 255) != 1:
        return None
    return round(c[1] * 255) * 256 + round(c[2] * 255)


# ---------- 快取 ----------


def _cache_path(cache: Path, kind: str, key: str) -> Path:
    return cache / kind / key[:2] / f"{key}.json"


def _cache_read(cache: Path | None, kind: str, key: str):
    if cache is None:
        return None
    try:
        return json.loads(_cache_path(cache, kind, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cache_write(cache: Path | None, kind: str, key: str, value) -> None:
    if cache is None:
        return
    path = _cache_path(cache, kind, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def figure_key(ctx: Context, fig: Figure) -> str:
    """前置、引擎與圖原始碼都沒變，量測結果就不會變；來源目錄影響圖裡 \\input 與圖檔的相對路徑。"""
    return hashlib.sha256(f"{ctx.key}|{ctx.engine}|{ctx.body_head}|{fig.file.parent.resolve()}|{fig.code}".encode()).hexdigest()


# ---------- 分類 ----------


@dataclass
class Shape:
    poly: object          # shapely Polygon（中心線）
    shape: object         # 判斷用：圓角矩形取外框，其餘取多邊形
    lw: float
    seq: int
    texts: list = field(default_factory=list)
    members: list = field(default_factory=list)
    container: bool = False

    def name(self) -> str:
        if self.container:
            inner = [m.name() for m in self.members if m.texts][:2]
            return f"外框（含 {'、'.join(inner) or '節點'}{'等' if len(self.members) > len(inner) else ''}）"
        if not self.texts:
            x0, y0, _, _ = self.poly.bounds
            return f"無字節點（左上 {x0:.0f},{y0:.0f}pt）"
        text = _join(self.texts)
        return f"「{text[:18]}{'…' if len(text) > 18 else ''}」"


@dataclass
class Label:
    rect: tuple
    text: str
    seq: int
    boxed: bool


@dataclass
class Edge:
    pts: list
    straight: list
    seq: int
    dashed: bool = False
    ends: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    labels: list = field(default_factory=list)

    @property
    def guide(self) -> bool:
        """沒有箭頭、最多一端接到節點的虛線：生命線、時間軸，不是節點之間的連線。"""
        return self.dashed and not self.tips and sum(e is not None for e in self.ends) <= 1

    def name(self) -> str:
        a, b = (e.name() if e else "（線端）" for e in self.ends)
        if self.tips and all(math.dist(self.pts[0], t.centroid.coords[0]) < math.dist(self.pts[-1], t.centroid.coords[0])
                             for t in self.tips):
            a, b = b, a
        tag = f"（標籤「{self.labels[0].text}」）" if self.labels else ""
        return f"連線 {a}→{b}{tag}"


@dataclass
class Scene:
    size: tuple
    nodes: list
    containers: list
    labels: list
    edges: list
    tips: list
    texts: list


def classify(raw: dict) -> Scene:
    from shapely import make_valid
    from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
    from shapely.ops import unary_union

    def white(c):
        return c is not None and min(c) >= 0.97

    closed, opens = [], []
    for p in raw["paths"]:
        for s in p["subs"]:
            pts = [tuple(x) for x in s["pts"]]
            if len(pts) < 2:
                continue
            if s["closed"] or (p["fill"] is not None and p["stroke"] is None and len(pts) >= 3):
                if len(pts) < 3:
                    continue
                poly = Polygon(pts)
                if not poly.is_valid:
                    poly = make_valid(poly)
                    poly = max(getattr(poly, "geoms", [poly]), key=lambda g: g.area)
                    if poly.geom_type != "Polygon":
                        continue
                if poly.area < 0.5:
                    continue
                closed.append((p, poly))
            elif p["stroke"] is not None and not white(p["stroke"]):
                opens.append((p, pts, s["straight"]))

    # 開放的小筆畫接在別條線的端點上（-> 的 to 箭頭）：是箭頭，不是線
    def small(pts) -> bool:
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys)) <= 8

    long_ends = [pt for _, pts, _ in opens if not small(pts) for pt in (pts[0], pts[-1])]
    tips, kept = [], []
    for item in opens:
        if small(item[1]):
            hull = MultiPoint(item[1]).convex_hull.buffer(0.3)
            if any(hull.buffer(2).contains(Point(pt)) for pt in long_ends):
                tips.append(hull)
                continue
        kept.append(item)
    edges: list[Edge] = []
    seen = set()
    for p, pts, straight in kept:
        key = tuple((round(x, 1), round(y, 1)) for x, y in pts)
        if key in seen or key[::-1] in seen:
            continue  # double、preaction 之類同一條線畫兩次
        seen.add(key)
        edges.append(Edge(pts, straight, p["seq"], dashed=p["dash"]))

    texts = [{**t, "box": box(*t["rect"])} for t in raw["spans"]]
    nodes, boxes = [], []
    for p, poly in closed:
        x0, y0, x1, y1 = poly.bounds
        if max(x1 - x0, y1 - y0) <= TIP_MAX:
            # 小圖形：字大半落在它裡面才是帶字的小節點（編號圓圈）；否則是箭頭或記號，
            # 標籤壓在上面一樣要擋（線太短時只剩箭頭，也要看得到）
            own = any(poly.intersection(t["box"]).area > 0.5 * t["box"].area for t in texts)
            if not own:
                tips.append(poly)
                continue
        if p["stroke"] is not None:
            shape = box(x0, y0, x1, y1) if poly.area >= RECT_LIKE * (x1 - x0) * (y1 - y0) else poly
            nodes.append(Shape(poly, shape, p["lw"], p["seq"]))
        else:
            boxes.append((p, poly))  # 只有填色：包住節點就是背景容器，有字是邊標籤，其餘忽略

    # 容器：完全包住其他節點的框
    for a in nodes:
        grown = a.poly.buffer(1)
        a.members = [b for b in nodes if b is not a and b.poly.area < a.poly.area and grown.contains(b.poly)]
        a.container = bool(a.members)
    labels_boxes = []
    containers = [n for n in nodes if n.container]
    for p, poly in boxes:
        grown = poly.buffer(1)
        members = [b for b in nodes if grown.contains(b.poly)]
        if members:
            x0, y0, x1, y1 = poly.bounds
            c = Shape(poly, box(x0, y0, x1, y1), 0.0, p["seq"], members=members, container=True)
            containers.append(c)
        elif any(poly.contains(Point(t["box"].centroid)) for t in texts):
            labels_boxes.append((p, poly))
    nodes = [n for n in nodes if not n.container]

    # 文字歸屬：最小的包住字中心的節點或標籤框；都不在就是裸字標籤
    labels: list[Label] = [Label(poly.bounds, "", p["seq"], True) for p, poly in labels_boxes]
    boxed: list[list] = [[] for _ in labels_boxes]
    # 以「一行字」為單位歸屬（同一行裡隔太開的再拆開），裸字標籤的各個字詞才不會被拆到兩旁的節點
    lines: dict[str, list] = {}
    for t in texts:
        lines.setdefault(t["line"], []).append(t)
    for group in lines.values():
        for run in _split_runs(group):
            rect = (min(t["rect"][0] for t in run), min(t["rect"][1] for t in run),
                    max(t["rect"][2] for t in run), max(t["rect"][3] for t in run))
            c = Point((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
            hosts = [(n.poly.area, "node", n) for n in nodes if n.poly.contains(c)]
            hosts += [(poly.area, "label", i) for i, (_, poly) in enumerate(labels_boxes) if poly.contains(c)]
            if not hosts:
                labels.append(Label(rect, _join(run), 10**9, False))
                continue
            _, kind, host = min(hosts, key=lambda h: h[0])
            if kind == "node":
                host.texts += run
            else:
                boxed[host] += run
    for lab, group in zip(labels, boxed):
        lab.text = _join(group)
    for c in containers:
        c.texts = [t for t in texts if c.poly.contains(Point(t["box"].centroid))]
    for lab in labels:
        lab.text = lab.text or "（無字）"

    # 線的兩端接到哪個節點：線端加上接在那裡的箭頭，離節點外形 END_TOL 以內就算接到
    for e in edges:
        for pt in (e.pts[0], e.pts[-1]):
            attached = [t for t in tips if t.buffer(2).contains(Point(pt))]
            e.tips += attached
            probe = unary_union([Point(pt), *attached])
            near = [(n.poly.distance(probe), n) for n in nodes]
            near = [x for x in near if x[0] <= END_TOL]
            e.ends.append(min(near, key=lambda x: x[0])[1] if near else None)
    for lab in labels:
        rect = box(*lab.rect)
        near = [(LineString(e.pts).distance(rect), e) for e in edges]
        near = [x for x in near if x[0] <= 3]
        if near:
            min(near, key=lambda x: x[0])[1].labels.append(lab)
    return Scene(tuple(raw["size"]), nodes, containers, labels, edges, tips, texts)


def _join(spans: list) -> str:
    """依閱讀順序串起一組字：先按 PyMuPDF 的行（取行的最高點）再按 x；字距明顯時補空白。"""
    tops: dict[str, float] = {}
    for t in spans:
        tops[t["line"]] = min(tops.get(t["line"], 1e9), t["rect"][1])
    out, prev = "", None
    for t in sorted(spans, key=lambda t: (round(tops[t["line"]], 1), t["line"], t["rect"][0])):
        if prev is not None and (prev["line"] != t["line"] or t["rect"][0] - prev["rect"][2] > 1.5):
            out += " "
        out += t["text"]
        prev = t
    return re.sub(r"\s+", " ", out).strip()


def _split_runs(spans: list) -> list[list]:
    """同一行的裸字，水平距離超過一個字寬就拆成不同標籤。"""
    spans = sorted(spans, key=lambda t: t["rect"][0])
    runs = [[spans[0]]]
    for t in spans[1:]:
        prev = runs[-1][-1]
        height = prev["rect"][3] - prev["rect"][1]
        if t["rect"][0] - prev["rect"][2] > max(height, 4):
            runs.append([t])
        else:
            runs[-1].append(t)
    return runs


# ---------- 守門 ----------


@dataclass
class Issue:
    rule: str
    message: str
    nodes: list = field(default_factory=list)


def lint(scene: Scene, min_gap: float, max_width: float | None) -> list[Issue]:
    from shapely.geometry import LineString, box

    issues: list[Issue] = []

    def add(rule, message, *items):
        names = [i.name() for i in items]
        if not any(x.rule == rule and x.message == message for x in issues):
            issues.append(Issue(rule, message, names))

    nodes, containers = scene.nodes, scene.containers
    # 1. 節點互壓、太近；外框切過不屬於它的節點、兩個外框交疊
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            overlap = a.shape.intersection(b.shape).area
            if overlap > 1.0:
                add("node-overlap", f"節點 {a.name()} 和 {b.name()} 重疊：用相對定位拉開（加大 node distance，或改 below=of 的對象）", a, b)
                continue
            gap = a.shape.distance(b.shape) - (a.lw + b.lw) / 2
            if gap < min_gap:
                add("node-overlap", f"節點 {a.name()} 和 {b.name()} 間距只有 {max(gap, 0):.1f}pt（下限 {min_gap}）：加大 node distance", a, b)
    for c in containers:
        for n in nodes:
            if n not in c.members and c.shape.intersection(n.shape).area > 1.0:
                add("node-overlap", f"{c.name()} 切過節點 {n.name()}：把它放進 fit 清單，或移到外框外", c, n)
    for i, a in enumerate(containers):
        for b in containers[i + 1 :]:
            inter = a.shape.intersection(b.shape).area
            if inter > 1.0 and inter < min(a.shape.area, b.shape.area) - 1.0:
                add("node-overlap", f"{a.name()} 和 {b.name()} 交疊：拉開兩組節點，或讓一個外框完整包住另一個", a, b)

    # 2. 連線穿過兩端以外的節點
    for e in scene.edges:
        if e.guide:
            continue  # 生命線、時間軸之類的導引虛線：被 note、activation 蓋住是慣例
        line = LineString(e.pts)
        for n in nodes:
            if n in e.ends:
                continue
            inner = n.shape.buffer(-SHRINK)
            if not inner.is_empty and line.intersects(inner):
                add("edge-through-node", f"{e.name()} 穿過節點 {n.name()}：用 -| 或 |- 繞開，或經過轉折點 ([xshift=…]…) 走節點外側", n)

    # 3. 標籤壓到節點、其他標籤、箭頭
    for i, lab in enumerate(scene.labels):
        x0, y0, x1, y1 = lab.rect
        rect = box(x0 + LABEL_TOL, y0 + LABEL_TOL, x1 - LABEL_TOL, y1 - LABEL_TOL)
        if rect.is_empty:
            continue
        for n in nodes:
            if rect.intersection(n.shape).area > LABEL_AREA:
                add("label-on-node", f"標籤「{lab.text}」壓到節點 {n.name()}：改 pos 或 above／below／left／right，或拉開節點", n)
        for other in scene.labels[i + 1 :]:
            if rect.intersection(box(*other.rect)).area > 0.5:
                add("label-on-label", f"標籤「{lab.text}」和「{other.text}」重疊：錯開 pos，或放到線的另一側")
        for tip in scene.tips:
            if rect.intersection(tip).area > max(1.0, TIP_COVER * tip.area):
                owner = next((e for e in scene.edges if tip in e.tips), None)
                whose = owner.name() if owner else "連線"
                add("label-on-arrow", f"標籤「{lab.text}」蓋住{whose}的箭頭：pos 往線段中間移，或拉開兩端節點")

    # 4. 字超出節點外形
    for n in nodes:
        limit = n.shape.buffer(-n.lw / 2 + TEXT_TOL)
        for t in n.texts:
            if not limit.contains(t["box"]):
                add("text-overflow", f"「{t['text'].strip()}」超出節點 {n.name()} 的外形：縮短字句、用 \\\\ 換行或加 text width；"
                                     "菱形加大 inner sep 或 aspect", n)
                break

    # 5. 兩條連線有一段疊在一起
    edges = scene.edges
    for i, a in enumerate(edges):
        for b in edges[i + 1 :]:
            if a.seq == b.seq:
                continue
            if any(math.dist(p, q) < SAME_PORT for p in (a.pts[0], a.pts[-1]) for q in (b.pts[0], b.pts[-1])):
                continue  # 同一接點分岔或匯流，共用線段是刻意的
            length = max((_overlap(p, q, r, s) for p, q in _straight(a) for r, s in _straight(b)), default=0)
            if length > OVERLAP_MIN:
                add("edge-overlap", f"{a.name()} 和{b.name()}有 {length:.0f}pt 疊在一起：錯開接點（如 .north east）或轉折位置")

    # 6. 圖寬
    if max_width and scene.size[0] > max_width + 0.5:
        add("figure-width", f"圖寬 {scene.size[0] / 72 * 2.54:.1f}cm 超過上限 {max_width}："
                            "縮小 node distance、文字換行，或改成直向排列")
    return issues


def _straight(e: Edge):
    for k, ok in enumerate(e.straight):
        p, q = e.pts[k], e.pts[k + 1]
        if ok and math.dist(p, q) > OVERLAP_MIN:
            yield p, q


def _overlap(p, q, r, s) -> float:
    """兩條線段共線時的重疊長度，不共線回傳 0。"""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    ex, ey = s[0] - r[0], s[1] - r[1]
    if abs(ux * ey - uy * ex) > math.sin(math.radians(1)) * math.hypot(ex, ey):
        return 0.0
    if any(abs((pt[0] - p[0]) * uy - (pt[1] - p[1]) * ux) > COLLINEAR for pt in (r, s)):
        return 0.0
    t1, t2 = sorted((pt[0] - p[0]) * ux + (pt[1] - p[1]) * uy for pt in (r, s))
    return max(0.0, min(length, t2) - max(0.0, t1))


# ---------- 主流程 ----------


class Length(float):
    """命令列的長度（pt、bp、mm、cm、in）；值是 PDF 點，str() 保留使用者寫的樣子。"""

    def __new__(cls, text: str):
        m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(pt|bp|mm|cm|in)?\s*", text)
        if not m:
            raise argparse.ArgumentTypeError(f"看不懂長度 {text!r}（例：16cm、2pt）")
        unit = m.group(2) or "pt"
        value = float(m.group(1)) * {"pt": 72 / 72.27, "bp": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72}[unit]
        obj = super().__new__(cls, value)
        obj.text = f"{m.group(1)}{unit}"
        return obj

    def __str__(self) -> str:
        return self.text


def default_cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "tikz-guard"


def check(args) -> dict:
    sources = find_sources(args.paths)
    if (args.keep_pdf or args.from_pdf) and len(sources) != 1:
        raise EnvError("--keep-pdf 與 --from-pdf 只能配一個來源檔")
    cache = None if args.no_cache or args.keep_pdf or args.from_pdf else (args.cache_dir or default_cache())
    report = {"ok": True, "files": 0, "figures": 0, "compiled": 0, "issues": [], "warnings": []}
    figures: list[Figure] = []
    results: dict[int, dict] = {}       # id(fig) → 量測、錯誤或略過
    groups: dict[str, tuple[Context, list[Figure]]] = {}
    for src in sources:
        found = scan_file(src)
        if not found:
            continue
        report["files"] += 1
        figures += found
        if args.from_pdf:
            if not args.from_pdf.is_file():
                raise EnvError(f"找不到 {args.from_pdf}")
            measured = measure_pdf(args.from_pdf)
            for k, fig in enumerate(found, 1):
                results[id(fig)] = measured.get(k) or {"skip": "PDF 裡沒有這張圖"}
            continue
        mode = args.mode if args.mode != "auto" else ("quarto" if project_root(src) else "latex")
        ctx = quarto_context(src, args, cache) if mode == "quarto" else latex_context(src, args)
        for fig in found:
            hit = _cache_read(cache, "figure", figure_key(ctx, fig))
            if hit is not None:
                results[id(fig)] = hit
                continue
            group = groups.setdefault(ctx.key, (ctx, []))
            group[0].inputs = list(dict.fromkeys(group[0].inputs + ctx.inputs))
            group[1].append(fig)
    # 共用同一份前置的圖一起編：一次 TeX 啟動處理整批
    for ctx, todo in groups.values():
        batch = compile_batch(ctx, todo, args.timeout, args.keep_pdf)
        report["compiled"] += len(todo)
        for local, fig in enumerate(todo, 1):
            results[id(fig)] = batch[local]
            _cache_write(cache, "figure", figure_key(ctx, fig), batch[local])
    report["figures"] = len(figures)
    for fig in figures:
        result = results[id(fig)]
        for issue in figure_issues(fig, result, args):
            report["issues"].append({"file": str(fig.file), "line": fig.line, "figure": fig.index, "label": fig.label,
                                     "rule": issue.rule, "message": issue.message, "nodes": issue.nodes})
        if "warn" in result or "skip" in result:
            report["warnings"].append(f"{fig.where}：{result.get('warn') or result.get('skip')}")
    report["ok"] = not report["issues"]
    return report


def figure_issues(fig: Figure, result: dict, args) -> list[Issue]:
    if "error" in result:
        return [] if "compile" in fig.allow else [Issue("compile", f"這張圖編譯失敗：{result['error']}")]
    if "raw" not in result:
        return []
    issues = lint(classify(result["raw"]), args.min_gap, args.max_width)
    return [i for i in issues if i.rule not in fig.allow]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把 .qmd／.tex 裡的每張 TikZ 圖單獨編譯並量測，節點、連線、標籤有任何壓疊就列出並以非零結束碼擋下。",
        epilog="結束碼：0 通過｜1 圖有問題（含圖本身編譯失敗）｜2 執行環境問題。規則與修法見 references/rules.md。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", type=Path, nargs="+", metavar="FILE_OR_DIR",
                    help=".qmd（從 {=latex} raw block 抽圖）或 .tex；目錄會遞迴找含 tikzpicture 的檔案，略過 . 與 _ 開頭的目錄")
    ap.add_argument("--mode", choices=("auto", "quarto", "latex"), default="auto",
                    help="auto（預設）：上層有 _quarto.yml 用 quarto，否則 latex")
    ap.add_argument("--preamble", type=Path, action="append", default=[], metavar="FILE",
                    help="latex 模式的前置檔，可重複；也可以是一份完整文件（取 \\begin{document} 之前）")
    ap.add_argument("--engine", help="TeX 引擎名稱或路徑（預設：quarto 模式沿用專案設定，latex 模式 xelatex）")
    ap.add_argument("--min-gap", type=Length, default=Length("2pt"), metavar="LEN",
                    help="節點之間的最小間距（預設 2pt）")
    ap.add_argument("--max-width", type=Length, metavar="LEN", help="圖寬上限，例如 16cm（預設不檢查）")
    ap.add_argument("--json", action="store_true", help="以單一 JSON 物件輸出（ok、issues、warnings 與計數）")
    ap.add_argument("--limit", type=int, default=30, metavar="N", help="最多列出幾個問題（預設 30；0 表示全部）")
    ap.add_argument("--timeout", type=int, default=300, metavar="SEC", help="每次 quarto／TeX 執行的時限（預設 300 秒）")
    ap.add_argument("--cache-dir", type=Path, metavar="DIR", help=f"量測快取目錄（預設 {default_cache()}）")
    ap.add_argument("--no-cache", action="store_true", help="不讀也不寫快取")
    ap.add_argument("--keep-pdf", type=Path, metavar="PDF", help="另存編譯出的 PDF（除錯用；只能配一個來源檔，不用快取）")
    ap.add_argument("--from-pdf", type=Path, metavar="PDF", help="不編譯，直接量測 --keep-pdf 存下的 PDF（只能配一個來源檔）")
    args = ap.parse_args(argv)
    if args.limit < 0:
        ap.error("--limit 不能是負數")

    try:
        report = check(args)
    except EnvError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        print(f"✗ {e}", file=sys.stderr)
        return 2

    issues = report["issues"]
    shown = issues if args.limit == 0 else issues[: args.limit]
    report["omitted"] = len(issues) - len(shown)
    summary = (f"{report['figures']} 張圖（{report['files']} 個檔案，編譯 {report['compiled']} 張、其餘取自快取）")
    if args.json:
        print(json.dumps({**report, "issues": shown}, ensure_ascii=False))
    else:
        for w in report["warnings"]:
            print(f"! {w}", file=sys.stderr)
        for i in shown:
            tag = f" {i['label']}" if i["label"] else ""
            print(f"✗ {i['file']}:{i['line']}{tag} [{i['rule']}] {i['message']}", file=sys.stderr)
        if report["omitted"]:
            print(f"… 另有 {report['omitted']} 個問題未列出（--limit 0 列出全部）", file=sys.stderr)
        if issues:
            bad = len({(i["file"], i["line"]) for i in issues})
            print(f"✗ {summary}：{bad} 張有問題，共 {len(issues)} 個", file=sys.stderr)
        elif report["figures"] == 0:
            print("沒有找到 tikzpicture", file=sys.stderr)
        else:
            print(f"✓ {summary}：沒有壓疊")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
