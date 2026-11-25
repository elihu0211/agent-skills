#!/usr/bin/env bash
# draw-layered-diagrams 測試：--help、每個範例 --check 通過、目錄與多檔的規格探索與結束碼、溢字與規格錯誤以結束碼 1 擋下並回報規則、
# 節點圖的版面守門逐條擋得下、交叉畫跳線弧、--json 可解析、--svg 是合法 XML；有 Chrome 時另驗 PNG 尺寸為畫布兩倍，沒有就略過這一段。
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

# 4. 節點圖模式的規格錯誤與版面守門：每個案例只壞一件事，回報的規則與訊息要對得上
python3 - "$tmp" <<'PY'
"""寫出故意弄壞的節點圖規格；cases.tsv 記每個檔案應回報的規則與訊息片段。"""
import json, sys
from pathlib import Path

tmp = Path(sys.argv[1])
def spec(nodes, edges=(), **band):
    return {"title": "守門測試", "bands": [{"color": "blue", "name": "一層", "rows": nodes, **band}], "edges": list(edges)}
def node(i, col, span=6, **extra):
    return {"id": i, "at": [col, span], "text": [i], **extra}

row = [node("a", 1), node("b", 16), node("c", 31)]
two_rows = [[node("a", 1)], [node("b", 31)]]
def two_bands(**edge):
    bands = [{"color": c, "name": n, "rows": [[node(i, 1)]]} for c, n, i in (("blue", "一層", "a"), ("teal", "二層", "b"))]
    return {"title": "守門測試", "bands": bands, "edges": [{"from": "a", "to": "b", "label": "跨層", **edge}]}
def near_tip(dx):
    """兩個相鄰節點之間的雙字標籤，中心放在箭尖左方 -dx 像素。"""
    return spec([[node("a", 1), node("b", 10)]],
                [{"from": "a", "to": "b", "label": "到達", "label_at": 1, "shift": [dx, 0]}])
cases = {
    # 版面
    "through-node": (spec([row], [{"from": "a", "to": "c"}]), "layout", "穿過或貼到節點 b"),
    "node-overlap": (spec([[node("a", 1, 8), node("b", 8)]]), "layout", "重疊"),
    "label-on-node": (spec([row], [{"from": "a", "to": "b", "label": "這個標籤比兩個節點之間的空隙寬很多很多"}]),
                      "layout", "壓到節點"),
    "short-arrow": (spec([[node("a", 1), node("b", 7.3)]], [{"from": "a", "to": "b"}]), "layout", "線段太短"),
    "stacked-lines": (spec(two_rows, [{"from": "a.bottom@0.3", "to": "b.top@0.3"},
                                      {"from": "a.bottom@0.7", "to": "b.top@0.7"}], row_gap=90),
                      "layout", "疊在一起"),
    "leaves-bands": (spec([row], [{"from": "a.top", "to": "c.top", "depth": 120}]), "layout", "跑出層帶區域"),
    "into-panel": (spec([row], [{"from": "a.left", "to": "c.left", "depth": 60}]), "layout", "左側層名面板"),
    "label-on-frame": (two_bands(shift=[0, 22]), "layout", "層框邊線"),
    "label-on-arrowhead": (near_tip(-40), "layout", "蓋住自己的箭頭"),
    # 規格
    "unknown-node": (spec([row], [{"from": "a", "to": "zz"}]), "schema", "沒有這個節點"),
    "bad-side": (spec([row], [{"from": "a.middle", "to": "b"}]), "schema", "邊只有"),
    "off-grid": (spec([[node("a", 46)]]), "schema", "超出格線"),
    "duplicate-id": (spec([[node("a", 1), node("a", 16)]]), "schema", "id 重複"),
    "bad-accent": (spec([[node("a", 1, accent=3)]]), "schema", "行號"),
    "bad-divider": (spec([[node("a", 1, divider=1)]]), "schema", "分隔線"),
    "bad-fill": (spec([[node("a", 1, fill="blue")]]), "schema", "white, tint"),
    "bad-band-en": (spec([row], en=["一", "二", "三"]), "schema", "2 行清單"),
    # 側欄、層內標題版型、條列面板與大型箭頭
    "bad-labels": ({**spec([row]), "labels": "bottom"}, "schema", "層名面板"),
    "align-without-top": (spec([row], title_align="center"), "schema", "只在 labels: top"),
    "rail-span": ({**spec([row]), "rails": [{"id": "r", "side": "left", "bands": [1, 2], "text": ["欄"]}]},
                  "schema", "起始層, 結束層"),
    "rail-duplicate-id": ({**spec([row]), "rails": [{"id": "a", "side": "left", "bands": [1, 1], "text": ["欄"]}]},
                          "schema", "id 重複"),
    "bad-bullets": (spec([[node("a", 1, bullets=[["重點", "說明", "pink"]])]]), "schema", "1–6 個條目"),
    "block-with-text": (spec([[node("a", 1, block="down")]]), "schema", "不放文字"),
    "header-on-node": ({**spec([row]), "labels": "top"}, "layout", "重疊"),
    "bridge-in-graph": (spec([row], bridge="節點圖模式沒有層間說明框"), "schema", "不認得的鍵"),
}
# 對照組：同樣的圖把標籤放開就要通過，守門才不是一律擋下
for name, body in {"pass-between-bands": two_bands(), "pass-clear-of-arrowhead": near_tip(-60)}.items():
    (tmp / f"{name}.yml").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
with open(tmp / "cases.tsv", "w", encoding="utf-8") as index:
    for name, (body, rule, needle) in cases.items():
        (tmp / f"{name}.yml").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        index.write(f"{name}\t{rule}\t{needle}\n")
PY
while IFS=$'\t' read -r name rule needle; do
  if uv run "$DRAW" "$tmp/$name.yml" --check --json > "$tmp/$name.json"; then
    echo "FAIL: $name 應被擋下" >&2
    exit 1
  fi
  python3 - "$tmp/$name.json" "$name" "$rule" "$needle" <<'PY'
import json, sys
path, name, rule, needle = sys.argv[1:]
issues = json.load(open(path, encoding="utf-8"))["issues"]
assert issues and {i["rule"] for i in issues} == {rule}, (name, issues)
assert any(needle in i["message"] for i in issues), (name, needle, issues)
PY
done < "$tmp/cases.tsv"
echo "graph guard cases OK: $(wc -l < "$tmp/cases.tsv" | tr -d ' ')"
for spec in "$tmp"/pass-*.yml; do
  uv run "$DRAW" "$spec" --check > /dev/null || { echo "FAIL: $(basename "$spec") 應通過" >&2; exit 1; }
done

# 層框守門給的 shift 照著改就要通過
uv run python3 - "$tmp" "$DRAW" <<'PY'
import json, re, subprocess, sys
from pathlib import Path
tmp, draw = Path(sys.argv[1]), sys.argv[2]
message = json.load(open(tmp / "label-on-frame.json", encoding="utf-8"))["issues"][0]["message"]
spec = json.load(open(tmp / "label-on-frame.yml", encoding="utf-8"))
spec["edges"][0]["shift"] = json.loads(re.search(r"shift: (\[[^\]]*\])", message).group(1))
(tmp / "frame-fixed.yml").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
subprocess.run(["uv", "run", draw, str(tmp / "frame-fixed.yml"), "--check"], check=True, stdout=subprocess.DEVNULL)
PY

# 群組框內距要容得下最長的箭頭：從外面接到成員時，箭頭和框線之間還看得到線身
uv run --with 'pyyaml>=6' python3 -c '
import sys
sys.path.insert(0, "scripts")
import graph
longest = max(head for _, head, _ in graph.WEIGHTS.values())
assert graph.GROUP_PAD >= longest + 8, (graph.GROUP_PAD, longest)
'

# 5. 交叉的線畫跳線弧；從同一點分岔的線不算交叉
uv run "$DRAW" assets/examples/order-fulfilment-graph.yml --check --svg "$tmp/graph.svg" > /dev/null
grep -q "A9,9 0 0" "$tmp/graph.svg" || { echo "FAIL: 範例裡的交叉沒有畫跳線弧" >&2; exit 1; }
python3 -c "import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])" "$tmp/graph.svg"

# 6. --svg 是合法 XML
uv run "$DRAW" assets/examples/three-tier-web.yml --check --svg "$tmp/web.svg" > /dev/null
python3 -c "import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])" "$tmp/web.svg"

# 7. 目錄與多檔：遞迴找出規格（含寫壞的），略過別的 YAML、隱藏目錄與 node_modules；結束碼取最大
repo="$tmp/repo"
mkdir -p "$repo/docs/sub" "$repo/.agents" "$repo/node_modules"
cp assets/examples/three-tier-web.yml "$repo/docs/ok.yml"
cp assets/examples/osi-bms-iiot.yml "$repo/docs/sub/ok-too.yaml"
printf 'title: 壞色票\nbands:\n  - {color: pink, name: 一層, boxes: [[甲]]}\n' > "$repo/docs/sub/bad.yml"
printf 'title: 語法錯誤\nbands:\n  - {color: blue\n' > "$repo/docs/broken.yml"
printf 'slides:\n  - title: 簡報規格不是分層圖\n' > "$repo/docs/deck.yml"
printf 'name: {{ 樣板 }}: x\n' > "$repo/docs/template.yml"
cp "$repo/docs/sub/bad.yml" "$repo/.agents/hidden.yml"
cp "$repo/docs/sub/bad.yml" "$repo/node_modules/vendored.yml"
set +e
uv run "$DRAW" --check --json "$repo" > "$tmp/dir.jsonl"
rc=$?
set -e
[ "$rc" -eq 1 ] || { echo "FAIL: 目錄裡有壞規格應以 1 結束，實得 $rc" >&2; exit 1; }
python3 - "$tmp/dir.jsonl" "$repo" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[2])
got = {str(Path(r["spec"]).relative_to(root)): r["ok"]
       for r in map(json.loads, open(sys.argv[1], encoding="utf-8"))}
want = {"docs/ok.yml": True, "docs/sub/ok-too.yaml": True, "docs/sub/bad.yml": False, "docs/broken.yml": False}
assert got == want, got
print("directory check OK:", len(got), "specs")
PY
rm "$repo/docs/sub/bad.yml" "$repo/docs/broken.yml"
uv run "$DRAW" --check "$repo" > /dev/null || { echo "FAIL: 只剩好規格的目錄應通過" >&2; exit 1; }
mkdir "$tmp/empty"
uv run "$DRAW" --check "$tmp/empty" 2> "$tmp/empty.err" || { echo "FAIL: 沒有規格的目錄應以 0 結束" >&2; exit 1; }
grep -q "沒有找到分層圖規格" "$tmp/empty.err" || { echo "FAIL: 沒有規格時要提示" >&2; exit 1; }
for case in "-o $tmp/x.png $repo" "--check $repo/docs/ok.yml $tmp/nope.yml"; do
  set +e
  # shellcheck disable=SC2086
  uv run "$DRAW" $case > /dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" -eq 2 ] || { echo "FAIL: draw.py $case 應以 2 結束，實得 $rc" >&2; exit 1; }
done

# 8. 有 Chrome 才驗 PNG：尺寸要是畫布的兩倍
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
