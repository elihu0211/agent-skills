#!/usr/bin/env bash
# build-tech-deck 腳本測試：範本可建置且零折行、lint 抓得到違規。
set -euo pipefail
cd "$(dirname "$0")"
uv run test_lint.py
