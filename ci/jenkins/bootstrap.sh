#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE=${JENKINS_ENV_FILE:-"${SCRIPT_DIR}/.runtime.env"}
EXAMPLE_ENV="${SCRIPT_DIR}/.env.example"

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "缺少命令：$1" >&2
        exit 1
    }
}

require_command docker
require_command curl
require_command python3
docker compose version >/dev/null 2>&1 || {
    echo "需要 Docker Compose v2，请先安装或启用 docker compose。" >&2
    exit 1
}

if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${EXAMPLE_ENV}" "${ENV_FILE}"
    echo "已生成 ${ENV_FILE}。"
    echo "请先确认其中 WITTY_AGENTS_REPO_URL 和 WITTY_AGENTS_BRANCH，然后重新运行本脚本。"
    exit 2
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${WITTY_AGENTS_REPO_URL:?请在 .runtime.env 中填写 WITTY_AGENTS_REPO_URL}"
JENKINS_DATA_ROOT=${JENKINS_DATA_ROOT:-/home/witty-agents-jenkins}
JENKINS_HTTP_PORT=${JENKINS_HTTP_PORT:-18081}
JENKINS_ADMIN_PASSWORD_SOURCE=${JENKINS_ADMIN_PASSWORD_SOURCE:-./secrets/admin-password}
WITTY_AGENTS_RUNTIME_IMAGE=${WITTY_AGENTS_RUNTIME_IMAGE:-witty-agents-ci-runtime:oe2403sp4-node20-py311}
WITTY_AGENTS_BUILD_RUNTIME_IMAGE=${WITTY_AGENTS_BUILD_RUNTIME_IMAGE:-true}
WITTY_AGENTS_RUNTIME_BASE_IMAGE=${WITTY_AGENTS_RUNTIME_BASE_IMAGE:-openeuler/openeuler:24.03-lts}
WITTY_AGENTS_OPENCODE_VERSION=${WITTY_AGENTS_OPENCODE_VERSION:-1.18.23}

if [[ "${JENKINS_ADMIN_PASSWORD_SOURCE}" = /* ]]; then
    PASSWORD_FILE=${JENKINS_ADMIN_PASSWORD_SOURCE}
else
    PASSWORD_FILE="${SCRIPT_DIR}/${JENKINS_ADMIN_PASSWORD_SOURCE#./}"
fi

mkdir -p \
    "${JENKINS_DATA_ROOT}/home" \
    "${JENKINS_DATA_ROOT}/cache/npm" \
    "${JENKINS_DATA_ROOT}/cache/pip" \
    "${JENKINS_DATA_ROOT}/ocr-model-cache" \
    "$(dirname -- "${PASSWORD_FILE}")"

if [[ ! -s "${PASSWORD_FILE}" ]]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 24 > "${PASSWORD_FILE}"
    else
        tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 > "${PASSWORD_FILE}"
        printf '\n' >> "${PASSWORD_FILE}"
    fi
    echo "已生成 Jenkins 初始密码文件：${PASSWORD_FILE}"
fi
chmod 600 "${PASSWORD_FILE}"

if [[ $(id -u) -eq 0 ]]; then
    chown -R 1000:1000 "${JENKINS_DATA_ROOT}/home"
else
    if [[ ! -w "${JENKINS_DATA_ROOT}/home" ]]; then
        echo "当前用户不能写入 ${JENKINS_DATA_ROOT}/home，请使用 sudo 运行或修改 JENKINS_DATA_ROOT。" >&2
        exit 1
    fi
fi

if stat -c '%g' /var/run/docker.sock >/dev/null 2>&1; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
else
    DOCKER_GID=$(stat -f '%g' /var/run/docker.sock)
fi
export DOCKER_GID JENKINS_DATA_ROOT JENKINS_HTTP_PORT JENKINS_ADMIN_PASSWORD_SOURCE

python3 - "${ENV_FILE}" "${DOCKER_GID}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
gid = sys.argv[2]
lines = path.read_text().splitlines()
updated = []
seen = False
for line in lines:
    if line.startswith("DOCKER_GID="):
        updated.append(f"DOCKER_GID={gid}")
        seen = True
    else:
        updated.append(line)
if not seen:
    updated.append(f"DOCKER_GID={gid}")
path.write_text("\n".join(updated) + "\n")
PY

if ! docker image inspect "${WITTY_AGENTS_RUNTIME_IMAGE}" >/dev/null 2>&1; then
    if [[ -n "${WITTY_AGENTS_RUNTIME_IMAGE_SOURCE:-}" ]] \
        && docker image inspect "${WITTY_AGENTS_RUNTIME_IMAGE_SOURCE}" >/dev/null 2>&1; then
        docker tag "${WITTY_AGENTS_RUNTIME_IMAGE_SOURCE}" "${WITTY_AGENTS_RUNTIME_IMAGE}"
        echo "已创建通用运行镜像标签：${WITTY_AGENTS_RUNTIME_IMAGE}"
    elif [[ "${WITTY_AGENTS_BUILD_RUNTIME_IMAGE}" = "true" ]]; then
        echo "正在为当前 $(uname -m) 架构构建流水线运行镜像：${WITTY_AGENTS_RUNTIME_IMAGE}"
        docker build \
            --build-arg "OPEN_EULER_IMAGE=${WITTY_AGENTS_RUNTIME_BASE_IMAGE}" \
            --build-arg "OPENCODE_VERSION=${WITTY_AGENTS_OPENCODE_VERSION}" \
            --tag "${WITTY_AGENTS_RUNTIME_IMAGE}" \
            --file "${SCRIPT_DIR}/Dockerfile.runtime" \
            "${SCRIPT_DIR}"
    else
        echo "警告：未找到流水线运行镜像 ${WITTY_AGENTS_RUNTIME_IMAGE}。" >&2
        echo "Jenkins 可以启动，但首次构建前必须导入该镜像、配置 WITTY_AGENTS_RUNTIME_IMAGE_SOURCE，或启用 WITTY_AGENTS_BUILD_RUNTIME_IMAGE。" >&2
    fi
fi

docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/docker-compose.yml" up -d --build

for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${JENKINS_HTTP_PORT}/login" >/dev/null 2>&1; then
        echo "Jenkins 已启动：http://127.0.0.1:${JENKINS_HTTP_PORT}/"
        echo "Job：${WITTY_AGENTS_JOB_NAME:-witty-agent-package-ci}"
        echo "管理员用户：${JENKINS_ADMIN_USER:-admin}"
        echo "初始密码保存在：${PASSWORD_FILE}"
        exit 0
    fi
    sleep 2
done

echo "Jenkins 未在预期时间内就绪，请运行以下命令查看日志：" >&2
echo "docker compose --env-file ${ENV_FILE} -f ${SCRIPT_DIR}/docker-compose.yml logs --tail=200" >&2
exit 1
