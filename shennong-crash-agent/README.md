# Shennong Crash Agent

> 一个最小化的 OpenCode 插件，仅用于 Linux 内核宕机诊断。

## 范围

只保留以下核心能力：

- **Agent**：`shennong`（神农）内核宕机诊断**主 Agent**，直接调用下方 MCP 完成诊断。
- **Skill / MCP**：
  - `crash-feature-matcher`（**MCP**）— 崩溃特征提取与已知/社区案例检索
  - `vmcore-analysis`（Skill）— vmcore 深度分析
  - `witty-log-detection`（**MCP**）— 日志异常检测
  - `crash-report-generator`（Skill）— 标准化 JSON 报告生成

神农作为独立 Agent，直接调用 crash-feature-matcher 与 witty-log-detection 两个 MCP 完成诊断。

## 安装

### 方式一：使用 `opencode plugin` 命令安装到全局配置（推荐）

```bash
opencode plugin /root/shennong-crash-agent/shennong-crash-agent-0.1.0.tgz -g
```

> `-g` 表示安装到全局 `~/.config/opencode/` 配置；去掉 `-g` 则安装到当前项目。
>
> 推荐全局安装，这样在任何项目目录中都能直接调用 `shennong`。

### 方式二：安装到项目目录

```bash
# 1. 安装到你想让 OpenCode 加载的项目目录
cd /your/project
cp /root/shennong-crash-agent/shennong-crash-agent-0.1.0.tgz ./
npm install ./shennong-crash-agent-0.1.0.tgz

# 2. 等待 postinstall 自动创建 Python venv（依赖 Python 3.11，需要几分钟）
```

### 方式三：直接引用源码目录（开发调试）

```bash
cd /root/shennong-crash-agent
npm install
npm run build
```

## 注册到 OpenCode

安装插件后，**必须**让 OpenCode 加载插件。在 `~/.config/opencode/opencode.jsonc`（全局）或 `.opencode/opencode.jsonc`（项目级）中添加 `plugin` 字段：

### 方式一/二安装后：使用模块名

```json
{
  "plugin": ["shennong-crash-agent"],
  "$schema": "https://opencode.ai/config.json"
}
```

### 方式三（源码目录）：使用文件 URL

```json
{
  "plugin": ["file:///root/shennong-crash-agent/dist/index.js"],
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

插件安装后，`crash-feature-matcher` MCP 通过 `skills/crash-feature-matcher/mcp_config.json` **自动注册**为 stdio 本地 MCP Server，由 `skills/crash-feature-matcher/run_mcp.sh` 启动，依赖 `.venvs/crash-feature-matcher`。无需手动修改 `opencode.json`。

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

若未配置 RAG，神农会：

- 继续使用 `analyze_crash` 提取崩溃特征；
- 跳过内部/社区案例检索；
- 更多依赖 `witty-log-detection` 与 `vmcore-analysis` 回退模式完成诊断。

## 环境变量

插件本身不强制要求环境变量。实际诊断依赖的 LLM API 由 OpenCode 统一配置。

### 内置 MCP 与 venv

两个 MCP Server 均通过各自 `skills/*/mcp_config.json` 自动注册，无需手动修改 `opencode.json` 的 `mcp` 段：

- `crash-feature-matcher` MCP：stdio 类型，由 `skills/crash-feature-matcher/run_mcp.sh` 启动，依赖 `.venvs/crash-feature-matcher`。
- `witty-log-detection` MCP：SSE 类型，默认地址 `http://localhost:12144/sse`，由 `skills/witty-log-detection/run_server.sh` 启动，依赖 `.venvs/witty-log-detection`。

`npm install` 完成后会自动执行 `postinstall.mjs`，创建上述 Python venv 并安装依赖（需要 Python 3.11）。若安装时跳过了 postinstall，可手动运行：

```bash
node node_modules/shennong-crash-agent/postinstall.mjs
```

## 目录结构

```
shennong-crash-agent/
├── src/
│   ├── index.ts              # 插件入口，注册 shennong 主 Agent
│   ├── agents/
│   │   ├── system-prompt.ts  # Agent 组装与权限
│   │   ├── identity-constraints.ts
│   │   └── behavioral-summary.ts
│   └── shared/
│       ├── env-prompt.ts
│       └── language-prompt.ts
├── skills/                   # 4 个核心 Skill / MCP
│   ├── crash-feature-matcher/
│   │   ├── mcp_config.json   # MCP 自动注册配置（stdio）
│   │   └── run_mcp.sh        # MCP Server 启动脚本
│   ├── vmcore-analysis/
│   ├── witty-log-detection/
│   │   └── mcp_config.json   # MCP 自动注册配置（SSE）
│   └── crash-report-generator/
├── .venvs/                   # 两个 MCP 的 Python 依赖（未打包，安装后生成）
├── dist/
├── package.json
├── tsconfig.json
└── tsup.config.ts
```

## 版本

- `0.1.0`
- 构建产物：`/root/shennong-crash-agent/shennong-crash-agent-0.1.0.tgz`（Skill 与 venv 未打包）

## 常见问题

### 1. 安装后 `opencode agent list` 看不到 `shennong`

- 检查 `~/.config/opencode/opencode.jsonc` 是否已添加 `plugin` 字段。
- 检查路径是否正确，文件 URL 使用绝对路径。
- 重启 OpenCode TUI/Server。

### 2. `opencode` 报插件加载失败

- 检查插件目录是否有 `node_modules`（依赖 `@opencode-ai/plugin` 等）。
- 检查 `dist/index.js` 是否存在（运行 `npm run build`）。
- 检查 Python 版本是否为 3.11，且 `pip` 可用。

### 3. MCP 启动失败

- 确认 `postinstall` 已执行，`.venvs` 目录已生成。
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
- 如果其他 MCP Server 正常但 crash-feature-matcher 不显示，删除并重新安装插件，确保 postinstall 执行完毕。
- **重启 OpenCode** 后生效。

### 7. crash-feature-matcher 返回“未配置 RAG 知识库”/“离线模式”

- 崩溃特征提取（`analyze_crash`）仍可正常工作。
- 若需要内部/社区案例检索，请配置 RAG 服务端点，详见上方“`crash-feature-matcher` 知识库 RAG 配置”。
- 未配置 RAG 时，神农会跳过案例检索，改用日志检测与 vmcore 回退模式继续诊断。
