#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
INPUT_BACKEND="${INPUT_BACKEND:-gpio}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

exec "$PYTHON_BIN" app/main.py --runtime real --input "$INPUT_BACKEND" --log-level "$LOG_LEVEL" "$@"
