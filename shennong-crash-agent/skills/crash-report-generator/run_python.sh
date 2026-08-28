#!/bin/bash
# Launcher that runs crash-report-generator scripts with the package venv Python
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PACKAGE_NAME="$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PROJECT_ROOT/package.json" | head -n 1)"
PACKAGE_KEY="${PACKAGE_NAME#@}"
PACKAGE_KEY="${PACKAGE_KEY//\//-}"
VENV_ROOT="${SHENNONG_VENV_CACHE:-$HOME/.cache/witty-agents}/$PACKAGE_KEY/venvs"
exec "$VENV_ROOT/crash-report-generator/bin/python" "$@"
