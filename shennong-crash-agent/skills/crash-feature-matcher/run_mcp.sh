#!/bin/bash
# Launcher for crash-feature-matcher stdio MCP server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$PROJECT_ROOT/.venvs/crash-feature-matcher"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
exec "$VENV/bin/python" -c "from crash_matcher.skill import mcp; mcp.run(transport='stdio')"
