#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/simple-src"
BUILD_DIR="${SRC_DIR}/build"
OUTPUT_DIR="${SRC_DIR}/output"
LIBSIMPLE_LINK="${SCRIPT_DIR}/libsimple"
echo "[Tokenizer] 查询最新 release 版本..."
LATEST_TAG=$(curl -s https://api.github.com/repos/wangfenjin/simple/releases/latest | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
if [[ -z "${LATEST_TAG}" ]]; then
    echo "[WARN] 无法获取最新版本，使用默认版本 v0.7.1"
    LATEST_TAG="v0.7.1"
fi
echo "[Tokenizer] 最新版本: ${LATEST_TAG}"

TAR_FILE="${SCRIPT_DIR}/${LATEST_TAG}.tar.gz"
TAR_URL="https://ghproxy.net/https://github.com/wangfenjin/simple/archive/refs/tags/${LATEST_TAG}.tar.gz"

if [[ ! -d "${SRC_DIR}" ]]; then
    if [[ -f "${TAR_FILE}" ]]; then
        echo "[Tokenizer] 本地源码包已存在: ${TAR_FILE}，直接解压..."
    else
        echo "[Tokenizer] 本地源码包不存在，开始下载: ${TAR_URL} ..."
        if command -v curl &>/dev/null; then
            curl --http1.1 -L -o "${TAR_FILE}" "${TAR_URL}"
        elif command -v wget &>/dev/null; then
            wget -O "${TAR_FILE}" "${TAR_URL}"
        else
            echo "[ERROR] 未找到 curl 或 wget，无法下载源码包。"
            exit 1
        fi
        echo "[Tokenizer] 下载完成: ${TAR_FILE}"
    fi

    echo "[Tokenizer] 解压源码包..."
    tar -xzf "${TAR_FILE}" -C "${SCRIPT_DIR}"
    mv "${SCRIPT_DIR}/simple-${LATEST_TAG#v}" "${SRC_DIR}"
    echo "[Tokenizer] 源码已解压到: ${SRC_DIR}"
fi

echo "[Tokenizer] 开始编译 simple 分词器扩展..."

# 清理旧构建缓存，防止 CMakeCache 路径冲突
if [[ -d "${BUILD_DIR}" ]]; then
    rm -rf "${BUILD_DIR}"
fi
mkdir -p "${BUILD_DIR}"

# cmake
echo "[Tokenizer] cmake..."
cmake -S "${SRC_DIR}" -B "${BUILD_DIR}" \
    -DSIMPLE_WITH_JIEBA=OFF \
    -DCMAKE_INSTALL_PREFIX="${OUTPUT_DIR}" \
    -DCMAKE_BUILD_TYPE=Release

# make
echo "[Tokenizer] make..."
make -C "${BUILD_DIR}" -j"$(nproc 2>/dev/null || echo 2)"

# install
echo "[Tokenizer] make install..."
make -C "${BUILD_DIR}" install

# 创建软链
COMPILED="${OUTPUT_DIR}/bin/libsimple.so"
if [[ ! -f "${COMPILED}" ]]; then
    echo "[ERROR] 编译后未找到 ${COMPILED}"
    exit 1
fi

if [[ -L "${LIBSIMPLE_LINK}" ]] || [[ -e "${LIBSIMPLE_LINK}" ]]; then
    rm -f "${LIBSIMPLE_LINK}"
fi
ln -s "${COMPILED}" "${LIBSIMPLE_LINK}"

echo "[Tokenizer] 编译完成: ${COMPILED} -> ${LIBSIMPLE_LINK}"
