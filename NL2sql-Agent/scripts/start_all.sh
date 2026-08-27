#!/usr/bin/env bash
# 一键：ES（Docker）→ 检查 rag-core → 启动 NL2SQL Web
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_ES="${SKIP_ES:-0}"
SKIP_RAG="${SKIP_RAG:-0}"
SKIP_WEB="${SKIP_WEB:-0}"

echo "=== [1/3] Elasticsearch ==="
if [[ "$SKIP_ES" == "1" ]]; then
  echo "跳过 ES（SKIP_ES=1）"
else
  bash "$ROOT/scripts/start_es.sh"
fi

echo "=== [2/3] rag-core ==="
if [[ "$SKIP_RAG" == "1" ]]; then
  echo "跳过 rag 检查（SKIP_RAG=1）"
else
  bash "$ROOT/scripts/start_rag_core.sh"
fi

echo "=== [3/3] NL2SQL Web ==="
if [[ "$SKIP_WEB" == "1" ]]; then
  echo "跳过 Web（SKIP_WEB=1）"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "未找到 .venv，正在创建并安装依赖..."
  python3 -m venv "$ROOT/.venv"
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  pip install -U pip
  pip install -r "$ROOT/requirements.txt"
else
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "已生成 .env，请填写 NL2SQL_LLM_API_KEY 等后重启 Web。"
fi

echo "启动 Web: http://127.0.0.1:${NL2SQL_WEB_PORT:-8199}"
echo "健康检查: curl -s http://127.0.0.1:${NL2SQL_WEB_PORT:-8199}/api/health"
exec bash "$ROOT/scripts/start_web.sh"
