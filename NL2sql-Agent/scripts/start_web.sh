#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
HOST="${NL2SQL_WEB_HOST:-0.0.0.0}"
PORT="${NL2SQL_WEB_PORT:-8199}"
exec python3 -m uvicorn apps.web.main:app --host "$HOST" --port "$PORT" --reload
