#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOCAL_ENV_FILE="$REPO_ROOT/.env.real.local"
if [ -f "$LOCAL_ENV_FILE" ]; then
	set -a
	# Load Pi-local secrets without requiring manual export each run.
	. "$LOCAL_ENV_FILE"
	set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
INPUT_BACKEND="${INPUT_BACKEND:-gpio}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
UI_BACKEND="${UI_BACKEND:-screen}"

# camera prototype validated kmsdrm for current Waveshare HDMI setup.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
export RECOGNIZER_SCREEN_WIDTH="${RECOGNIZER_SCREEN_WIDTH:-480}"
export RECOGNIZER_SCREEN_HEIGHT="${RECOGNIZER_SCREEN_HEIGHT:-800}"
export RECOGNIZER_SCREEN_FULLSCREEN="${RECOGNIZER_SCREEN_FULLSCREEN:-1}"
export RECOGNIZER_SCREEN_FILL="${RECOGNIZER_SCREEN_FILL:-0}"
export RECOGNIZER_UI_SCALE="${RECOGNIZER_UI_SCALE:-1.0}"
export RECOGNIZER_PREVIEW_ROTATION="${RECOGNIZER_PREVIEW_ROTATION:-0}"
export RECOGNIZER_CAMERA_WIDTH="${RECOGNIZER_CAMERA_WIDTH:-960}"
export RECOGNIZER_CAMERA_HEIGHT="${RECOGNIZER_CAMERA_HEIGHT:-540}"
# Keep the sensor on a native 16:9 mode, then normalize to a portrait frame
# once in the camera adapter so preview and model consume the same image.
# If the module is mounted in the opposite portrait direction on your unit,
# switch this to 270.
export RECOGNIZER_CAMERA_ROTATION="${RECOGNIZER_CAMERA_ROTATION:-90}"
export RECOGNIZER_CAMERA_SWAP_RED_BLUE="${RECOGNIZER_CAMERA_SWAP_RED_BLUE:-1}"

exec "$PYTHON_BIN" app/main.py --runtime real --input "$INPUT_BACKEND" --ui-backend "$UI_BACKEND" --log-level "$LOG_LEVEL" "$@"
