#!/usr/bin/env bash
# vault-doctor 腳本測試（CI 以 skills/*/scripts/test.sh 執行）。
set -euo pipefail
cd "$(dirname "$0")"
python3 test_doctor.py
python3 doctor.py --help > /dev/null
