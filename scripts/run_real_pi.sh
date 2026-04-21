#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
INPUT_BACKEND="${INPUT_BACKEND:-gpio}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
UI_BACKEND="${UI_BACKEND:-screen}"

# camera prototype validated kmsdrm for current Waveshare HDMI setup.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
export RECOGNIZER_SCREEN_FULLSCREEN="${RECOGNIZER_SCREEN_FULLSCREEN:-1}"
export RECOGNIZER_SCREEN_FILL="${RECOGNIZER_SCREEN_FILL:-1}"

exec "$PYTHON_BIN" app/main.py --runtime real --input "$INPUT_BACKEND" --ui-backend "$UI_BACKEND" --log-level "$LOG_LEVEL" "$@"
