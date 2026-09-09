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

## 注册

在需要使用本 Agent 的 xlite 项目根目录下执行初始化命令，将 Agent 注册到 opencode：

```bash
npx xlite-opt-init
```

如果 `opencode.jsonc` 中已存在 `xlite-perf-optimizer` 配置但想更新 skill 列表或 prompt 路径，使用：

```bash
npx xlite-opt-init --force
```

`xlite-opt-init` 会：

1. 将 Agent role prompt 安装到 `~/.config/opencode/agents/xlite-perf-optimizer/`。
2. 将 8 个内置 skill 安装到 `~/.config/opencode/skills/`。
3. 在当前项目的 `opencode.jsonc` 中追加/覆盖 `xlite-perf-optimizer` agent 配置。
4. 在当前项目创建 `.xlite-opt/journal/` 和 `.xlite-opt/reports/`。

命令具备幂等语义：agent 配置已存在时默认跳过写入，重复执行不出错。

> 注意：写入 `opencode.jsonc` 前会自动生成带时间戳的 `.bak-XXX` 备份，但回写为纯 JSON 会丢失原有注释（输出中会给出提示）。如需保留注释，请手动合并。

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
