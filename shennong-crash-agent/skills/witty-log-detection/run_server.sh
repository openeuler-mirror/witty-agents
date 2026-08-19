#!/bin/bash
# Launcher for witty-log-detection SSE MCP server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$PROJECT_ROOT/.venvs/witty-log-detection"
export PYTHONPATH="$PROJECT_ROOT/skills/witty-log-detection"
cd "$PROJECT_ROOT/skills/witty-log-detection"
exec "$VENV/bin/python" src/server.py
