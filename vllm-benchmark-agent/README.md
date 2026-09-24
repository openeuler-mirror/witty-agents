# vLLM Benchmark Agent

Ascend vLLM 配置驱动压测 Agent。自动检查环境、启动已有容器中的 vLLM、复用匹配服务、扫描并发或 QPS、采集指标，生成 JSON 分析和 PNG 性能图；支持任务恢复、取消和每张 NPU 的独立锁。

## 安装前提

需要 Linux、Node.js 20+、npm 10+、Python 3.10+（包含 venv/pip，或已安装 virtualenv）。运行压测另需可访问的 Docker/Podman、已有 Ascend 容器及其中的 vLLM、模型和 npu-smi。setup 不创建容器、不安装驱动、不启动压测服务。

## 线上安装（npm）

从 npm 官方 registry 安装：

```bash
npm install -g witty-agent-vllm-benchmark-online@0.1.0 --registry=https://registry.npmjs.org
vllm-benchmark-setup install
vllm-benchmark-configure install --target=opencode
```

也可以省略 `@0.1.0` 安装 latest 版本。包名为 `witty-agent-vllm-benchmark-online`。
重启 OpenCode 后选择 `vllm-benchmark`；`benchmark-config` 和 `/benchmark_config` 用于编辑配置。

## 线下安装（本地 tgz）

拿到 `witty-agent-vllm-benchmark-online-0.1.0.tgz` 后，从文件安装：

```bash
npm install -g ./witty-agent-vllm-benchmark-online-0.1.0.tgz
vllm-benchmark-setup install
vllm-benchmark-configure install --target=opencode
```

可以在联网机器上下载 npm 中同版本的包，再传输到目标机器：

```bash
npm pack witty-agent-vllm-benchmark-online@0.1.0 --registry=https://registry.npmjs.org
```

也可以从 witty-agents 源码构建 tgz：

```bash
cd witty-agents/vllm-benchmark-agent
npm ci
npm run validate
npm run pack:variant -- --variant=online --package-style=plain
npm install -g ./artifacts/witty-agent-vllm-benchmark-online-0.1.0.tgz
vllm-benchmark-setup install
vllm-benchmark-configure install --target=opencode
```

本地 tgz 安装仍需要获取 npm 依赖，setup 仍需要获取 Python 依赖；当前不提供完全断网安装包。目标机器必须能够访问相应依赖源，或已配置可用的内网镜像。`PYPI_INDEX_URL` 可指定 Python 依赖镜像。

两种安装方式遵循相同的 Witty 安装契约：普通 npm 安装没有 postinstall；setup 创建独立 Python venv 并安装 requirements.txt；configure 幂等注册 `file://.../dist/index.js` 和 Skill 软链，保留 JSONC 注释及其他配置，修改前自动备份。

源码开发可用 `node bin/vllm-benchmark-setup.mjs install`，然后 `node bin/vllm-benchmark.mjs config`；setup 支持 `PYTHON_BIN`、`PYPI_INDEX_URL` 和 `VLLM_BENCHMARK_VENV`。

## 使用

复制包内 `benchmark.yaml` 到工作目录，填写模型路径、已有容器名、物理 NPU 编号和压测参数。示例中的模型路径是占位值。默认读取当前工作目录的配置，支持 `VLLM_BENCHMARK_CONFIG` 或显式 `--config PATH`。

全局安装后，在准备存放配置的工作目录执行以下命令复制模板（已有配置时不覆盖）：

```bash
cp -n "$(npm root -g)/witty-agent-vllm-benchmark-online/benchmark.yaml" ./benchmark.yaml
# 编辑 benchmark.yaml，填写真实环境后再运行
vllm-benchmark config
vllm-benchmark run
vllm-benchmark watch --once
vllm-benchmark resume
# 分析 ANALYZE 返回的 llm_prompt 后结束任务，清理本任务启动的服务
vllm-benchmark done
```

用户要求按 YAML 运行即启动正常流程；仅阻塞异常要求用户决定。配置在任务开始时冻结，`resume --reload-config` 显式读取新配置；`--retry-round` 重跑缺失指标的轮次，`--accept-partial` 接受不完整指标。复用的已有服务不会在 done 时停止。

运行数据默认写入 `${XDG_DATA_HOME:-~/.local/share}/witty-agents/vllm-benchmark/`，可用 `VLLM_BENCHMARK_DATA_DIR` 覆盖；包含 state、runs、locks、reports。相对 report.output 以数据目录为基准。工作目录及用户主目录的 `.vllm-benchmark/current.json` 供 TUI 发现活动任务，不写入安装目录。

`tui/vllm-benchmark-view/` 保留原独立 OpenCode TUI 扩展源码及锁文件。它依赖原 TUI API，作为可选开发组件保留，当前标准 npm 包不自动安装或注册该扩展。

## 检查与卸载

```bash
vllm-benchmark-setup check
vllm-benchmark-configure status
# 活动任务需要时先执行 cancel；不会自动停止其他用户服务
vllm-benchmark-configure remove --target=opencode
npm uninstall -g witty-agent-vllm-benchmark-online
```

虚拟环境默认位于 `${XDG_CACHE_HOME:-~/.cache}/witty-agents/vllm-benchmark/venv`。
卸载保留缓存、配置备份及运行报告；需要时用户自行清理。`VLLM_BENCHMARK_OPENCODE_CONFIG` 可指定注册配置文件，否则使用 XDG_CONFIG_HOME 下的 `opencode/opencode.jsonc`。

## 验证和 CI

```bash
npm ci
node bin/vllm-benchmark-setup.mjs install
npm run validate
npm test
npm run pack:variant -- --variant=online --package-style=organization
npm run ci:verify-artifacts -- --variants=online --package-style=organization
npm run test:install-contract
RUN_REAL_INSTALL_VALIDATION=true node ci/driver.mjs --phase=real-install --variants=online
```

仓库 `ci/agents.json` 注册 ID `vllm-benchmark`，使用统一 Jenkinsfile。支持 organization/plain 两种命名风格；当前仅支持 online，离线 Python wheel 闭包尚未实现，offline 请求会失败。安装验证在临时 HOME 下测试真实 tgz 安装、setup、configure/remove 幂等、JSONC 保留和 npm 卸载，不执行硬件压测。

从原独立项目迁移时，源项目和已有运行数据保留。原配置可通过 `--config /原项目/benchmark.yaml` 继续使用；已有任务需将 VLLM_BENCHMARK_DATA_DIR 指向原数据目录。代码树内更早的 `.benchmark/`/reports 数据，请在原项目使用其 `migrate-data` 命令迁移。

## 发布到 npm（维护者）

在 Agent 目录构建并验证普通命名的在线包，然后发布生成的 tgz：

```bash
npm ci
npm run validate
npm run pack:variant -- --variant=online --package-style=plain
npm run ci:verify-artifacts -- --variants=online --package-style=plain
npm run test:install-contract
npm login --registry=https://registry.npmjs.org
npm publish ./artifacts/witty-agent-vllm-benchmark-online-0.1.0.tgz --access=public --tag=latest --registry=https://registry.npmjs.org
```

源码 package.json 的名称用于组织构建；线上安装使用上述 tgz 内的普通包名。
发布后用 `npm view witty-agent-vllm-benchmark-online@0.1.0 dist.integrity --registry=https://registry.npmjs.org` 检查发布结果。
