#!/usr/bin/env bash
# guard-tikz-figures 測試：--help、fixture 逐張比對「回報的規則集合 == % expect: 註記」（乾淨的圖通過、每條規則各有一張被擋下）、
# .qmd 抽圖（raw block、行號、\label 與 #fig- 標籤、略過註解與程式碼區塊）、結束碼、hook 的放行／回饋／警告。
# 有 TeX（xelatex）時重新編譯 fixture，並確認夾帶的 fixture PDF 沒有過期，另驗快取、目錄掃描；有 Quarto 時另驗 quarto 模式不留暫存檔。
# 沒有 TeX 的機器（CI）改量測夾帶的 fixture PDF（--from-pdf），規則判斷照樣全部驗到。
# fixture 改了就重產 PDF：uv run scripts/check.py assets/fixtures/<名稱> --mode latex --no-cache --keep-pdf assets/fixtures/<名稱去副檔名>.pdf
set -euo pipefail
cd "$(dirname "$0")/.."
CHECK=scripts/check.py
HOOK=scripts/hook.py
F=assets/fixtures
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

uvx ruff check scripts
uv run -q "$CHECK" --help > /dev/null
uv run -q "$HOOK" --help > /dev/null

# 每個 fixture：檔名、額外參數
fixtures=("clean.tex" "rules.tex --max-width 10cm" "doc.qmd")

# 比對 JSON 結果與 fixture 裡的 % expect: 註記（寫在 \begin{tikzpicture} 上方或圖裡）；
# $3=pdf 時是量測夾帶的 PDF：編不過的圖不在 PDF 裡，改成預期一則略過警告
expect() {  # $1 fixture  $2 JSON  $3 fresh|pdf
  python3 - "$F/$1" "$2" "$3" <<'PY'
import json, re, sys
src, result, how = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")), sys.argv[3]
lines = open(src, encoding="utf-8").read().split("\n")
want, pending = {}, None
for n, line in enumerate(lines, 1):
    m = re.search(r"%\s*expect:\s*(.+)$", line)
    if m:
        pending = set() if m.group(1).strip() == "none" else {r.strip() for r in m.group(1).split(",")}
    if re.match(r"\s*\\begin\{tikzpicture\}", line):
        assert pending is not None, f"{src}:{n} 沒有 % expect: 註記"
        want[n], pending = pending, None
got = {n: set() for n in want}
for i in result["issues"]:
    got.setdefault(i["line"], set()).add(i["rule"])
skipped = {int(re.search(r":(\d+)", w).group(1)) for w in result["warnings"]}
if how == "pdf":
    for n in [n for n, rules in want.items() if "compile" in rules]:
        want[n] = set()
        assert n in skipped, f"{src}:{n} 編不過的圖應以警告略過：{result['warnings']}"
bad = {n: (want[n], got.get(n)) for n in want if want[n] != got.get(n)}
assert not bad and set(got) == set(want), f"{src} 規則不符（行：預期, 實得）：{bad or set(got) ^ set(want)}"
assert result["figures"] == len(want), (result["figures"], len(want))
print(f"{src}（{how}）：{len(want)} 張圖符合預期")
PY
}

run_json() {  # $1 輸出檔，其餘是 check.py 參數；回傳 check.py 的結束碼
  local out=$1
  shift
  set +e
  uv run -q "$CHECK" "$@" --json --limit 0 > "$out"
  local rc=$?
  set -e
  return $rc
}

# 1. 有沒有 TeX
if uv run -q "$CHECK" "$F/clean.tex" --mode latex --no-cache > /dev/null 2> "$tmp/probe.err"; then
  have_tex=1
elif grep -q "找不到 xelatex" "$tmp/probe.err"; then
  have_tex=0
  echo "這台機器沒有 xelatex：改量測夾帶的 fixture PDF"
else
  cat "$tmp/probe.err" >&2
  exit 1
fi

# 2. fixture：有 TeX 時重新編譯，再確認夾帶的 PDF 量出一樣的結果；沒有 TeX 時只量夾帶的 PDF
for item in "${fixtures[@]}"; do
  read -r name extra <<< "$item"
  stem=${name%.*}
  # shellcheck disable=SC2086
  if [ "$have_tex" -eq 1 ]; then
    run_json "$tmp/$stem.json" "$F/$name" --mode latex --no-cache --keep-pdf "$tmp/$stem.pdf" $extra || true
    expect "$name" "$tmp/$stem.json" fresh
  fi
  run_json "$tmp/$stem-pdf.json" "$F/$name" --from-pdf "$F/$stem.pdf" $extra || true
  expect "$name" "$tmp/$stem-pdf.json" pdf \
    || { echo "FAIL: $F/$stem.pdf 過期，重產：uv run $CHECK $F/$name --mode latex --no-cache --keep-pdf $F/$stem.pdf" >&2; exit 1; }
done

# 3. 結束碼、標籤與 JSON 欄位
python3 - "$tmp/doc-pdf.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
assert not r["ok"] and r["files"] == 1 and r["figures"] == 2, r
(i,) = r["issues"]
assert (i["line"], i["label"], i["figure"], i["rule"]) == (13, "fig:through", 1, "edge-through-node"), i
assert i["nodes"] == ["「B」"] and "穿過節點" in i["message"], i
PY
set +e
uv run -q "$CHECK" "$F/clean.tex" --from-pdf "$F/clean.pdf" > /dev/null; rc_ok=$?
uv run -q "$CHECK" "$F/rules.tex" --from-pdf "$F/rules.pdf" --limit 2 2> "$tmp/limit.err"; rc_bad=$?
uv run -q "$CHECK" "$F/nope.tex" 2> /dev/null; rc_missing=$?
uv run -q "$CHECK" "$F/clean.tex" --mode latex --engine /nonexistent/xelatex --no-cache 2> /dev/null; rc_engine=$?
uv run -q "$CHECK" "$F" --keep-pdf "$tmp/x.pdf" 2> /dev/null; rc_many=$?
set -e
[ "$rc_ok" -eq 0 ] || { echo "FAIL: 乾淨的圖應以 0 結束，實得 $rc_ok" >&2; exit 1; }
[ "$rc_bad" -eq 1 ] || { echo "FAIL: 有問題的圖應以 1 結束，實得 $rc_bad" >&2; exit 1; }
for rc in "$rc_missing" "$rc_engine" "$rc_many"; do
  [ "$rc" -eq 2 ] || { echo "FAIL: 執行環境問題應以 2 結束，實得 $rc" >&2; exit 1; }
done
[ "$(grep -c '^✗ .*\[' "$tmp/limit.err")" -eq 2 ] && grep -q "另有 .* 個問題未列出" "$tmp/limit.err" \
  || { echo "FAIL: --limit 2 應只列 2 個問題並提示其餘" >&2; cat "$tmp/limit.err" >&2; exit 1; }
mkdir "$tmp/empty"
uv run -q "$CHECK" "$tmp/empty" 2> "$tmp/empty.err" || { echo "FAIL: 沒有圖的目錄應以 0 結束" >&2; exit 1; }
grep -q "沒有找到 tikzpicture" "$tmp/empty.err" || { echo "FAIL: 沒有圖時要提示" >&2; exit 1; }
echo "exit codes OK"

# 4. hook：不相干的檔放行、壞輸入與環境問題只警告（結束碼 0 + systemMessage）
hook() {  # $1 檔案路徑；其餘是 hook.py 參數；印出結束碼
  set +e
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$PWD" \
    | uv run -q "$HOOK" "${@:2}" > "$tmp/hook.out" 2> "$tmp/hook.err"
  echo $?
  set -e
}
[ "$(hook "$PWD/scripts/check.py")" -eq 0 ] && [ ! -s "$tmp/hook.out" ] || { echo "FAIL: 非 .qmd/.tex 應直接放行" >&2; exit 1; }
printf -- '---\ntitle: x\n---\n\n沒有圖\n' > "$tmp/plain.qmd"
[ "$(hook "$tmp/plain.qmd")" -eq 0 ] && [ ! -s "$tmp/hook.out" ] || { echo "FAIL: 不含 tikzpicture 應直接放行" >&2; exit 1; }
set +e
echo "not json" | uv run -q "$HOOK" > "$tmp/hook.out"; rc=$?
set -e
[ "$rc" -eq 0 ] && grep -q systemMessage "$tmp/hook.out" || { echo "FAIL: 壞輸入應以 systemMessage 警告並放行" >&2; exit 1; }
[ "$(hook "$PWD/$F/clean.tex" -- --mode latex --engine /nonexistent/xelatex --no-cache)" -eq 0 ] \
  && python3 -c 'import json,sys; assert "找不到" in json.load(open(sys.argv[1]))["systemMessage"]' "$tmp/hook.out" \
  || { echo "FAIL: 找不到 TeX 應以 systemMessage 警告並放行" >&2; cat "$tmp/hook.out" "$tmp/hook.err" >&2; exit 1; }
echo "hook pass-through OK"

if [ "$have_tex" -eq 0 ]; then
  echo "guard-tikz-figures tests passed（無 TeX：略過編譯、快取、目錄掃描與 quarto 模式）"
  exit 0
fi

# 5. hook 擋下：結束碼 2，問題與修法文件寫在 stderr
[ "$(hook "$PWD/$F/rules.tex" --limit 3 -- --mode latex --no-cache)" -eq 2 ] \
  && grep -q "\[node-overlap\]" "$tmp/hook.err" && grep -q "references/rules.md" "$tmp/hook.err" \
  || { echo "FAIL: 有壓疊時 hook 應以 2 結束並在 stderr 列出問題" >&2; cat "$tmp/hook.err" >&2; exit 1; }
echo "hook block OK"

# 6. 快取：第二次全部取自快取；改一張圖只重編那一張
cp "$F/rules.tex" "$F/styles.tex" "$tmp/"
run_json "$tmp/c1.json" "$tmp/rules.tex" --mode latex --cache-dir "$tmp/cache" || true
run_json "$tmp/c2.json" "$tmp/rules.tex" --mode latex --cache-dir "$tmp/cache" || true
sed -i.bak 's/right=-3mm of a\] (b) {Beta}/right=8mm of a] (b) {Beta}/' "$tmp/rules.tex"
run_json "$tmp/c3.json" "$tmp/rules.tex" --mode latex --cache-dir "$tmp/cache" || true
python3 - "$tmp/c1.json" "$tmp/c2.json" "$tmp/c3.json" <<'PY'
import json, sys
c1, c2, c3 = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:])
assert c1["compiled"] == c1["figures"] and c2["compiled"] == 0, (c1["compiled"], c2["compiled"])
assert c1["issues"] == c2["issues"]
assert c3["compiled"] == 1 and len(c3["issues"]) == len(c1["issues"]) - 1, (c3["compiled"], len(c3["issues"]))
print("cache OK")
PY

# 7. 目錄：遞迴找含 tikzpicture 的 .qmd／.tex，略過 . 與 _ 開頭的目錄、node_modules、*_files
repo="$tmp/repo"
mkdir -p "$repo/docs/sub" "$repo/_output" "$repo/.hidden" "$repo/node_modules" "$repo/docs/a_files"
cp "$F/clean.tex" "$F/styles.tex" "$repo/docs/"
cp "$F/doc.qmd" "$repo/docs/sub/_fragment.qmd"
for d in _output .hidden node_modules docs/a_files; do cp "$F/rules.tex" "$F/styles.tex" "$repo/$d/"; done
printf '%% 只在註解提到 tikzpicture 的前置檔不算圖\n\\usepackage{tikz}\n' > "$repo/docs/preamble.tex"
run_json "$tmp/dir.json" "$repo" --mode latex --no-cache || true
python3 - "$tmp/dir.json" "$repo" <<'PY'
import json, sys
from pathlib import Path
r = json.load(open(sys.argv[1], encoding="utf-8"))
files = {str(Path(i["file"]).relative_to(sys.argv[2])) for i in r["issues"]}
assert r["files"] == 2 and r["figures"] == 4, (r["files"], r["figures"])
assert files == {"docs/sub/_fragment.qmd"}, files
print("directory scan OK")
PY

# 8. quarto 模式：專案設定提供前置；跑完專案裡不能多出任何檔案
if command -v quarto > /dev/null; then
  proj="$tmp/proj"
  mkdir -p "$proj/docs"
  cat > "$proj/_quarto.yml" <<'EOF'
project:
  type: default
  output-dir: _site
format:
  pdf:
    include-in-header:
      - text: |
          \usepackage{tikz}
          \usetikzlibrary{arrows.meta,positioning}
EOF
  cp "$F/doc.qmd" "$proj/docs/"
  (cd "$proj" && find . | sort) > "$tmp/before.txt"
  run_json "$tmp/quarto.json" "$proj/docs/doc.qmd" --no-cache || true
  (cd "$proj" && find . | sort) > "$tmp/after.txt"
  diff "$tmp/before.txt" "$tmp/after.txt" || { echo "FAIL: quarto 模式留下了暫存檔" >&2; exit 1; }
  cp "$tmp/quarto.json" "$tmp/q.json"
  python3 - "$tmp/q.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
assert r["figures"] == 2 and [(i["line"], i["rule"]) for i in r["issues"]] == [(13, "edge-through-node")], r
print("quarto mode OK")
PY
else
  echo "略過 quarto 模式：這台機器沒有 quarto"
fi

echo "guard-tikz-figures tests passed"
