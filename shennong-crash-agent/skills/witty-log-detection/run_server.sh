#!/bin/bash
# Launcher for witty-log-detection SSE MCP server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PACKAGE_NAME="$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PROJECT_ROOT/package.json" | head -n 1)"
PACKAGE_KEY="${PACKAGE_NAME#@}"
PACKAGE_KEY="${PACKAGE_KEY//\//-}"
VENV_ROOT="${SHENNONG_VENV_CACHE:-$HOME/.cache/witty-agents}/$PACKAGE_KEY/venvs"
VENV="$VENV_ROOT/witty-log-detection"
export SHENNONG_OCR_MODELS_DIR="${SHENNONG_VENV_CACHE:-$HOME/.cache/witty-agents}/$PACKAGE_KEY/ocr-models"
export PYTHONPATH="$PROJECT_ROOT/skills/witty-log-detection"
cd "$PROJECT_ROOT/skills/witty-log-detection"
exec "$VENV/bin/python" src/server.py
