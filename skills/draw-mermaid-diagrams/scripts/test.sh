#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$DIR/lint_mermaid.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. --help 正常結束
uv run "$SCRIPT" --help >/dev/null

# 2. 合規圖表（含透明 subgraph 與語意邊框、YAML frontmatter）應通過
cat >"$TMP/good.md" <<'EOF'
# Good

```mermaid
---
config:
  look: neo
---
flowchart LR
    subgraph S1["接入層"]
        A["API"] --> B[("DB")]
    end
    style S1 fill:transparent,stroke:#2563EB,stroke-width:1.5px
    style A stroke-dasharray: 5 5
```

```mermaid
---
config:
  look: neo
---
sequenceDiagram
    autonumber
    A->>B: 請求
```
EOF

uv run "$SCRIPT" "$TMP/good.md" >/dev/null

# 3. 寫死 theme: base 與字色、未設透明底 subgraph、舊版 init、時序圖 rect 皆應被攔截
cat >"$TMP/bad.md" <<'EOF'
# Bad

```mermaid
%%{init: {'theme': 'base'}}%%
flowchart LR
    subgraph S1["沒有透明底"]
        A["節點"]:::card
    end
    classDef card fill:#FFFFFF,color:#1E293B
```

```mermaid
---
config:
  theme: base
---
sequenceDiagram
    rect rgb(248, 250, 252)
        A->>B: 呼叫
    end
```
EOF

if uv run "$SCRIPT" "$TMP/bad.md" >/dev/null; then
  echo "FAIL: bad.md should fail lint" >&2
  exit 1
fi

# 4. --json 輸出可解析且含預期規則
uv run "$SCRIPT" "$TMP/bad.md" --json >"$TMP/report.json" || true
uv run python - "$TMP/report.json" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
rules = {i["rule"] for i in data["issues"]}
expected = {"legacy-init", "hardcoded-theme", "hardcoded-color", "subgraph-fill", "sequence-rect"}
missing = expected - rules
assert not missing, f"missing rules: {missing}"
assert data["blocks_checked"] == 2
print("JSON check OK:", sorted(rules))
PY

echo "draw-mermaid-diagrams tests passed"
