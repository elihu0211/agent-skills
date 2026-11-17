#!/usr/bin/env bash
# build-tech-deck 測試：範本引擎的 pytest（建置、零折行、白話命名、字數上限表、schema、命令列），
# 加上 scripts/lint.py 入口的正反向煙霧測試。
set -euo pipefail
cd "$(dirname "$0")/.."
TEMPLATE=assets/deck-template
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# 靜態檢查：lint、格式與型別，引擎程式碼不退化
(cd "$TEMPLATE" && uvx ruff check . && uvx ruff format --check . && uv run --isolated --with pyright pyright deckstyle)

(cd "$TEMPLATE" && uv run --isolated --with pytest --with jsonschema pytest -q)

# 假專案：.git 標出專案根，帶範本附的品牌與作者設定
mkdir -p "$tmp/.git" "$tmp/deck"
cp "$TEMPLATE/_brand.yml" "$TEMPLATE/_quarto.yml" "$tmp/"
cp -R "$TEMPLATE/deckstyle/template/." "$tmp/deck/"
uv run --isolated --project "$TEMPLATE" deckstyle build "$tmp/deck" -o "$tmp/ok.pptx"
uv run scripts/lint.py "$tmp/ok.pptx"
uv run scripts/lint.py --help > /dev/null

# 反向：投影片出現程式識別字，lint 入口要以結束碼 1 失敗
python3 - "$tmp/deck/deck.yml" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text(encoding="utf-8").replace("規則只在雲端一份", "呼叫 load_data 取得規則"), encoding="utf-8")
PY
uv run --isolated --project "$TEMPLATE" deckstyle build "$tmp/deck" -o "$tmp/bad.pptx" --no-lint
if uv run scripts/lint.py "$tmp/bad.pptx" > /dev/null 2>&1; then
  echo "scripts/lint.py 沒有抓到程式識別字" >&2
  exit 1
fi
echo "ok   scripts/lint.py"
