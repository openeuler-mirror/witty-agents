# xlite-perf-optimizer-agent

一个可 npm 安装的 opencode 自定义 Agent（prompt 注册型），用于自动化 xlite 性能优化。

npm 包名：`@openeuler/agent-xlite-perf-optimizer`

## 功能

- 自动分析 xlite 算子 profiling 数据，识别**算子级与流程级**瓶颈。
- 设计并修改推理逻辑 / AscendC 算子 / C++ 管线 / Python 模型适配。
- 基于 `(input_tokens, output_tokens, batch_size)` 估算单算子及端到端时间复杂度。
- 自动配置时间打点、聚合统计、输出 JSON/CSV/Markdown/静态 HTML 报告。
- 本地代码构建昇腾容器（默认镜像 `quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler`）或复用已有容器进行测试。
- 支持 GitCode 远端测试模式：推送分支后用户反馈结果，Agent 自动解析。
- 每次原子修改生成 patch，测试失败则自动回滚。

## 安装

online 包（npm registry）：

```bash
npm install @openeuler/agent-xlite-perf-optimizer
```

offline 包：本 Agent 未声明 `witty.offlineExtras`，全部内容（prompt / skills / helpers）均在 online 包内自足，无独立 offline 变体；离线环境可将 online 包导出 tgz 携带转移：

```bash
npm pack @openeuler/agent-xlite-perf-optimizer   # 在有网环境导出 tgz
npm install openeuler-agent-xlite-perf-optimizer-<version>.tgz   # 拷贝到离线机后安装
```

> 安装过程（`postinstall`）只打印下一步提示，不创建 venv、不改写任何配置、不联网下载。

## 注册（统一双命令）

四个 Agent 统一为 `<agent>-setup` + `<agent>-configure` 两个命令。本 Agent 无 Python / 后端依赖，Skills 随包内置：

```bash
xlite-perf-optimizer-setup install                        # no-op：校验包完整性
xlite-perf-optimizer-configure install --target=opencode  # plugin 注册 + 软链 8 个 skill
```

`configure install` 会：

1. 在 `~/.config/opencode/opencode.jsonc` 的 `plugin` 数组注册本包 `dist/index.js`（幂等）。
2. 将 8 个内置 skill 以**符号链接**链到 `~/.config/opencode/skills/`（不复制实体文件）。

命令幂等可重复执行；改写配置前会自动生成带时间戳的备份并保留 JSONC 注释。
反注册使用 `xlite-perf-optimizer-configure remove`，状态查看 `xlite-perf-optimizer-configure status`。

> 旧版 `xlite-opt-init`（复制实体文件 + 写项目 `opencode.jsonc` 的引导方式）已移除，请改用上面的 plugin 注册流程；旧残留的清理方式见 witty-agents 仓库 `docs/agents-install-uninstall-guide.md` 卸载章节。

## 验证

初始化完成后，在 opencode 中选择 `xlite-perf-optimizer` agent，然后直接输入优化任务，例如：

```text
优化 Qwen3.5-27B decode 阶段的 Conv1dAndSiLU，目标让 xlite full_mode 比 native graph 快 10%。
```

Agent 会自动执行分析、设计、修改、测试、报告生成与保留/回滚。

也可以在项目内运行结构自检，确保 agent 与 skill 文件完整：

```bash
node node_modules/@openeuler/agent-xlite-perf-optimizer/scripts/smoke-test.js
```

## 环境变量

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `XLITE_TEST_MODE` | `container_build` | 测试模式：`container_build` / `container_reuse` / `gitcode` |
| `XLITE_TEST_CONTAINER` | `auto` | 昇腾容器名；`auto` 时自动识别（`container_reuse` 模式） |
| `XLITE_IMAGE` | `quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler` | 基础镜像（`container_build` 模式） |
| `XLITE_NPU_DEVICES` | `/dev/davinci2` | NPU 设备路径 |
| `XLITE_MODEL_PATH` | `/home/models/Qwen3.5-27B` | 测试模型路径 |
| `XLITE_PROFILING_ENABLED` | `true` | 是否自动开启时间打点 |
| `XLITE_ATOMIC_JOURNAL_DIR` | `.xlite-opt/journal` | 原子修改记录目录 |
| `XLITE_REPORT_DIR` | `.xlite-opt/reports` | HTML/JSON 报告输出目录 |
| `XLITE_TEST_TIMEOUT` | `300` | 昇腾容器内单次测试超时（秒） |
| `XLITE_MAX_ROLLBACK` | `10` | 保留的最大回滚记录数 |

## 辅助脚本

本包提供了可直接调用的辅助脚本：

| 脚本 | 路径 | 说明 |
|------|------|------|
| `ascend-container-test.sh` | `helpers/ascend-container-test.sh` | 一键在昇腾容器内构建本地 xlite 代码并启动 `vllm serve`，最后回传日志与指标占位 JSON。 |
| `parse-perf-log.py` | `helpers/parse-perf-log.py` | 解析性能日志，自动提取 wall time、TPOT、throughput、p50/p99，输出 JSON。 |

示例：

```bash
# 昇腾容器测试
bash node_modules/@openeuler/agent-xlite-perf-optimizer/helpers/ascend-container-test.sh

# 解析日志
python3 node_modules/@openeuler/agent-xlite-perf-optimizer/helpers/parse-perf-log.py \
  .xlite-opt/reports/ascend-test-<ts>.log \
  -o .xlite-opt/reports/metrics-<ts>.json
```

## 项目级原子记录

每次 Agent 修改代码前都会保存 patch，记录位于：

```text
.xlite-opt/
├── journal/          # 原子修改记录
└── reports/          # HTML/JSON 性能报告
```

你可以随时要求 Agent `show journal` 或 `rollback last`。
