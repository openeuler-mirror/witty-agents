#!/usr/bin/env bash
# 检查 / 对齐 rag-core 端口（默认 19988）。
# 优先使用已运行实例；若仅在 9988 等端口可用，则用 ncat 代理到 19988。
# 本仓库不内嵌完整 rag-core 运行时（依赖 DB/向量库），请按 docs/DEPLOY.md 部署或对接已有服务。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${RAG_PORT:-19988}"
UPSTREAM="${RAG_UPSTREAM:-}"
PID_FILE="$ROOT/data/rag_proxy.pid"
LOG_FILE="$ROOT/data/rag_proxy.log"

mkdir -p "$ROOT/data"

health() {
  local url="$1"
  curl -sf -o /dev/null -w "%{http_code}" "$url/health_check" 2>/dev/null || echo "000"
}

if [[ "$(health "http://127.0.0.1:${PORT}")" == "200" ]]; then
  echo "rag-core already healthy on :${PORT}"
  exit 0
fi

if [[ -z "$UPSTREAM" ]]; then
  for p in 9988 19988 8000; do
    if [[ "$(health "http://127.0.0.1:${p}")" == "200" ]]; then
      UPSTREAM="http://127.0.0.1:${p}"
      break
    fi
  done
fi

if [[ -n "$UPSTREAM" && "$UPSTREAM" != "http://127.0.0.1:${PORT}" ]]; then
  hostport="${UPSTREAM#http://}"
  host="${hostport%%:*}"
  up_port="${hostport##*:}"
  if ! command -v ncat >/dev/null 2>&1 && ! command -v nc >/dev/null 2>&1; then
    echo "发现上游 rag-core ${UPSTREAM}，但缺少 ncat/nc，无法自动代理到 :${PORT}。" >&2
    echo "请把 configs/rag_core.yaml 的 base_url 改成 ${UPSTREAM}，或安装 nmap-ncat 后重试。" >&2
    exit 1
  fi
  echo "proxy :${PORT} -> ${host}:${up_port}"
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "proxy already running pid=$(cat "$PID_FILE")"
  else
    if command -v ncat >/dev/null 2>&1; then
      nohup ncat -l "${PORT}" --keep-open --sh-exec "ncat ${host} ${up_port}" >"$LOG_FILE" 2>&1 &
    else
      echo "请使用 ncat（nmap）做端口代理；busybox nc 能力因发行版而异。" >&2
      exit 1
    fi
    echo $! >"$PID_FILE"
    sleep 0.5
  fi
  code="$(health "http://127.0.0.1:${PORT}")"
  if [[ "$code" == "200" ]]; then
    echo "rag-core ready via proxy http://127.0.0.1:${PORT}"
    exit 0
  fi
  echo "proxy health failed: $code (see $LOG_FILE)" >&2
  exit 1
fi

echo "未发现可用 rag-core。" >&2
echo "请先部署 rag-core（见 docs/DEPLOY.md），并确保健康检查可用：" >&2
echo "  curl -s http://127.0.0.1:19988/health_check" >&2
echo "或设置已运行地址: RAG_UPSTREAM=http://127.0.0.1:9988 $0" >&2
exit 1
