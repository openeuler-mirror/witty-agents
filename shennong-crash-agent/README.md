# Shennong Crash Agent

> 一个最小化的 OpenCode 插件，仅用于 Linux 内核宕机诊断。

## 目录

- [范围](#范围)
- [诊断产出（报告结构）](#诊断产出报告结构)
- [快速开始](#快速开始)
- [安装](#安装)
  - [源码构建与本地安装（开发者）](#源码构建与本地安装开发者)
- [注册到 OpenCode](#注册到-opencode)
- [验证](#验证)
- [使用示例](#使用示例)
- [MCP 与 Skill 配置](#mcp-与-skill-配置)
- [环境变量](#环境变量)
- [online / offline 变体打包](#online--offline-变体打包)
- [目录结构](#目录结构)
- [版本](#版本)
- [常见问题](#常见问题)

## 范围

只保留以下核心能力：

- **Agent**：`shennong`（神农）内核宕机诊断**主 Agent**，直接调用下方 MCP 完成诊断。
- **Skill / MCP**：
  - `crash-feature-matcher`（**MCP**）— 崩溃特征提取与已知/社区案例检索
  - `vmcore-analysis`（Skill）— vmcore 深度分析
  - `witty-log-detection`（**MCP**）— 日志异常检测
  - `crash-report-generator`（Skill）— 标准化 JSON 报告生成
- **辅助 Skill**：`gitcode` — 按需查询 GitCode 上的仓库、议题、PR 和提交。

神农作为独立 Agent，直接调用 crash-feature-matcher 与 witty-log-detection 两个 MCP 完成诊断。

## 诊断产出（报告结构）

神农基于现场数据（vmcore / vmcore-dmesg / dmesg / sosreport 等）输出一份符合
`DiagnoseReport` 结构的标准化 JSON 报告，并渲染为可直接 `file://` 打开的自包含
`crash-report.html`。报告正文分五个章节，另附原始数据与诊断工作流：

1. **故障总览**：`conclusion`、`standard_solution` 与有案例依据时才展示的 `temporary_workaround`；
2. **宕机特征**：RIP / 签名 / 模块等基础字段，以及 `log_features` 日志特征（相关报错 / 重复日志 / 其它异常）；
3. **故障是怎样发生的**：`deep.mechanism_summary`、`event_scene` 事件时序和统一的 `deep.judgment`；
4. **为什么得出这个结论**：`deep.evidence[]`，每条核心依据拥有独立的证据推理链；
5. **技术附件**：`propagation_chain`、日志明细、案例资料、工作流和完整原始报告数据。

`event_scene` 使用“固定骨架 + 有限推断”：泳道固定为进程 / 内核 / 硬件，主链路建议 4–8 步；事件以 `evidence_level` 区分 L1（直接证据）、L2（强推断）和 L3（机制补全），主图只展示 L1/L2。只有存在两个并发路径、共享状态和明确交错关系时才绘制 `race` 竞态窗口。

案例资料按内部案例、社区案例、社区邮件、社区会议、在线案例分类展示。`temporary_workaround.case_refs` 为空时不展示临时缓解卡片，避免将没有案例依据的通用建议当成结论。

诊断约束与字段规范见 `agent.md` 与 `skills/crash-report-generator/`（含 JSON Schema
`schemas/crash-report-schema.json`）；报告生成后必须通过 `validate_report.py` 强校验。

## 快速开始

已发布的 npm 包最短三步（详见「安装」）：

```bash
npm install @openeuler/agent-shennong-crash-online   # ① 装包
npm exec --offline -- shennong-setup install         # ② 装 Python 依赖
npm exec --offline -- shennong-configure             # ③ 登记 OpenCode 插件 + MCP
# 重启 opencode 后：@ shennong <vmcore 路径 / 日志路径>
```

## 安装

安装分为三步：install → setup → configure。npm 安装阶段只落盘包文件，
不会创建 Python 虚拟环境、执行 pip 或修改 OpenCode 配置。

### 第一步：安装 npm 包

在线包：

```bash
npm install @openeuler/agent-shennong-crash-online
```

离线 Python 依赖包：

```bash
npm install @openeuler/agent-shennong-crash-offline
```

`npm install` 只安装插件、Skill 和命令文件，不修改 Python 环境和 OpenCode 配置。

#### openEuler 系统运行库

Python wheels 不包含操作系统动态库。openEuler 最小化环境在断网执行 setup 前，
需要由系统镜像或管理员提前安装以下运行库：

```bash
sudo dnf install -y \
  libglvnd-glx \
  glib2 \
  libXext \
  libXrender \
  libSM
```

其中 `libglvnd-glx` 提供 OpenCV/PaddleOCR 所需的 `libGL.so.1`。这些 RPM 是
目标操作系统前置条件，不属于 Python wheelhouse；正式离线环境应将它们固化在
基础镜像或系统安装介质中。已在 openEuler 24.03 LTS SP4 x86_64、CPython 3.11
环境通过 `--network none` 安装和运行验证。

### 第二步：显式安装 Python 依赖

项目本地安装后执行：

```bash
npm exec --offline -- shennong-setup install
```

> npm 没有 `npm shennong-setup` 这种子命令语法；项目本地安装必须通过
> `npm exec --offline --` 调用包提供的可执行文件。

全局 npm 安装后也可以直接执行：

```bash
shennong-setup install
```

该命令才会在用户缓存目录 `~/.cache/witty-agents/<package>/venvs/` 下创建三个
独立 Python 环境。在线包在此时联网下载 Python 依赖；离线包只读取随包携带的
wheelhouse，不访问 Python 包索引。online 与 offline 包按包名分别缓存，
互不干扰。当前依赖集合支持 Python 3.11 或 3.12，优先选择 3.11；Python 3.13 暂不放行。
为避免全局 npm 目录权限问题，当前优先使用项目本地安装方式。安装完成前会对
每套环境执行 `pip check` 和核心模块导入；任一验证失败都不会写入完成标记，
使用 `--force` 重装时还会恢复原有可用环境。

> Python 虚拟环境位于包外的用户缓存目录（`~/.cache/witty-agents/`，可用环境变量
> `SHENNONG_VENV_CACHE` 覆盖），npm 卸载、重装、升级或清理 `node_modules`
> 不会删除这三套环境。重装包后 `run_mcp.sh` / `run_server.sh` 等启动入口直接
> 指向缓存中的环境，无需重新执行 `shennong-setup install`。升级或卸载前建议
> 先执行 `shennong-setup stop`，停止由当前安装目录管理的 SSE 服务。

安装成功后会写入 `<venvs>/setup-complete.json`，并确保三个组件可用：

- `witty-log-detection` 是 SSE MCP，setup 会启动服务并检查 `127.0.0.1:12144`；
- `crash-feature-matcher` 是 stdio MCP，setup 校验其环境和启动入口，由 OpenCode 使用时按需拉起；
- `crash-report-generator` 是 Skill，setup 校验其 Python 环境，不启动常驻进程。

重复执行相同命令时会重新执行 `pip check`、核心模块导入和服务状态校验；全部
通过后直接返回，不会再次创建环境、执行 pip install 或重复启动 SSE 服务。

可单独查看、启动或停止 package 管理的 SSE 服务：

```bash
npm exec --offline -- shennong-setup status
npm exec --offline -- shennong-setup start
npm exec --offline -- shennong-setup stop
```

服务日志和 PID 记录保存在安装包目录的 `.runtime/` 下。

可先只检查环境，不写入文件：

```bash
npm exec --offline -- shennong-setup check
```

### 第三步：登记 OpenCode 插件和 MCP

```bash
npm exec --offline -- shennong-configure
# 等价的显式写法
npm exec --offline -- shennong-configure install --target=opencode
```

该命令把当前 online/offline 安装包的本地 `dist/index.js` 文件 URL 登记到
OpenCode `plugin` 数组，并移除旧的 Shennong 包名或本地入口。使用本地入口可以
保证尚未发布的包和断网安装的 offline 包都加载本次已经执行 setup 的同一份文件。
同时会在 OpenCode `mcp` 段登记 `crash-feature-matcher` 本地 stdio MCP 和
`witty-log-detection` SSE MCP，并保留用户已有的其他 MCP 配置。
若配置文件已经存在且确实需要修改，会先在同目录生成
`opencode.jsonc.shennong-backup-<时间戳>` 备份，再原子写入新配置。重复执行时
配置内容不变，也不会重复生成备份。

#### 完全离线使用 OpenCode 的前置条件

offline 包保证 `npm install`、`shennong-setup install` 和
`shennong-configure` 不需要访问公网，但不包含 OpenCode 本体、Provider 包或模型目录。
OpenCode 首次启动可能访问 `models.dev` 并下载 Provider 包。因此，在进入完全断网环境前，
需要先安装并启动一次 OpenCode，完成 Provider/模型配置和必要缓存；断网后再安装
Shennong offline 包并执行上述三步。此要求属于 OpenCode 宿主初始化，不是 Python
wheelhouse 缺失。

取消注册时只移除 Shennong，不覆盖用户后续增加的其他配置；修改前同样会备份：

```bash
npm exec --offline -- shennong-configure remove --target=opencode
```

`shennong-configure` 已采用框架适配器结构。可通过下面的命令查看 DSH
适配边界和模板状态，但在 `witty-log-detection` 提供 Streamable HTTP
`/mcp` 之前，DSH 的 install/remove 会明确拒绝执行，不会写入半成品配置：

```bash
npm exec --offline -- shennong-configure status --target=dsh
```

全局 npm 安装后可直接执行：

```bash
shennong-configure
```

### 源码构建与本地安装（开发者）

本节给出「改源码 → 构建 → 本地安装 → 验证」的完整流程，适用于二次开发后在本地跑通验证。
三步 npm 安装（install → setup → configure）的语义与上面「安装」一节一致，这里重点讲**从源码构建**以及**踩坑点**。

#### 0. 前置条件

- **Node.js ≥ 20**（`npm run build` / `pack:*` 脚本运行依赖）
- **Python 3.11 或 3.12**（`shennong-setup install` 用它创建 venv；3.13 暂不放行）
- **Git LFS**（构建 **offline** 包才需要，用于拉取 `*.pdiparams` OCR 模型；online 包可跳过）
- **opencode** 已安装、可启动

#### 1. 拉取源码

```bash
git clone <仓库地址> shennong-crash-agent
cd shennong-crash-agent
git lfs pull          # 仅 offline 包需要；online 包跳过
```

#### 2. 构建 npm 包

```bash
cd shennong-crash-agent
npm install           # 安装构建/校验依赖
npm run build         # 校验 dist/index.js：语法、导出、Shennong Agent 注册结果
npm run pack:online   # 生成 artifacts/openeuler-agent-shennong-crash-<version>.tgz
```

> 仓库以**已提交的预构建 `dist/index.js` 作为发布入口，不含 TypeScript 源码生成链**。
> `npm run build`（`scripts/validate-dist.mjs`）只做校验、不重新生成 `dist/index.js`。
> `pack:offline` 会额外为当前 Python/OS/CPU 构建并携带 wheels，见「online / offline 变体打包」一节。

#### 3. 安装到本地 consumer 项目

```bash
mkdir -p /tmp/shennong-consumer && cd /tmp/shennong-consumer
# 写一个最小 package.json，依赖指向刚打的 tgz
cat > package.json <<'EOF'
{"name":"shennong-consumer","private":true,"dependencies":{"@openeuler/agent-shennong-crash":"file:/path/to/shennong-crash-agent/artifacts/openeuler-agent-shennong-crash-<version>.tgz"}}
EOF
npm install
```

#### 4. 安装 Python 依赖（创建 venv）

```bash
cd node_modules/@openeuler/agent-shennong-crash
npm exec --offline -- shennong-setup install
npm exec --offline -- shennong-setup status   # 确认 crash-feature-matcher / witty-log-detection / crash-report-generator 三个组件 ready
```

#### 5. 登记 OpenCode 插件 + MCP

```bash
npm exec --offline -- shennong-configure install --target=opencode
```

#### 6. 重启 opencode 验证

```bash
opencode agent list   # 应能看到 shennong (primary)
```

改完配置 / 重装后**必须重启 opencode**（旧配置和插件会被缓存）。

---

#### 源码构建安装踩坑清单（重要）

1. **改了源码必须「重新打包 + 重装」，且 npm 有缓存会误判「up to date」**
   `pack:online` 打出的 tgz 内容变了、但版本号没变时，npm 对 `file:` 依赖按缓存命中，
   会返回 `up to date` 而**不重新解包**。重装时要显式清掉：
   ```bash
   cd /tmp/shennong-consumer
   rm -rf node_modules/@openeuler/agent-shennong-crash package-lock.json
   npm install          # 必要时加 npm cache clean --force
   ```

2. **版本号变了，consumer 的 `file:` 路径要同步改**
   `pack:online` 生成的 tgz 文件名带版本号（`openeuler-agent-shennong-crash-<version>.tgz`），
   改了 `package.json` 里的 `version` 后，consumer 的依赖路径要跟着改成新文件名，否则装的是旧包。

3. **skill 实际加载自 `~/.config/opencode/skills/`，不是安装包里的 `skills/`**
   opencode 里同名 skill 会解析到用户级 `~/.config/opencode/skills/<skill>/` 的**副本**，
   而不是 `node_modules/@openeuler/agent-shennong-crash/skills/`。改了 skill
   （如 `crash-report-generator` 的 SKILL.md / prompt / schema / viewer 模板）后，
   **重装 npm 包并不会自动更新这个副本**，必须手动同步，否则报告生成规则还是旧的：
   ```bash
   rsync -a --delete --exclude '__pycache__' --exclude '.venv' \
     shennong-crash-agent/skills/crash-report-generator/ \
     ~/.config/opencode/skills/crash-report-generator/
   ```

4. **agent 的 prompt 内嵌在 `dist/index.js`，不是直接读 `agent.md`**
   插件运行时用 `dist/index.js` 里内嵌的 `SHENNONG_SYSTEM_PROMPT`。当前实现里
   `getShennongPrompt` 会**优先读包内 `agent.md`**（读不到才回退内嵌），所以改
   `agent.md` 后重新打包即可生效；但如果改动了 `dist/index.js` 自身的 prompt 加载逻辑，
   要确认它仍能正确加载 `agent.md`。

5. **OCR 模型是 Git LFS（仅 offline 包）**
   `*.pdiparams` 走 Git LFS，构建 **offline** 包前必须 `git lfs pull`，否则构建脚本会
   拒绝残留的 LFS pointer。online 包不携带模型，`setup install` 时从 PaddleOCR 官方源下载。

6. **venv 缓存在包外，重装 npm 包不会重建**
   Python 环境在 `~/.cache/witty-agents/<package>/venvs/`（可用 `SHENNONG_VENV_CACHE`
   覆盖）。只有 Python 依赖变化时才需要重跑 `shennong-setup install`（`--force` 会重建，
   失败时回退到原有可用环境）；改纯文档/schema/viewer 不触发重建。

7. **SSE 服务端口被旧进程占用**
   witty-log-detection 用 `127.0.0.1:12144`。旧安装残留的进程会占住端口，setup 会
   WARNING 并复用，可能行为异常——先 `shennong-setup stop` 或杀掉残留进程再重装。

8. **报告有 Schema 强校验，缺字段会直接 FAILED**
   最终 `report.json` 必须通过 `validate_report.py`（jsonschema 强校验）。例如
   `root_cause_analysis` 现在**强制要求** `conclusion`/`event_scene`/`propagation_chain`/
   `reasoning_flow`/`deep`，缺了会报 `'event_scene' is a required property`，
   生成报告时要保证这些章节齐备。

## 注册到 OpenCode

安装插件后，**必须**执行 `shennong-configure` 让 OpenCode 加载插件。默认写入
`~/.config/opencode/opencode.jsonc`；如需项目级配置，可手动修改
`.opencode/opencode.jsonc`，或用 `SHENNONG_OPENCODE_CONFIG` 显式指定路径。

### npm 安装后：使用本地文件 URL

```json
{
  "plugin": ["file:///path/to/node_modules/@openeuler/agent-shennong-crash-online/dist/index.js"],
  "$schema": "https://opencode.ai/config.json"
}
```

### 源码目录：使用文件 URL

```json
{
  "plugin": ["file:///path/to/shennong-crash-agent/dist/index.js"],
  "$schema": "https://opencode.ai/config.json"
}
```

## 验证

```bash
# 查看已注册 agent，应能看到 shennong (primary)
opencode agent list
```

在交互界面中按 `Tab` 或输入 `@` 切换到 `shennong`。如果仍未显示，**重启 OpenCode TUI/Server**，因为旧配置可能已缓存。

## 使用示例

```text
@ shennong 我有个系统 crash，vmcore 在 /home/crash/...，请分析根因。
```

或直接在配置中指定入口 Agent 为 `shennong`。

## MCP 与 Skill 配置

### 1. `witty-log-detection` 日志检测 MCP

该 MCP 基于 Embedding 和 LLM 进行日志异常检测，首次调用前必须配置 Embedding / LLM 的 API 密钥。

调用任意日志检测任务时，如果未配置，MCP 会返回提示并引导你完成配置：

```text
调用 setup_log_detection_config 工具
或手动创建 ~/.config/shennong-crash-agent/witty-log-detection-config.toml
```

也可以使用 `test_log_detection_connection` 工具测试连接是否成功。

### 2. `vmcore-analysis` VMcore 分析 Skill

该 Skill 通过 `crash` 工具分析 vmcore，需要对应内核版本的 `vmlinux`（带调试信息）。

- 如果提供了 `vmlinux`，脚本会使用 `crash` 进行完整分析。
- 如果缺少 `vmlinux`，但 vmcore 同级目录存在 `vmcore-dmesg.txt`，脚本会自动进入回退模式，仅通过 dmesg 进行关键字匹配和故障分类。
- 获取 `vmlinux` 的典型方式：安装 `kernel-debuginfo` 包，或将 `vmlinux` 放到 vmcore 同级目录。

### 3. `crash-feature-matcher` 崩溃特征提取与检索 MCP

插件安装后，执行 `shennong-configure` 会将 `crash-feature-matcher` 注册为 stdio
本地 MCP Server，由 `skills/crash-feature-matcher/run_mcp.sh` 启动，依赖
`.venvs/crash-feature-matcher`。无需用户手动修改 `opencode.json`。

该 MCP 的**崩溃特征提取**（`analyze_crash`）无需额外配置即可运行。

但**内部已知问题库 / 社区案例库检索**（`query_knowledge`、`query_cases`、`query_community_cases`）依赖外部 RAG 服务，默认配置中的知识库 ID 为占位符，需要用户自行提供可用的 RAG 端点：

```bash
# 修改 skills/crash-feature-matcher/src/crash_matcher/settings.toml 中的 [rag] 段
# 或通过环境变量覆盖：
export RAG_BASE_URL="https://your-rag-service.example.com"
export CRASH_KNOWLEDGE_KB_ID="your-knowledge-kb-id"
export CRASH_CASES_KB_ID="your-cases-kb-id"
export LINUX_COMMUNITY_KB_ID="your-linux-community-kb-id"
export OPENEULER_COMMUNITY_KB_ID="your-openeuler-community-kb-id"
export RAG_ACCESS_KEY="your-access-key"
```

LLM 相关配置默认不携带密钥，可通过环境变量注入：

```bash
export SHENNONG_LLM_API_KEY="your-api-key"
export SHENNONG_LLM_BASE_URL="https://your-openai-compatible-endpoint/v1"
export SHENNONG_LLM_MODEL="your-model"
```

若未配置 RAG，神农会：

- 继续使用 `analyze_crash` 提取崩溃特征；
- 跳过内部/社区案例检索；
- 更多依赖 `witty-log-detection` 与 `vmcore-analysis` 回退模式完成诊断。

### 4. `crash-report-generator` 报告生成 Skill

标准化的 JSON 报告生成 Skill，定义 `DiagnoseReport` 的 JSON Schema 与生成提示词。
产物为 `report.json` + 自包含的 `crash-report.html`（可直接 `file://` 打开），
报告结构与字段规范见「诊断产出（报告结构）」一节。核心文件：

- `schemas/crash-report-schema.json`：报告 Schema（强校验用）；
- `prompts/generate-report.md`：报告生成提示词；
- `scripts/validate_report.py` / `combine_report.py` / `generate_report_html.py`：校验 / 合并 / 渲染脚本。

### 5. `gitcode` 辅助 Skill

按需查询 GitCode 平台上的仓库、议题、PR、提交等数据的辅助 Skill，仅在诊断过程中
需要查询相关 commit / issue 时使用。

## 环境变量

插件本身不强制要求环境变量。实际诊断依赖的 LLM API 由 OpenCode 统一配置。

### 内置 MCP 与 venv

两个 MCP Server 均由 `shennong-configure` 自动写入 OpenCode `mcp` 段，无需用户手工登记：

- `crash-feature-matcher` MCP：stdio 类型，由 `skills/crash-feature-matcher/run_mcp.sh` 启动，依赖 `.venvs/crash-feature-matcher`。
- `witty-log-detection` MCP：SSE 类型，默认地址 `http://localhost:12144/sse`，执行 `shennong-setup install` 时自动启动，依赖 `.venvs/witty-log-detection`。

两个 MCP 所需的 Python 环境均由 `shennong-setup` 创建；`npm install` 本身不会
创建 Python venv、启动 MCP，也不会修改 OpenCode 配置。

## online / offline 变体打包

统一使用 `variant` 参数生成两个互不污染的 npm 包：

```bash
# 精简在线包：不携带 Python wheels 和本地 OCR 模型
npm run pack:variant -- --variant=online --out-dir=artifacts

# 离线包：为当前 Python/操作系统/CPU 构建并携带 Python wheels
npm run pack:variant -- --variant=offline --out-dir=artifacts
```

源码基座包名为 `@openeuler/agent-shennong-crash`。为让 npm 上的两个产物可并存，
发布包名分别为 `@openeuler/agent-shennong-crash-online` 和
`@openeuler/agent-shennong-crash-offline`；对应 tgz 文件名由 npm 生成。
在线包在脚本内强制不超过
10 MiB；离线包不设置体积上限，但会将体积、平台、wheel 数量和 SHA256
写入 `artifacts/*-package-report.json`。

离线 wheel 与构建机的平台及 Python ABI 绑定，正式产物必须在目标
openEuler 架构和 Python 3.11 环境中生成。可用 `--python=/path/to/python`
或环境变量 `PYTHON_BIN` 指定解释器。

构建会生成知识文件 SHA256 清单，并拒绝 Git LFS 占位文件；离线包还会校验
wheel 清单闭合、SHA256、Python ABI、操作系统、CPU 架构、SOABI 与 libc。
任何一项不完整都会让 `shennong-setup check` 和发布门禁失败。

离线依赖解析还会读取 `packaging/offline-constraints.txt`。该文件将
PaddleOCR 的 OpenCV 扩展依赖与项目现有 `opencv-python==4.9.0.80`
保持一致，避免 pip 在多个几十 MiB 的候选 wheel 之间反复回溯下载。

OCR 模型文件使用 Git LFS 管理，根目录 `.gitattributes` 会将 `*.pdiparams` 交给
LFS filter。构建离线包前必须先执行 `git lfs pull`，并确认仓库服务端已启用 LFS；
构建脚本会拒绝残留的 LFS pointer，避免把只有百余字节的占位文本发布进 npm 包。

### OCR 模型获取（online 包）

online 包不携带本地 OCR 模型（仅保留源码），`shennong-setup install` 会从
PaddleOCR 官方源自动下载以下三组推理模型并校验 sha256，存放于用户缓存目录
`~/.cache/witty-agents/<package>/ocr-models/`（重装包不会丢失）：

- `ch_PP-OCRv4_det_infer`（检测）
- `ch_PP-OCRv4_rec_infer`（识别）
- `ch_ppocr_mobile_v2.0_cls_infer`（方向分类）

下载失败（如网络不可达）时 setup 会输出 WARNING 并继续完成安装，本地 OCR
暂不可用；网络恢复后重跑 `shennong-setup install` 即可补齐（已下载且校验
通过的模型自动跳过）。offline 包已内置上述模型，无需下载。OCR 需要 CPU
支持 AVX-512。

## 目录结构

```text
shennong-crash-agent/
├── bin/
│   ├── shennong-setup.mjs       # 一键安装三套 Python 环境
│   └── shennong-configure.mjs   # 统一的框架配置入口
├── lib/
│   ├── mcp-services.mjs         # MCP 服务生命周期管理
│   ├── opencode-config.mjs      # 旧导入路径的兼容转发
│   └── configure/
│       ├── common.mjs           # 参数、适配器契约和能力检查
│       ├── backup.mjs           # 通用备份和原子写入
│       └── adapters/
│           ├── index.mjs        # 框架适配器注册表
│           ├── opencode.mjs     # OpenCode JSONC 安全注册逻辑
│           └── dsh.mjs          # DSH 适配边界和状态检查
├── frameworks/
│   └── dsh/
│       ├── package.json.template
│       ├── cordis.patch.yml.template
│       └── shennong-persona.md
├── skills/                   # 4 个核心 Skill / MCP
│   ├── crash-feature-matcher/
│   │   ├── mcp_config.json   # MCP 自动注册配置（stdio）
│   │   └── run_mcp.sh        # MCP Server 启动脚本
│   ├── vmcore-analysis/
│   ├── witty-log-detection/
│   │   └── mcp_config.json   # MCP 自动注册配置（SSE）
│   └── crash-report-generator/
├── dist/index.js             # 已提交的预构建 OpenCode 插件入口
├── scripts/
│   ├── build-package.mjs     # online/offline 变体打包与检查
│   └── validate-dist.mjs     # 预构建 dist 入口校验
└── package.json

# Python 虚拟环境不在包内，由 shennong-setup 生成于
# ~/.cache/witty-agents/<package>/venvs/（SHENNONG_VENV_CACHE 可覆盖）
```

## 版本

- `0.10.4`
- npm 包：`@openeuler/agent-shennong-crash-online` / `@openeuler/agent-shennong-crash-offline`

## 常见问题

### 1. 安装后 `opencode agent list` 看不到 `shennong`

- 检查 `~/.config/opencode/opencode.jsonc` 是否已添加 `plugin` 字段。
- 检查路径是否正确，文件 URL 使用绝对路径。
- 重启 OpenCode TUI/Server。

### 2. `opencode` 报插件加载失败

- 检查插件目录是否有 `node_modules/jsonc-parser`（用于安全修改 OpenCode JSONC 配置）。
- 运行 `npm run build`，检查 `dist/index.js` 的语法、导出和 Agent 注册结果。
- 检查 Python 版本是否为 3.11 或 3.12，且 `pip` 可用。

### 3. MCP 启动失败

- 确认已显式执行 `npm exec --offline -- shennong-setup install`，且 `.venvs` 目录已生成。
- 两个 MCP 通过 `skills/*/mcp_config.json` 自动注册，无需手动配置 `opencode.json` 的 `mcp` 段。
- 手动运行 `skills/crash-feature-matcher/run_mcp.sh` 看报错。
- 检查 witty-log-detection 的 SSE 端口 12144 是否被占用。

### 4. witty-log-detection 返回“尚未配置 Embedding / LLM 模型密钥”

- 使用 `setup_log_detection_config` 工具配置 API 密钥。
- 或手动创建 `~/.config/shennong-crash-agent/witty-log-detection-config.toml`。
- 配置后重新调用日志检测任务。

### 5. vmcore-analysis 提示缺少 vmlinux

- 在崩溃机器上安装对应版本的 `kernel-debuginfo` 包。
- 或将 `vmlinux` 放到 vmcore 同级目录，脚本会自动检测。
- 如果存在 `vmcore-dmesg.txt`，脚本会进入回退模式，用 dmesg 做关键字匹配。

### 6. crash-feature-matcher 工具（analyze_crash / query_knowledge 等）不可用

- 插件通过 `skills/crash-feature-matcher/mcp_config.json` 自动注册该 MCP，与 `witty-log-detection` 机制相同。
- 确认 `.venvs/crash-feature-matcher/bin/python` 存在且可执行。
- 如果其他 MCP Server 正常但 crash-feature-matcher 不显示，重新执行 `shennong-setup install --force`。
- **重启 OpenCode** 后生效。

### 7. crash-feature-matcher 返回“未配置 RAG 知识库”/“离线模式”

- 崩溃特征提取（`analyze_crash`）仍可正常工作。
- 若需要内部/社区案例检索，请配置 RAG 服务端点，详见上方“`crash-feature-matcher` 知识库 RAG 配置”。
- 未配置 RAG 时，神农会跳过案例检索，改用日志检测与 vmcore 回退模式继续诊断。

### 8. openEuler ARM64 导入 `paddleocr` 时崩溃

在 `openEuler aarch64 + glibc 2.38 + CPython 3.11` 的部分环境中，已观察到
`import paddleocr` 在 zlib `inflateReset2` 附近触发 `SIGSEGV`；同一环境单独导入
`paddle` 和 `cv2` 正常。该问题同时影响 online/offline 依赖组合，不是离线包漏装，
且由于 OCR 为懒加载，不影响不调用 OCR 的 MCP 工具。发布前应在目标架构上实测 OCR；
未完成兼容性验证时，不应宣称该环境支持 OCR 功能。

### 9. witty-log-detection 数据库保存在哪里

当前 `SQL_LITE_DB_PATH` 和 `EMBEDDING_CACHE_DB_PATH` 默认仍为相对路径，尚未实现从
只读种子数据库复制到用户缓存目录的工作副本机制。实际数据库位置取决于服务启动
工作目录；请勿把运行生成的 `.db`、`.db-wal` 或 `.db-shm` 当作发布内容。打包脚本
会主动拒绝这些运行期文件。后续若迁移到用户缓存目录，需要单独设计升级、并发和旧数据
迁移策略，不能在 npm 安装阶段隐式修改。
