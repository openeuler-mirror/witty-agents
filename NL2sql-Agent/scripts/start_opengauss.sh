#!/usr/bin/env bash
# 若本机已有 OpenGauss 则跳过。默认连容器 opengauss 映射的 5434。
set -euo pipefail
if (echo >/dev/tcp/127.0.0.1/5434) >/dev/null 2>&1; then
  echo "OpenGauss/PG 端口 5434 已可连，跳过启动"
  exit 0
fi
if ! command -v docker >/dev/null; then
  echo "未找到 docker，无法启动 OpenGauss" >&2
  exit 1
fi
docker rm -f nl2sql-opengauss >/dev/null 2>&1 || true
docker run -d --name nl2sql-opengauss --privileged=true \
  -e GS_PASSWORD='OpenGauss@123' \
  -p 5434:5432 \
  opengauss/opengauss:5.0.0
echo "已启动 nl2sql-opengauss -> 127.0.0.1:5434 用户 gaussdb"
echo "请把 configs/datasources.yaml 中 local-opengauss.password 改成 OpenGauss@123"
