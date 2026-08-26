#!/usr/bin/env bash
# 启动 Elasticsearch（Docker Compose）。若 9200 已可用则跳过。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/docker-compose.yml"

if curl -sf http://127.0.0.1:9200 >/dev/null 2>&1; then
  echo "ES 已在运行: http://127.0.0.1:9200"
  curl -s http://127.0.0.1:9200 || true
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 docker。请安装 Docker，或自行部署 ES 7.x 并监听 9200。" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f "$COMPOSE_FILE")
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose -f "$COMPOSE_FILE")
else
  echo "未检测到 docker compose / docker-compose。" >&2
  exit 1
fi

echo "启动 Elasticsearch (compose) ..."
"${DC[@]}" up -d

echo "等待 ES 就绪..."
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:9200 >/dev/null 2>&1; then
    echo "ES OK"
    curl -s http://127.0.0.1:9200 || true
    exit 0
  fi
  sleep 2
done
echo "ES 启动超时，请检查: ${DC[*]} logs" >&2
exit 1
