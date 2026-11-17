#!/usr/bin/env bash
# audit-obsidian-vault 腳本測試（CI 以 skills/*/scripts/test.sh 執行）。
set -euo pipefail
cd "$(dirname "$0")"
python3 test_audit.py
python3 audit.py --help > /dev/null
