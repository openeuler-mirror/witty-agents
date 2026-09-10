# xlite-perf-optimizer Agent 设计文档

> 日期：2026-08-16  
> 状态：待实现  
> 目标：为 xlite 项目提供一个可 npm 安装的 opencode 自定义 Agent，自动化完成性能分析、算子/推理逻辑优化、测试验证、结果展示与原子回滚。

---

## 1. 背景与目标

### 1.1 背景

当前 xlite 在 Qwen3.5-27B 等模型上存在明显性能瓶颈（如 `Conv1dAndSiLU` 在 decode 场景下单次 0.258ms，远高于其他算子）。优化工作需要反复进行：

1. 分析 profiling 数据；
2. 设计推理逻辑/算子优化方案；
3. 修改 AscendC 算子或 C++/Python 管线；
4. 配置时间打点并跑测试；
5. 在昇腾容器内验证性能；
6. 对比测试结果并决定保留或回退。

这一系列工作重复且专业性强，需要一个自动化的 Agent 来承担。

### 1.2 目标

交付一个 **可通过 npm 安装到项目级** 的 opencode 自定义 Agent，名为 `xlite-perf-optimizer`。它应具备以下能力：

- **推理逻辑设计**：根据当前 xlite 代码结构，设计更优的 forward/attention/MLP 流程。
- **算子开发/优化**：编写或改写 AscendC 算子、C++ 管线、Python 模型适配代码。
- **可配置时间打点**：自动开启/关闭 xlite 内部时间打点，聚合统计并输出结果。
- **测试结果输出**：输出结构化结果（JSON/CSV/Markdown）和静态 HTML 报告。
- **时间复杂度估计**：基于输入 token 数、输出 token 数、batch size，估算单算子及端到端 latency。
- **昇腾容器测试**：本地代码构建/复用昇腾容器（默认镜像 `quay.io/ascend/vllm-ascend:v0.23.0rc1-openeuler`）自动运行并收集结果。
- **GitCode 远端测试**：推送分支到 GitCode，用户反馈结果后自动解析。
- **原子修改回滚**：每次原子修改生成 patch 记录，测试不通过则自动回退。
- **Skill 打包**：所需 skill 全部随 Agent 一起发布，不依赖运行时从 skillhub 安装。

---

## 2. 范围与非目标

### 2.1 范围（In Scope）

- 仅修改 xlite 相关代码：`csrc/`、`xlite/`、`tests/`、`doc/` 中的优化相关内容。
- 支持 Qwen3.5 及其类似的 hybrid attention / linear attention 模型优化。
- 支持 decode 路径优化、prefill 路径优化、以及通过配置切换的 profiling。
- 生成项目级可读的 HTML 性能报告。
- 通过 `npm install xlite-perf-optimizer` 安装并在当前项目初始化 Agent。

### 2.2 非目标（Out of Scope）

- 不修改 vllm/vllm-ascend 核心代码（除非 xlite 接口需要）。
- 不支持跨项目的全局安装（项目级安装可复现、可隔离）。
- 不直接操作生产环境；所有测试默认在昇腾容器/沙箱内执行。
- 不替代人工代码审查，Agent 只负责生成可验证的优化补丁。

---

## 3. Agent 配置

### 3.1 opencode agent 注册

安装后，项目 `opencode.jsonc` 中应新增：

```jsonc
{
  "agent": {
    "xlite-perf-optimizer": {
      "description": "xlite 性能优化专家 — 自动分析算子瓶颈、设计并实现优化、在昇腾容器内验证、生成 HTML 报告并支持原子回退",
      "prompt": "{file:.opencode/agents/xlite-perf-optimizer/agent.md}",
      "skills": [
        "xlite-analyzer",
        "xlite-complexity-estimator",
        "xlite-operator-dev",
        "xlite-atomic-journal",
        "xlite-profiler",
        "xlite-ascend-runner",
        "xlite-gitcode-runner",
        "xlite-html-reporter"
      ]
    }
  }
}
```

### 3.2 环境变量

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `XLITE_TEST_CONTAINER` | `auto` | 昇腾容器名；`auto` 时 Agent 自动识别 |
| `XLITE_PROFILING_ENABLED` | `true` | 是否自动开启时间打点 |
| `XLITE_ATOMIC_JOURNAL_DIR` | `.xlite-opt/journal` | 原子修改记录目录 |
| `XLITE_REPORT_DIR` | `.xlite-opt/reports` | HTML/JSON 报告输出目录 |
| `XLITE_TEST_TIMEOUT` | `300` | 昇腾容器内单次测试超时（秒） |
| `XLITE_MAX_ROLLBACK` | `10` | 保留的最大回滚记录数 |

---

## 4. Role Prompt（agent.md）

`agent.md` 是 Agent 的核心角色提示，定义其身份、工作流、约束和输出格式。

### 4.1 身份

```text
你是 xlite-perf-optimizer，一名专注于昇腾 xlite 推理框架性能优化的专家 Agent。
你的任务是在收到用户给出的性能优化目标后，自动分析 xlite 代码与 profiling 数据，
设计并实现推理逻辑/算子层面的优化，在昇腾容器内验证效果，并生成可视化报告。

你只能修改 xlite 直接相关的代码，包括：
- csrc/ 下的 AscendC/C++ 算子与管线
- xlite/ 下的 Python 封装与工具
- tests/ 下的测试用例与性能脚本
- doc/ 下的设计/性能文档
```

### 4.2 工作流

```text
收到任务后，请按以下顺序执行：

1. [xlite-analyzer] 收集上下文：读取 profiling 数据、当前 xlite 源码、模型配置，识别瓶颈算子。
2. [xlite-complexity-estimator] 根据用户提供的 (input_tokens, output_tokens, batch_size) 估算当前代码的时间复杂度。
3. [xlite-operator-dev] 设计优化方案并生成实现；每次修改前先调用 [xlite-atomic-journal] 保存 before/after patch。
4. [xlite-profiler] 配置时间打点与聚合统计。
5. [xlite-ascend-runner] 在昇腾容器内编译并运行测试；自动识别容器名（如 XLITE_TEST_CONTAINER=auto）。
6. [xlite-html-reporter] 生成静态 HTML 报告，包含优化前后对比、复杂度估计、原子修改记录。
7. 根据测试结果决定保留或回退：性能提升则保留，否则调用 [xlite-atomic-journal] 回退本次修改。
```

### 4.3 约束

```text
- 每次只做一个原子改动，改动范围尽量小。
- 修改前必须保存 patch；修改后必须跑测试。
- 测试失败或性能退化必须回退，并向用户说明原因。
- 不执行 git commit/push/reset/rebase 等变更仓库历史的行为。
- 所有危险操作（如 rm、docker exec 外部命令）必须显式在摘要中说明。
- 输出必须包含：当前状态、修改文件列表、测试结果、HTML 报告路径。
```

### 4.4 输出格式

```text
每次迭代返回：

## 迭代摘要
- 目标：...
- 修改文件：...
- 测试命令：...
- 性能变化：wall X ms → Y ms (-Z%)
- 原子记录：.xlite-opt/journal/YYYYMMDDHHMMSS-xxx/
- HTML 报告：.xlite-opt/reports/report-YYYYMMDDHHMMSS.html
- 状态：kept / rolled_back
- 下一步建议：...
```

---

## 5. Skill 分解

所有 skill 安装到全局 `~/.config/opencode/skills/` 目录，按名字加载；项目级只保留 `agent.md` 和 agent 配置片段。

### 5.1 xlite-analyzer

**职责**：
- 读取 xlite 源码、profiling 数据、模型配置。
- 识别性能瓶颈算子、冗余搬运、可融合链路。
- 输出结构化的瓶颈分析报告。

**输入**：
- 项目路径、profiling 文件路径或最近一次运行结果。

**输出**：
- `bottleneck_report.json`：算子名、self 时间、占比、调用次数、单次耗时。
- `optimization_candidates.md`：候选优化项与预期收益。

### 5.2 xlite-complexity-estimator

**职责**：
- 基于当前代码结构，建立单算子时间复杂度模型。
- 建立端到端 latency 公式。
- 根据 `(input_tokens, output_tokens, batch_size)` 估算总耗时。

**复杂度模型示例**：

```text
# 单算子
Conv1dAndSiLU(seqlen=S, batch=B, channels=C, kernel=K) ~ O(B * C * (S + K))
RecurrentGatedDeltaRule(...) ~ O(B * H * S * kDim * vDim)

# 端到端 decode 单步
T_total = sum over layers (
    T_attn_layer + T_ffn_layer + T_norm_add
)
T_attn_linear = T_in_proj + T_conv + T_l2norm + T_expand + T_gdr + T_gate + T_out_proj
T_attn_mha = T_qkv_proj + T_rope + T_flashattn + T_out_proj + T_gate
```

**输出**：
- `complexity_report.json`：各算子理论耗时、端到端估计、与实际 profiling 偏差。

### 5.3 xlite-operator-dev

**职责**：
- 编写/修改 AscendC 算子（`.h`/`.cpp`）。
- 修改 `csrc/model.cpp` 等管线逻辑。
- 修改 `tests/models/*.py` 或 `tests/kernels/*.py` 测试用例。
- 生成单算子测试与端到端测试命令。

**输入**：
- 优化目标（如“实现 decode 特化 Conv1dAndSiLU”）。

**输出**：
- 修改后的源码文件。
- 新增/更新的测试文件。
- 构建与运行指令。

### 5.4 xlite-atomic-journal

**职责**：
- 在每次原子修改前保存 `before.patch`。
- 修改后保存 `after.patch` 与修改说明。
- 根据测试结果标记 `kept` 或 `rolled_back`。
- 支持 `rollback last`、`rollback <id>`、`show journal`。

**目录结构**：

```text
.xlite-opt/
├── journal/
│   └── 20260816-143052-conv-decode/
│       ├── before.patch
│       ├── after.patch
│       ├── description.md
│       ├── test-result.json
│       └── status.json        # kept / rolled_back
└── reports/
    └── report-20260816-143052.html
```

### 5.5 xlite-profiler

**职责**：
- 配置 `XLITE_DEBUG_ON` 编译选项（如 `forward`）。
- 在 C++ 代码中插入/移除时间打点宏（可选）。
- 解析 xlite 输出日志，聚合算子耗时。
- 输出 `profile.json` / `profile.csv`。

**可配置项**：
- 是否开启 per-op 打点。
- 聚合维度：按算子名、按层、按阶段（prefill/decode）。
- 输出格式。

### 5.6 xlite-ascend-runner

**职责**：
- 自动识别昇腾容器（`docker ps` 中带有 `ascend` / `npu` / `cann` 等标签的容器）。
- 在容器内执行编译、安装、运行测试。
- 收集 stdout/stderr 和性能数据。

**容器发现逻辑**：

```text
1. 若 XLITE_TEST_CONTAINER 为具体容器名，直接使用。
2. 若为 auto：
   a. 执行 docker ps --format '{{.Names}} {{.Image}}'。
   b. 匹配包含 ascend / npu / cann / openeuler 镜像名的容器。
   c. 若存在多个，选择名字最短的或最近启动的。
   d. 若无匹配，报错并提示用户手动设置 XLITE_TEST_CONTAINER。
```

**执行的典型命令**：

```bash
docker exec -it <container> bash -c \
  "cd /path/to/xlite && cmake -B build && cmake --build build -j && cd tests && python run_perf.sh"
```

### 5.7 xlite-html-reporter

**职责**：
- 读取 profiling 结果、复杂度估计、原子修改记录。
- 渲染为静态 HTML 报告。

**报告内容**：

1. 任务概述与优化目标。
2. 当前瓶颈算子表格（self 时间、占比、单次耗时）。
3. 优化前后性能对比（wall/tpot/throughput）。
4. 时间复杂度估计结果（单算子 + 端到端）。
5. 原子修改记录与状态（kept/rolled_back）。
6. 关键代码片段与说明。
7. 结论与下一步建议。


---

## 6. 原子修改与回滚流程

```text
开始优化任务
    │
    ▼
[确定修改范围]
    │
    ▼
[xlite-atomic-journal] 生成 before.patch
    │
    ▼
[xlite-operator-dev] 修改源码
    │
    ▼
[xlite-atomic-journal] 生成 after.patch
    │
    ▼
[xlite-profiler] 开启打点
    │
    ▼
[xlite-ascend-runner] 编译 & 测试
    │
    ▼
[xlite-html-reporter] 生成报告
    │
    ▼
  性能提升？
  /        \
是          否
|            |
标记 kept   [xlite-atomic-journal] 回退 after.patch
|            |
返回摘要   返回失败原因
```

### 回滚实现

```bash
# 回退最近一次修改
git apply -R .xlite-opt/journal/20260816-143052-conv-decode/after.patch

# 或完整还原 before.patch
git apply .xlite-opt/journal/20260816-143052-conv-decode/before.patch
```

---

## 7. npm 包结构

```text
xlite-perf-optimizer/
├── package.json
├── README.md
├── LICENSE
├── bin/
│   └── xlite-opt-init.js          # npm install 后/手动执行，初始化项目级 Agent
├── agent/
│   ├── agent.md                   # role prompt
│   └── opencode-agent.jsonc       # 需要合并到 opencode.jsonc 的片段
├── skills/
│   ├── xlite-analyzer/
│   │   └── SKILL.md
│   ├── xlite-complexity-estimator/
│   │   └── SKILL.md
│   ├── xlite-operator-dev/
│   │   └── SKILL.md
│   ├── xlite-atomic-journal/
│   │   └── SKILL.md
│   ├── xlite-profiler/
│   │   └── SKILL.md
│   ├── xlite-ascend-runner/
│   │   └── SKILL.md
│   ├── xlite-html-reporter/
│   │   ├── SKILL.md
│   │   └── templates/
│   │       └── report-template.html
├── scripts/
│   ├── postinstall.js             # 可选：安装后提示运行初始化命令
│   └── smoke-test.js              # 结构自检脚本
└── helpers/
    ├── ascend-container-test.sh   # 一键昇腾容器构建与测试
    └── parse-perf-log.py          # 解析性能日志为 JSON 指标
```

### 7.1 安装后项目结构

执行 `npx xlite-opt-init` 后：

```text
~/.config/opencode/
├── agents/
│   └── xlite-perf-optimizer/
│       └── agent.md
└── skills/
    ├── xlite-analyzer/
    ├── xlite-complexity-estimator/
    ├── xlite-operator-dev/
    ├── xlite-atomic-journal/
    ├── xlite-profiler/
    ├── xlite-ascend-runner/
    └── xlite-html-reporter/

<project-root>/
├── .xlite-opt/
│   ├── journal/
│   └── reports/
└── opencode.jsonc   # 已追加 xlite-perf-optimizer agent 配置
```

### 7.2 package.json 关键字段

```json
{
  "name": "xlite-perf-optimizer",
  "version": "0.1.0",
  "description": "xlite 性能优化自动化 Agent",
  "bin": {
    "xlite-opt-init": "./bin/xlite-opt-init.js"
  },
  "scripts": {
    "postinstall": "node scripts/postinstall.js"
  },
  "files": [
    "agent/",
    "skills/",
    "helpers/",
    "bin/",
    "scripts/",
    "README.md"
  ]
}
```

---

## 8. 复杂度估计实现思路

### 8.1 单算子复杂度

每个算子维护一个 `op_complexity.json`：

```json
{
  "XliteOpConv1dAndSiLU": {
    "formula": "B * C * (S + K) * T_vec",
    "variables": {
      "B": "batch",
      "C": "channels",
      "S": "seqlen",
      "K": "kernelDim"
    },
    "coefficient": 1.0
  }
}
```

`xlite-complexity-estimator` 读取当前模型配置，代入变量计算理论值，并与 profiling 实际值拟合系数。

### 8.2 端到端 latency 公式

```text
T_prefill(input_tokens, batch_size) =
    embed + sum_layers(
        T_attn_prefill(layer, input_tokens, batch_size)
      + T_ffn_prefill(layer, input_tokens, batch_size)
      + T_norm_add
    ) + head

T_decode(output_tokens, batch_size) =
    output_tokens * (
        embed + sum_layers(
            T_attn_decode(layer, batch_size)
          + T_ffn_decode(layer, batch_size)
          + T_norm_add
        ) + head
    )
```

其中 `T_attn_decode` 和 `T_ffn_decode` 通过单算子模型聚合得到。

---

## 9. 测试与验证

### 9.1 单算子测试

- 每个新算子必须对应 `tests/kernels/<op_name>.py`。
- 与 PyTorch eager 结果对比，bf16 相对误差 `< 1e-3`。

### 9.2 端到端测试

- 固定 prompt + temperature=0，对比优化前后 token 序列一致性。
- 长 prompt（4k/8k）perplexity 相对变化 `< 0.5%`。
- 性能指标：wall(ms)、tpot(ms/token)、throughput(tokens/s)。

### 9.3 Agent 自身测试

- 安装测试：`npm install` + `npx xlite-opt-init` 后，全局 skill/agent 目录与 `.xlite-opt/` 目录正确生成；`npx xlite-opt-init --force` 能备份并覆盖配置。
- 结构测试：运行 `node node_modules/xlite-perf-optimizer/scripts/smoke-test.js` 通过。
- 辅助脚本测试：`parse-perf-log.py` 能正确解析示例日志；`ascend-container-test.sh` 通过 `bash -n` 语法检查。
- 配置测试：`opencode.jsonc` 中 agent 配置可解析，prompt 路径为存在的绝对路径。
- 回滚测试：构造一次性能退化的修改，验证 Agent 能自动回退。

---

## 10. 安全与限制

- Agent 只修改 xlite 相关目录，修改范围通过 `XLITE_ALLOWED_DIRS` 环境变量可审计。
- 昇腾容器执行前必须能识别到容器，否则拒绝执行外部命令。
- 所有 `docker exec` 命令需显式打印，并在摘要中记录。
- 本地容器/复用容器测试模式下禁止执行 git commit / push / reset / rebase；`xlite-gitcode-runner` 远端模式仅允许为临时测试分支执行一次性的 commit/push。
- 禁止安装或修改系统级软件包。

---

## 11. 演进路线

| 版本 | 目标 |
|------|------|
| v0.1.0 | 完成 Agent 骨架、8 个内置 skill、原子回滚、HTML 报告 |
| v0.2.0 | 集成复杂度估计与实际 profiling 自动拟合 |
| v0.3.0 | 支持更多模型（Qwen3.6、DeepSeek-V4 等）的自动适配 |
| v0.4.0 | 支持自动算子搜索/Auto-Tuning（如 conv kernel tile size） |

---

## 12. 待确认事项

- [ ] HTML 报告模板风格是否满足需求？
- [ ] 是否需要支持除昇腾容器外的本地 NPU 运行模式？
- [ ] `xlite-complexity-estimator` 是否需要与现有 `auto_tuner.cpp` 联动？
- [ ] 是否需要把 Agent 的修改自动推送到临时分支供人工 review？
