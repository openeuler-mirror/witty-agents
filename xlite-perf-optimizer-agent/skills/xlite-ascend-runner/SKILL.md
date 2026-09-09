# xlite-ascend-runner

## 用途

在昇腾 NPU 容器内自动构建本地 xlite 代码并运行性能测试，输出测试结果。

支持两种运行形态：

1. **本地代码构建容器**（默认）：拉取昇腾基础镜像，创建容器，在容器内克隆依赖仓库并注入本地代码，编译运行。
2. **复用已有容器**：连接用户已经启动的昇腾容器，直接执行构建/测试。

## 何时使用

- `[xlite-operator-dev]` 完成代码修改后。
- 用户需要验证性能时。
- `XLITE_TEST_MODE` 为 `container_build` 或 `container_reuse` 时。

## 输入

- 本地 xlite 项目目录（默认当前工作目录）。
- `XLITE_TEST_MODE`：`container_build`（默认）/ `container_reuse`。
- `XLITE_TEST_CONTAINER`：已有容器名（仅 `container_reuse` 模式需要，默认 `auto`）。
- `XLITE_IMAGE`：基础镜像（默认 `quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler`）。
- `XLITE_NPU_DEVICES`：NPU 设备（默认 `/dev/davinci2`）。
- `XLITE_MODEL_PATH`：测试模型路径（默认 `/home/models/Qwen3.5-27B`）。

## 输出

- `.xlite-opt/reports/ascend-test-<ts>.log`
- `.xlite-opt/reports/ascend-test-<ts>.json`

## 执行步骤

### 快速执行

本 Agent 提供了辅助脚本，可直接调用：

```bash
bash node_modules/xlite-perf-optimizer/helpers/ascend-container-test.sh
```

脚本会根据环境变量自动完成：镜像检查、容器创建、依赖安装、本地代码注入、编译、启动服务、日志回传。

也可以分步手动执行以下命令：

#### 1. 检查镜像

```bash
docker pull ${XLITE_IMAGE}
```

#### 2. 创建并启动容器

使用默认镜像与设备映射：

```bash
docker run -d --name xlite-test \
  --shm-size=1g --privileged \
  --device ${XLITE_NPU_DEVICES} \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  -v /root/.cache:/root/.cache \
  -v ${PROJECT_DIR}:/workspace/xlite-local \
  --net host \
  ${XLITE_IMAGE} \
  sleep infinity
```

#### 3. 容器内环境准备

在容器内执行：

```bash
pip uninstall -y vllm vllm_ascend || true

git clone https://github.com/vllm-project/vllm.git -b releases/v0.26.0 /workspace/vllm
git clone https://github.com/zd1204/vllm-ascend.git /workspace/vllm-ascend
cd /workspace/vllm
pip install setuptools_rust
VLLM_TARGET_DEVICE=empty pip install -v -e . --no-build-isolation
cd /workspace/vllm-ascend
pip install --trusted-host mirror.huaweicloud.com \
  --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
  -v -e . --no-build-isolation --no-deps

# 注入本地 xlite 代码
git clone https://gitcode.com/zhoudong01/GVirt_2803.git /workspace/GVirt_2803
cd /workspace/GVirt_2803
git checkout xlite/linear-attn-mixed-len
rm -rf xlite
cp -r /workspace/xlite-local /workspace/GVirt_2803/xlite
cd xlite
pip install -v -e .[dev] --no-build-isolation

pip install transformers==5.14.1 \
  -i https://mirrors.aliyun.com/pypi/simple \
  --trusted-host mirrors.aliyun.com
```

#### 4. 运行性能测试

```bash
docker exec xlite-test bash -c "
  cd /workspace/GVirt_2803/xlite &&
  vllm serve ${XLITE_MODEL_PATH} \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --dtype bfloat16 \
    --block-size 128 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 8192 \
    --max-num-seqs 4 \
    --additional-config '{\"xlite_graph_config\": {\"enabled\": true, \"full_mode\": true}}' \
    > /workspace/xlite-test.log 2>&1 &
  sleep 60
  # 这里替换为具体的性能压测命令，例如 curl / benchmark_serving
  echo '测试完成'
"
```

#### 5. 收集结果

```bash
docker cp xlite-test:/workspace/xlite-test.log .xlite-opt/reports/ascend-test-<ts>.log
docker cp xlite-test:/workspace/GVirt_2803/xlite/tests/perf-result.json .xlite-opt/reports/ascend-test-<ts>.json || true
```

### 模式二：复用已有容器

若 `XLITE_TEST_MODE=container_reuse`：

1. 自动识别：`docker ps` 匹配包含 `ascend` / `npu` / `cann` / `openeuler` 的容器。
2. 或直接使用 `XLITE_TEST_CONTAINER` 指定的容器名。
3. 在该容器内执行构建与测试（容器内路径通过 `XLITE_CONTAINER_WORKDIR` 指定）。

## 结果解析

从日志中提取：

- `wall(ms)`：端到端单步耗时
- `tpot(ms/token)`：每个输出 token 的耗时
- `throughput(tokens/s)`：吞吐
- 各算子 `self(ms)` 与 `per_call(ms)`

输出到 `.xlite-opt/reports/ascend-test-<ts>.json`。

## 工具

- `Bash`：`docker pull`、`docker run`、`docker exec`、`docker cp`、日志解析。

## 环境变量

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `XLITE_TEST_MODE` | `container_build` | `container_build` / `container_reuse` / `gitcode` |
| `XLITE_TEST_CONTAINER` | `auto` | 已有容器名（`container_reuse` 模式） |
| `XLITE_IMAGE` | `quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler` | 基础镜像 |
| `XLITE_NPU_DEVICES` | `/dev/davinci2` | NPU 设备路径 |
| `XLITE_MODEL_PATH` | `/home/models/Qwen3.5-27B` | 测试模型路径 |
| `XLITE_CONTAINER_WORKDIR` | `/workspace/GVirt_2803/xlite` | 容器内 xlite 路径 |
| `XLITE_TEST_TIMEOUT` | `300` | 测试超时（秒） |

## 注意事项

- 执行 `docker run` / `docker exec` 前在摘要中显式说明命令。
- 容器内网络需可访问 GitHub / GitCode / PyPI 镜像。
- 若本地已存在 `xlite-test` 容器，先停止并删除，或修改 `XLITE_TEST_CONTAINER` 名称。
- 测试结果依赖真实 NPU 环境；无 NPU 时自动降级到 `[xlite-gitcode-runner]` 模式。
