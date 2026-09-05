#!/usr/bin/env bash
# 启动 HBase REST（127.0.0.1:16080）。默认把官方二进制装到仓库 .opt/（不拉 Docker 镜像）。
set -euo pipefail

REST_URL="http://127.0.0.1:16080/version"
if curl -sf -m 2 "$REST_URL" >/dev/null 2>&1; then
  echo "HBase REST 已在 16080"
  curl -sS -m 2 "$REST_URL" || true
  echo
  exit 0
fi

if [[ -z "${JAVA_HOME:-}" ]]; then
  JAVA_BIN="$(command -v java || true)"
  if [[ -n "$JAVA_BIN" ]]; then
    JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$JAVA_BIN")")")"
  fi
fi
if [[ -z "${JAVA_HOME:-}" || ! -x "${JAVA_HOME}/bin/java" ]]; then
  echo "未找到 JAVA_HOME，无法启动 HBase" >&2
  exit 1
fi
export JAVA_HOME

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HBASE_VER="${NL2SQL_HBASE_VERSION:-2.4.18}"
# 默认装到仓库 .opt/，避免写满根分区上的 /root 或 /var/lib/docker
OPT_ROOT="${NL2SQL_HBASE_OPT:-$ROOT/.opt}"
HBASE_HOME="${NL2SQL_HBASE_HOME:-$OPT_ROOT/hbase-${HBASE_VER}}"
DATA_ROOT="${NL2SQL_HBASE_DATA:-$ROOT/data/hbase-standalone}"
mkdir -p "$OPT_ROOT" "$DATA_ROOT/root" "$DATA_ROOT/zk"

if [[ ! -x "$HBASE_HOME/bin/hbase" ]]; then
  tarball="$OPT_ROOT/hbase-${HBASE_VER}-bin.tar.gz"
  url="${NL2SQL_HBASE_URL:-https://mirrors.huaweicloud.com/apache/hbase/${HBASE_VER}/hbase-${HBASE_VER}-bin.tar.gz}"
  echo "下载 HBase ${HBASE_VER} -> $tarball"
  curl -fL --retry 3 --retry-delay 2 -o "$tarball" "$url"
  tar -xzf "$tarball" -C "$OPT_ROOT"
fi

cat > "$HBASE_HOME/conf/hbase-site.xml" <<EOF
<?xml version="1.0"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property>
    <name>hbase.rootdir</name>
    <value>file://${DATA_ROOT}/root</value>
  </property>
  <property>
    <name>hbase.cluster.distributed</name>
    <value>false</value>
  </property>
  <property>
    <name>hbase.zookeeper.property.dataDir</name>
    <value>${DATA_ROOT}/zk</value>
  </property>
  <property>
    <name>hbase.unsafe.stream.capability.enforce</name>
    <value>false</value>
  </property>
  <property>
    <name>hbase.rest.port</name>
    <value>16080</value>
  </property>
  <property>
    <name>hbase.rest.readonly</name>
    <value>true</value>
  </property>
</configuration>
EOF

if ! grep -q '^export JAVA_HOME=' "$HBASE_HOME/conf/hbase-env.sh"; then
  echo "export JAVA_HOME=${JAVA_HOME}" >> "$HBASE_HOME/conf/hbase-env.sh"
fi

echo "启动 HBase standalone（JAVA_HOME=$JAVA_HOME）"
"$HBASE_HOME/bin/start-hbase.sh"

for i in $(seq 1 45); do
  if (echo >/dev/tcp/127.0.0.1/16000) >/dev/null 2>&1; then
    echo "Master 16000 已监听"
    break
  fi
  sleep 2
done

"$HBASE_HOME/bin/hbase-daemon.sh" start rest -p 16080 || \
  "$HBASE_HOME/bin/hbase-daemon.sh" start rest

for i in $(seq 1 30); do
  if curl -sf -m 2 "$REST_URL" >/dev/null 2>&1; then
    echo "HBase REST 就绪 -> $REST_URL"
    curl -sS -m 2 "$REST_URL" || true
    echo
    exit 0
  fi
  sleep 2
done

echo "HBase REST 启动超时，请看 $HBASE_HOME/logs" >&2
ls -lt "$HBASE_HOME/logs" 2>/dev/null | head -5 || true
exit 1
