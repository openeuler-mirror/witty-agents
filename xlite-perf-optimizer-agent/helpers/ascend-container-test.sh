#!/usr/bin/env bash
#
# ascend-container-test.sh
# 在昇腾容器内构建本地 xlite 代码并运行 vllm serve 性能测试。
#
# 环境变量：
#   XLITE_IMAGE                基础镜像，默认 quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler
#   XLITE_CONTAINER            容器名，默认 xlite-test
#   XLITE_PROJECT_DIR          本地 xlite 项目目录，默认当前目录
#   XLITE_MODEL_PATH           测试模型路径，默认 /home/models/Qwen3.5-27B
#   XLITE_NPU_DEVICES          NPU 设备路径，默认 /dev/davinci2
#   XLITE_REPORT_DIR           报告输出目录，默认 ./.xlite-opt/reports
#   XLITE_BRANCH               GVirt_2803 分支，默认 xlite/linear-attn-mixed-len
#   XLITE_VLLM_BRANCH          vLLM 分支，默认 releases/v0.26.0
#   XLITE_REUSE_WORKSPACE      是否复用 /workspace 下已克隆的依赖，默认 0
#   XLITE_BENCHMARK_CMD        可选：服务启动后执行的压测命令
#   XLITE_KEEP_CONTAINER       测试结束后是否保留容器，默认 0（删除）
#   XLITE_TEST_TIMEOUT         等待服务启动的最长秒数，默认 120
#

set -euo pipefail

IMAGE="${XLITE_IMAGE:-quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler}"
CONTAINER="${XLITE_CONTAINER:-xlite-test}"
PROJECT_DIR="${XLITE_PROJECT_DIR:-$(pwd)}"
MODEL_PATH="${XLITE_MODEL_PATH:-/home/models/Qwen3.5-27B}"
NPU_DEVICES="${XLITE_NPU_DEVICES:-/dev/davinci2}"
REPORT_DIR="${XLITE_REPORT_DIR:-./.xlite-opt/reports}"
GVIRT_BRANCH="${XLITE_BRANCH:-xlite/linear-attn-mixed-len}"
VLLM_BRANCH="${XLITE_VLLM_BRANCH:-releases/v0.26.0}"
REUSE_WORKSPACE="${XLITE_REUSE_WORKSPACE:-0}"
BENCHMARK_CMD="${XLITE_BENCHMARK_CMD:-}"
KEEP_CONTAINER="${XLITE_KEEP_CONTAINER:-0}"
TEST_TIMEOUT="${XLITE_TEST_TIMEOUT:-120}"

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$REPORT_DIR"

echo "[xlite-ascend-runner] 镜像: $IMAGE"
echo "[xlite-ascend-runner] 容器: $CONTAINER"
echo "[xlite-ascend-runner] 本地代码: $PROJECT_DIR"
echo "[xlite-ascend-runner] 模型: $MODEL_PATH"
echo "[xlite-ascend-runner] 复用 workspace: $REUSE_WORKSPACE"
echo "[xlite-ascend-runner] 保留容器: $KEEP_CONTAINER"
echo "[xlite-ascend-runner] 压测命令: ${BENCHMARK_CMD:-<未配置>}"

# 1. 若容器已存在则停止并删除旧容器，保证干净
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[xlite-ascend-runner] 发现旧容器 ${CONTAINER}，正在清理..."
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm "$CONTAINER" >/dev/null 2>&1 || true
fi

# 2. 创建并启动容器
docker run -d --name "$CONTAINER" \
    --shm-size=1g --privileged \
    --device "$NPU_DEVICES" \
    --device /dev/davinci_manager \
    --device /dev/devmm_svm \
    --device /dev/hisi_hdc \
    -v /usr/local/dcmi:/usr/local/dcmi \
    -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
    -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
    -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
    -v /etc/ascend_install.info:/etc/ascend_install.info \
    -v /root/.cache:/root/.cache \
    -v "$PROJECT_DIR:/workspace/xlite-local:ro" \
    --net host \
    "$IMAGE" \
    sleep infinity

# 3. 容器内环境准备与测试
docker exec -i "$CONTAINER" bash -s <<EOF
set -euo pipefail

WORKSPACE=/workspace
REUSE=${REUSE_WORKSPACE}

# 卸载旧 vllm
pip uninstall -y vllm vllm_ascend || true

# 克隆/复用依赖
if [ "\$REUSE" = "1" ] && [ -d "\$WORKSPACE/vllm/.git" ]; then
    echo "[inside container] 复用已克隆的 vllm"
else
    rm -rf "\$WORKSPACE/vllm"
    git clone --depth 1 --branch "$VLLM_BRANCH" https://github.com/vllm-project/vllm.git "\$WORKSPACE/vllm"
fi

if [ "\$REUSE" = "1" ] && [ -d "\$WORKSPACE/vllm-ascend/.git" ]; then
    echo "[inside container] 复用已克隆的 vllm-ascend"
else
    rm -rf "\$WORKSPACE/vllm-ascend"
    git clone --depth 1 https://github.com/zd1204/vllm-ascend.git "\$WORKSPACE/vllm-ascend"
fi

# 安装 vllm
cd "\$WORKSPACE/vllm"
pip install setuptools_rust
VLLM_TARGET_DEVICE=empty pip install -v -e . --no-build-isolation

# 安装 vllm-ascend
cd "\$WORKSPACE/vllm-ascend"
pip install --trusted-host mirror.huaweicloud.com \
    --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
    -v -e . --no-build-isolation --no-deps

# 克隆/复用 GVirt_2803 并注入本地 xlite 代码
if [ "\$REUSE" = "1" ] && [ -d "\$WORKSPACE/GVirt_2803/.git" ]; then
    echo "[inside container] 复用已克隆的 GVirt_2803"
    cd "\$WORKSPACE/GVirt_2803"
    git fetch origin "$GVIRT_BRANCH" || true
    git checkout "$GVIRT_BRANCH" || true
else
    rm -rf "\$WORKSPACE/GVirt_2803"
    git clone --depth 1 --branch "$GVIRT_BRANCH" https://gitcode.com/zhoudong01/GVirt_2803.git "\$WORKSPACE/GVirt_2803"
    cd "\$WORKSPACE/GVirt_2803"
fi

rm -rf "\$WORKSPACE/GVirt_2803/xlite"
cp -r /workspace/xlite-local "\$WORKSPACE/GVirt_2803/xlite"

# 安装 xlite
cd "\$WORKSPACE/GVirt_2803/xlite"
pip install -v -e .[dev] --no-build-isolation

# 安装 transformers
pip install transformers==5.14.1 \
    -i https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com

# 运行 vllm serve 并后台记录日志
nohup vllm serve "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --dtype bfloat16 \
    --block-size 128 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 8192 \
    --max-num-seqs 4 \
    --additional-config '{"xlite_graph_config": {"enabled": true, "full_mode": true}}' \
    > /workspace/xlite-test.log 2>&1 &

# 等待服务启动（简单轮询端口）
echo "[inside container] 等待 vllm serve 启动，最长 ${TEST_TIMEOUT}s..."
ready=0
for i in \$(seq 1 ${TEST_TIMEOUT}); do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "[inside container] vllm serve 已就绪"
        ready=1
        break
    fi
    sleep 1
done

if [ "\$ready" != "1" ]; then
    echo "[inside container] 错误：vllm serve 在 ${TEST_TIMEOUT}s 内未就绪，请检查 /workspace/xlite-test.log"
    exit 1
fi

# 可选：执行自定义压测命令
if [ -n "${BENCHMARK_CMD}" ]; then
    echo "[inside container] 执行压测命令..."
    set +e
    eval "${BENCHMARK_CMD}" | tee /workspace/xlite-benchmark.log 2>&1
    set -e
else
    echo "[inside container] 未配置 XLITE_BENCHMARK_CMD，跳过主动压测"
    echo "[inside container] vllm serve 日志：/workspace/xlite-test.log"
fi

EOF

# 4. 收集日志
docker cp "$CONTAINER:/workspace/xlite-test.log" "$REPORT_DIR/ascend-test-${TS}.log" || true
docker cp "$CONTAINER:/workspace/xlite-benchmark.log" "$REPORT_DIR/ascend-benchmark-${TS}.log" || true

# 5. 解析指标
METRICS_FILE="$REPORT_DIR/ascend-test-${TS}.json"
if [ -f "$REPORT_DIR/ascend-test-${TS}.log" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$(cd "$(dirname "$0")" && pwd)/parse-perf-log.py" \
        "$REPORT_DIR/ascend-test-${TS}.log" \
        -o "$METRICS_FILE" || true
else
    cat > "$METRICS_FILE" <<EOF
{
  "timestamp": "$TS",
  "container": "$CONTAINER",
  "image": "$IMAGE",
  "model": "$MODEL_PATH",
  "log": "$REPORT_DIR/ascend-test-${TS}.log",
  "metrics": {
    "wall_ms": null,
    "tpot_ms_per_token": null,
    "throughput_tokens_per_s": null
  },
  "note": "请根据日志中的实际输出填写 metrics。"
}
EOF
fi

# 6. 清理容器（可选）
if [ "$KEEP_CONTAINER" != "1" ]; then
    echo "[xlite-ascend-runner] 测试结束，清理容器 ${CONTAINER}..."
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm "$CONTAINER" >/dev/null 2>&1 || true
fi

echo "[xlite-ascend-runner] 测试日志: $REPORT_DIR/ascend-test-${TS}.log"
echo "[xlite-ascend-runner] 指标文件: $METRICS_FILE"
[ -f "$REPORT_DIR/ascend-benchmark-${TS}.log" ] && echo "[xlite-ascend-runner] 压测日志: $REPORT_DIR/ascend-benchmark-${TS}.log"
