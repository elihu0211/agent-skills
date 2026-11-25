#!/usr/bin/env bash
# draw-layered-diagrams 測試：--help、每個範例 --check 通過、溢字與規格錯誤以結束碼 1 擋下並回報規則、
# --json 可解析、--svg 是合法 XML；有 Chrome 時另驗 PNG 尺寸為畫布兩倍，沒有就略過這一段。
set -euo pipefail
cd "$(dirname "$0")/.."
DRAW=scripts/draw.py
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

uvx ruff check scripts
uv run "$DRAW" --help > /dev/null

# 1. 範例規格都要通過
for spec in assets/examples/*.yml; do
  uv run "$DRAW" "$spec" --check > /dev/null
done

# 2. 溢字：四個方塊平分一欄，標題故意寫長，要以 overflow 擋下
cat > "$tmp/overflow.yml" <<'EOF'
title: 溢字測試
bands:
  - color: blue
    name: 一層
    boxes:
      - [這個方塊的標題故意寫得非常非常長一定放不下]
      - [短]
      - [短]
      - [短]
EOF
if uv run "$DRAW" "$tmp/overflow.yml" --check --json > "$tmp/overflow.json"; then
  echo "FAIL: overflow.yml 應被擋下" >&2
  exit 1
fi

# 3. 規格錯誤：不認得的色票、cells 格數不符、最後一層放說明框、方塊超過三行
cat > "$tmp/schema.yml" <<'EOF'
title: 規格錯誤測試
columns:
  - {title: 甲}
  - {title: 乙}
bands:
  - color: pink
    name: 一層
    cells:
      - - [甲一]
  - color: gray
    name: 二層
    cells:
      - - [一, 二, 三, 四]
      - - [乙二]
    bridge: 最後一層不能有說明框
EOF
if uv run "$DRAW" "$tmp/schema.yml" --check --json > "$tmp/schema.json"; then
  echo "FAIL: schema.yml 應被擋下" >&2
  exit 1
fi

python3 - "$tmp/overflow.json" "$tmp/schema.json" <<'PY'
import json, sys
overflow = json.load(open(sys.argv[1], encoding="utf-8"))
schema = json.load(open(sys.argv[2], encoding="utf-8"))
assert not overflow["ok"] and {i["rule"] for i in overflow["issues"]} == {"overflow"}, overflow
wheres = {i["where"] for i in schema["issues"]}
assert not schema["ok"] and {i["rule"] for i in schema["issues"]} == {"schema"}, schema
for expected in ("bands[1].color", "bands[1].cells", "bands[2].cells[1][1]", "bands[2].bridge"):
    assert expected in wheres, (expected, sorted(wheres))
print("JSON check OK:", len(schema["issues"]), "schema issues")
PY

# 4. --svg 是合法 XML
uv run "$DRAW" assets/examples/three-tier-web.yml --check --svg "$tmp/web.svg" > /dev/null
python3 -c "import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])" "$tmp/web.svg"

# 5. 有 Chrome 才驗 PNG：尺寸要是畫布的兩倍
uv run "$DRAW" assets/examples/three-tier-web.yml --check --json > "$tmp/size.json"
set +e
uv run "$DRAW" assets/examples/three-tier-web.yml -o "$tmp/web.png" > /dev/null 2> "$tmp/png.err"
rc=$?
set -e
if [ "$rc" -eq 2 ] && grep -q "找不到 Chrome" "$tmp/png.err"; then
  echo "略過 PNG 檢查：這台機器沒有 Chrome"
elif [ "$rc" -ne 0 ]; then
  cat "$tmp/png.err" >&2
  exit 1
else
  python3 - "$tmp/size.json" "$tmp/web.png" <<'PY'
import json, struct, sys
w, h = json.load(open(sys.argv[1], encoding="utf-8"))["size"]
data = open(sys.argv[2], "rb").read(24)
assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
pw, ph = struct.unpack(">II", data[16:24])
assert (pw, ph) == (w * 2, h * 2), ((pw, ph), (w, h))
print(f"PNG check OK: {pw}x{ph}")
PY
fi

echo "draw-layered-diagrams tests passed"
