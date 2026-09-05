#!/bin/bash
# Launcher that runs crash-feature-matcher scripts with the package venv Python.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PACKAGE_NAME="$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PROJECT_ROOT/package.json" 2>/dev/null | head -n 1)"
PACKAGE_KEY="${PACKAGE_NAME#@}"
PACKAGE_KEY="${PACKAGE_KEY//\//-}"
CACHE_ROOT="${SHENNONG_VENV_CACHE:-$HOME/.cache/witty-agents}"
VENV="$CACHE_ROOT/$PACKAGE_KEY/venvs/crash-feature-matcher"
if [ ! -x "$VENV/bin/python" ]; then
  VENV="$CACHE_ROOT/venvs/crash-feature-matcher"
fi
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
exec "$VENV/bin/python" "$@"
