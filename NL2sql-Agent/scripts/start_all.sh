#!/usr/bin/env bash
# 一键：ES（Docker，可选）→ 检查 rag-core（可跳过）→ 启动 NL2SQL Web
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_ES="${SKIP_ES:-0}"
SKIP_RAG="${SKIP_RAG:-0}"
SKIP_WEB="${SKIP_WEB:-0}"
# 无 rag 时默认只告警并继续起 Web（问答需稍后配好 rag 再 sync 规则）
REQUIRE_RAG="${REQUIRE_RAG:-0}"

echo "=== [1/3] Elasticsearch ==="
if [[ "$SKIP_ES" == "1" ]]; then
  echo "跳过 ES（SKIP_ES=1）"
else
  if ! bash "$ROOT/scripts/start_es.sh"; then
    echo "警告: ES 未就绪。可稍后启动，或 SKIP_ES=1 并改用已有集群。" >&2
    echo "      若本机为 aarch64 且 Docker 拉不到镜像，请自备 ES 后 SKIP_ES=1。" >&2
  fi
fi

echo "=== [2/3] rag-core ==="
if [[ "$SKIP_RAG" == "1" ]]; then
  echo "跳过 rag 检查（SKIP_RAG=1）"
else
  if ! bash "$ROOT/scripts/start_rag_core.sh"; then
    echo "警告: 未检测到可用 rag-core。Web 仍可启动，但规则召回/问答不可用。" >&2
    echo "      请按 docs/DEPLOY.md 部署或对接 rag，再执行规则同步。" >&2
    if [[ "$REQUIRE_RAG" == "1" ]]; then
      exit 1
    fi
  fi
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
  echo "已生成 .env，请填写 NL2SQL_LLM_API_KEY、NL2SQL_RAG_ACCESS_KEY 后使用。"
fi

echo "启动 Web: http://127.0.0.1:${NL2SQL_WEB_PORT:-8199}"
echo "健康检查: curl -s http://127.0.0.1:${NL2SQL_WEB_PORT:-8199}/api/health"
echo "下一步: 浏览器打开 Web → 选一个数据源并「测试当前数据源」→ 同步规则（见 README / docs/TEST.md）"
exec bash "$ROOT/scripts/start_web.sh"
