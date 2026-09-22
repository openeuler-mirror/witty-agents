# Witty Agent 仓库规范（初版）

> 版本：v0.2（讨论稿）  
> 适用范围：本仓库中的所有可安装、可配置、可在 OpenCode 中运行的 Agent。

## 1. 这份规范定义什么

这里的 Agent 不是一段提示词，而是一个可以被构建、打包、安装、配置、运行、检查和卸载的交付单元。

一个完整 Agent 至少由以下部分组成：

1. **Agent 内容**：`agent.md`，定义角色提示词、工作流、可用 Skill、工具和输出规则。
2. **npm 包**：`package.json`、锁文件、构建产物和发布文件清单。
3. **安装生命周期**：`<agent>-setup` 和 `<agent>-configure` 两组 CLI。
4. **Skill 能力**：源码仓库可以不保存 Skill；但打包制品 MUST 包含所需 Skill。online 运行时优先从 [openEuler SkillHub](https://skillhub.openeuler.org/) 获取，失败时使用包内 Skill；offline 直接使用包内 Skill 和离线依赖。
5. **配置与运行时**：用户配置、插件注册、Skill 链接、缓存、服务和状态文件。
6. **测试与 CI**：安装契约、包体校验、变体构建和 Agent 注册信息。

本规范使用以下约定：

- **MUST**：必须满足，否则不能合并或发布。
- **SHOULD**：默认应满足；有明确理由时可以例外。
- **MAY**：按 Agent 需要选择。

## 2. 推荐目录结构

每个 Agent 应是仓库根目录下的独立目录，例如 `openeuler-ops-agent/`：

```text
<agent-dir>/
├── agent.md                         # MUST：角色提示词和工作流（推荐）
├── package.json                     # MUST：npm 包元数据和生命周期入口
├── package-lock.json                # SHOULD：锁定依赖
├── README.md                        # MUST：用户安装、使用、卸载文档
├── bin/
│   ├── <agent>-setup.mjs            # MUST：环境准备、运行控制
│   ├── configure.mjs                # MUST：注册/反注册宿主代码 Agent
│   └── <agent>-configure.mjs        # MAY：面向用户的命令别名
├── dist/                            # MUST：可发布的运行时代码
├── lib/                             # MAY：安装器、配置器、运行时库
├── skills/                          # MAY：源码内 Skill；最终制品 MUST 包含所需 Skill
├── config/                          # MAY：包内默认配置或配置样例
├── scripts/
│   ├── validate.mjs                 # SHOULD：源码/结构校验
│   ├── validate-dist.mjs            # SHOULD：发布包校验
│   └── build-package.mjs            # SHOULD：online/offline 构建
├── tests/
│   └── test-install-contract.mjs    # MUST：安装契约测试
├── ci/
│   ├── agent.json                   # MUST：CI 注册元数据
│   └── driver.mjs                   # MAY：CI 驱动
└── packaging/                       # MAY：镜像、系统包或额外打包文件
```

实际目录可按 Agent 类型增删，例如后端型 Agent 可以增加 `src/`、`apps/`、`frameworks/`、`opencode_plugin/`。历史 Agent 也允许将提示词放在 `agent/agent.md`；新 Agent 推荐放在根目录，且一个包只能有一个权威 Agent 提示词来源，不能出现两份内容漂移。

## 3. `agent.md` 规范

`agent.md` 是 Agent 的角色提示词和运行说明，MUST 随 npm 包发布。它可以位于包根目录（推荐）或兼容历史结构的 `agent/agent.md`，具体路径必须在 `package.json` 的 `files` 和构建校验中明确。它不是 README 的复制品，也不是实现代码；它描述 Agent 在对话运行时如何工作。

### 3.1 必须包含的内容

```markdown
# Agent 身份

你是谁，服务什么对象，负责解决什么问题。

## 能力与边界
- 能处理的任务
- 明确不能处理的任务
- 需要人工确认或转交的条件

## 可用 Skill
- Skill 名称、能力、使用时机
- Skill 来源：SkillHub 或本地 fallback

## 可用工具 / MCP
- 工具名称、用途、输入限制、权限级别

## 工作流
1. 任务理解与必要澄清
2. 知识/Skill 检索
3. 分步骤执行
4. 结果验证
5. 结构化输出

## 安全规则
- 不越权、不伪造结果、不泄露凭证
- 删除、覆盖、发布、远程写入等操作必须确认

## 输出格式
- 结果/状态
- 依据和来源
- 风险、限制和未完成项
- 后续建议
```

### 3.2 编写要求

- MUST 明确 Agent 的唯一职责、触发场景和不适用场景。
- MUST 把多步骤业务流程写成有顺序的步骤，并说明分支条件和失败降级方式。
- MUST 写出高风险操作的确认规则；不能只在代码中隐含。
- SHOULD 说明每个步骤依赖的 Skill、工具和预期产物。
- MUST 区分事实、工具返回、推断和待确认信息；禁止提示词要求 Agent 编造缺失结果。
- 不得把密钥、Token、机器专属路径或用户隐私写入 `agent.md`。

## 4. npm 包规范

### 4.1 `package.json` 必需字段

```json
{
  "name": "witty-agent-<id>",
  "version": "0.1.0",
  "description": "...",
  "type": "module",
  "main": "dist/index.js",
  "exports": { ".": "./dist/index.js" },
  "bin": {
    "<agent>-setup": "./bin/<agent>-setup.mjs",
    "<agent>-configure": "./bin/configure.mjs"
  },
  "files": ["agent.md", "dist/", "skills/", "bin/", "lib/", "README.md"],
  "engines": { "node": ">=20.0.0" },
  "scripts": {
    "validate": "node scripts/validate.mjs",
    "validate:dist": "node scripts/validate-dist.mjs",
    "pack:variant": "node scripts/build-package.mjs",
    "test:install-contract": "node tests/test-install-contract.mjs",
    "test": "node tests/test-install-contract.mjs"
  },
  "wittyAgentDistribution": {
    "primaryStyle": "plain",
    "packageNames": {
      "plain": "witty-agent-<id>",
      "organization": "@openeuler/agent-<id>"
    }
  }
}
```

当前发布以 **plain 包名** 为主，统一使用 `witty-agent-<id>`；organization 包名
`@openeuler/agent-<id>` 仅作为未来具备组织 npm scope 后的预留扩展，不作为当前发布前提。

`wittyAgentDistribution` 可以同时记录两种候选名称，但 MUST 标明 `primaryStyle: "plain"`。新 Agent 不得要求用户先配置组织 scope 才能安装。

### 4.2 包变体

每个正式发布的 Agent MUST 提供 `online` 和 `offline` 两个变体。当前主发布渠道为 plain 包，两个变体应使用：

```text
witty-agent-<id>-online
witty-agent-<id>-offline
```

两者应保持相同的 Agent ID、核心提示词、命令接口和主要功能；差异仅限于依赖来源、联网能力和需要在线服务的扩展能力。

`online` 变体允许在 setup 阶段访问 [openEuler SkillHub](https://skillhub.openeuler.org/)、npm/Python 源和配置的在线服务。`offline` 变体必须能够在目标机器完全无网络的情况下完成安装、检查、注册和声明为离线可用的核心任务。

变体构建必须：

- 使用同一个 Agent ID 和版本策略；
- 在构建结果中明确在线/离线差异；
- offline 包安装、setup、configure 和核心运行路径不能偷偷联网；
- offline 包不能依赖运行时访问 SkillHub、npm registry、PyPI、远程 Git 仓库或在线模型；
- offline 所需的 npm 依赖、Python wheel、模型、Skill 和其他资源必须随包、随离线制品或随明确声明的本地离线源提供；
- offline 缺少某个可选在线能力时，必须在 `check` 和运行输出中标注 `degraded`，不能伪报为完整能力；
- 在 `ci/agent.json` 中声明 `variants` 和 `defaultVariant`。

当前主发布包名为：

```text
witty-agent-<id>-online
witty-agent-<id>-offline
```

组织包名暂定为 `@openeuler/agent-<id>-online` 和
`@openeuler/agent-<id>-offline`，只有在组织 npm scope 可用并完成发布审批后才启用。两个变体必须能从包名、`package.json` 和 `check` 输出中明确识别，不能只依赖构建目录名区分。

### 4.3 打包期资源封装

Skill 是否存在于源码仓库不是发布前提；**最终打包制品中存在完整 Skill 才是发布前提**。`pack:variant` 或等价的构建流程 MUST 在生成 tarball 前完成资源封装：

1. 读取 Agent 声明的 Skill、Python、npm、模型和其他运行时依赖清单。
2. 优先从 [openEuler SkillHub](https://skillhub.openeuler.org/) 拉取固定版本；SkillHub 不可用时使用源码仓库已有的本地 Skill。
3. 将解析后的 Skill 复制到 staging/package 目录，并生成来源、版本和校验记录。
4. 校验 npm tarball 内容，确认每个声明的 Skill 都包含 `SKILL.md` 及其运行所需文件。
5. 对 offline 变体额外封装完整的离线运行环境，再执行无网络安装检查。

构建机在打包 offline 变体时可以联网拉取 Skill 和依赖；“offline”约束针对交付后的安装机和运行机。构建流程必须在制品生成后切换到无网络验证，不能因为构建阶段联网就跳过离线验收。

因此，源码仓库可以采用以下任一种方式：

- 只保存 Skill 清单，打包阶段从 SkillHub 拉取；
- 保存部分或全部本地 Skill，作为打包阶段的 fallback；
- 两者同时存在，但必须按版本和校验规则确定最终制品中的唯一来源。

打包完成后，发布 tarball 不得依赖用户机器在安装时再次下载必需 Skill。

### 4.4 offline 制品的自包含要求

offline 不是“安装时关闭网络”这么简单，而是**发布制品自包含运行环境**。offline 制品 MUST 包含或随离线制品交付：

- 所需 Skill 及其脚本、模板、参考资料和依赖；
- Node/npm 运行所需的包依赖，不能依赖安装时访问 npm registry；
- Python 解释器或可直接使用的 Python 虚拟环境；
- Python 包及 wheel、安装脚本和依赖锁定信息；
- Agent 使用的模型、词典、索引、浏览器/二进制资源等运行时文件；
- 启动、检查和升级所需的本地工具与 manifest。

如果 Python 环境因操作系统或架构不同无法跨平台复用，则必须按支持的平台/架构分别构建 offline 制品。仅提供 `requirements.txt`、`package.json` 或在线安装脚本，不能视为满足离线环境要求。

离线制品仍可以声明系统级前置条件，例如 glibc、bash、GPU 驱动或内核能力；这些条件必须在 README 和 `setup check` 中明确检查，不能在运行时尝试联网补装。

## 5. CLI 生命周期规范

安装和宿主注册必须拆成两个职责独立、可重复执行的命令：

```text
npm install -g <package>
<agent>-setup install
<agent>-configure install --target=opencode
```

### 5.1 `<agent>-setup`

负责本机运行环境准备，不负责修改 OpenCode 注册配置。

MUST 支持：

| 命令 | 语义 |
|---|---|
| `install` | 幂等地准备依赖、运行目录、模型、在线 Skill 或本地 fallback |
| `check` | 只读检查依赖、Skill、配置和运行时完整性 |

以下命令按 Agent 需要提供：

| 命令 | 语义 |
|---|---|
| `start` | 启动后台服务或常驻任务 |
| `stop` | 停止后台服务 |
| `status` | 输出服务/任务状态，优先使用 JSON |
| `run` | 执行一次任务或同步 |
| `init` | 交互式生成用户配置 |

`setup install` 典型步骤：

1. 检查 Node、Python、uv、外部命令和系统架构等前置条件。
2. 创建用户级缓存、虚拟环境、模型目录或运行目录。
3. 准备 Skill：online 先尝试 SkillHub，失败后使用打包进制品的 Skill；offline 只使用打包进制品或指定离线源中的 Skill。
4. 安装或校验后端依赖、MCP、模型和数据目录；offline 只使用制品内的 Python/Node 环境和本地资源，不得访问外部包源。
5. 执行自检，并输出每一步的 `success/partial/skipped/failed` 状态。

安装失败时 MUST 告知具体步骤、影响范围和可用的降级路径；允许降级的 Agent 不能把降级状态伪装成完整安装成功。

### 5.2 `configure.mjs` / `<agent>-configure`

`configure.mjs` 负责把 Agent 注册到对应的宿主代码 Agent，不能承担耗时的依赖安装，也不负责准备 Python/模型/后端等运行环境。

目标优先级：

1. **OpenCode（MUST 优先支持）**：注册插件入口、Agent 提示词和 Skill 链接到 OpenCode 的用户配置目录。
2. **DSH（MAY 支持）**：如果该 Agent 提供 DSH 适配器，则注册到 DSH 对应的 Agent/插件配置；不支持 DSH 时应明确返回 `unsupported target`。
3. **其他宿主（MAY 扩展）**：必须使用独立 target 适配器，不能把不同宿主的配置逻辑混在一起。

MUST 支持：

```text
<agent>-configure install --target=opencode
<agent>-configure remove --target=opencode
<agent>-configure status --target=opencode
```

`--target` 缺省值 MUST 为 `opencode`。支持 DSH 时，命令形式为：

```text
<agent>-configure install --target=dsh
<agent>-configure remove --target=dsh
<agent>-configure status --target=dsh
```

配置器应：

- 按目标宿主的适配器幂等地添加/删除 Agent 注册入口；
- 对 OpenCode，为插件入口、Agent 提示词和 Skill 创建软链接或平台约定的注册关系；
- 对 DSH，只写入 DSH 规定的注册文件或目录，不修改 OpenCode 配置；
- 修改配置前创建备份；
- 不删除不属于本 Agent 的配置；
- `remove` 后不遗留失效的插件路径、Agent 注册项或 Skill 链接；
- `status` 输出目标宿主、注册状态、解析后的路径和版本，优先使用 JSON；
- 目标不支持或宿主未安装时，返回可识别错误并说明安装/启用方法。

`configure.mjs` 的内部结构建议采用目标适配器：

```text
lib/configure/
├── index.mjs
├── opencode.mjs       # 默认、优先实现
└── dsh.mjs            # 可选实现
```

`setup install` 不得代替 `configure install` 注册宿主；用户必须能够只重新执行 configure 来修复注册，而无需重新下载 Skill 或模型。

## 6. Skill 规范：SkillHub 优先，本地兜底

Skill 是 Agent 的可复用能力单元。源码仓库可以不包含 Skill 目录，但每个进入最终 npm/离线制品的 Skill 必须有独立目录和自己的 `SKILL.md`，必要时附带脚本、模板、测试和依赖说明。

### 6.1 来源优先级

默认顺序按变体区分：

1. **online：[openEuler SkillHub](https://skillhub.openeuler.org/) 在线版本（优先）**：获取更新后的公共 Skill，并记录名称、版本、来源和校验结果。
2. **online fallback：Agent 包内本地版本**：SkillHub 不可用、版本不兼容或安全校验失败时使用。
3. **offline：Agent 包内本地版本（唯一默认来源）**：不访问 SkillHub；只使用打包进制品的 Skill 或用户明确指定的本地离线源。
4. **内置降级逻辑**：本地版本也不可用时，Agent 仅执行明确支持的最小能力，并报告降级。

禁止在没有告知用户的情况下用未知来源覆盖本地 Skill。SkillHub 返回的 Skill MUST 经过名称、版本、来源和安全检查；高风险 Skill SHOULD 在安装前执行 vetting。

### 6.2 本地 Skill 目录

```text
skills/
└── <skill-name>/
    ├── SKILL.md
    ├── scripts/
    ├── references/
    ├── assets/
    └── tests/
```

本地 Skill 的 `SKILL.md` MUST 说明：用途、触发条件、输入输出、依赖、权限、失败处理、示例和安全边界。

### 6.3 安装记录

安装器 SHOULD 保存 Skill 安装清单，例如：

```json
{
  "skills": [
    {
      "name": "agent-tools",
      "source": "skillhub",
      "version": "1.2.0",
      "path": "~/.config/opencode/skills/agent-tools",
      "installedAt": "2026-09-22T00:00:00Z"
    }
  ]
}
```

这样 `check`、`remove`、升级和故障排查才能区分 SkillHub 安装内容、源码内 Skill 和打包进制品的 Skill 内容。

## 7. 配置与运行时文件

Agent MUST 区分三类配置：

1. **包内默认配置**：随包发布，升级可覆盖，不写机器专属信息。
2. **用户配置**：位于用户配置目录，升级不丢失。
3. **临时覆盖**：环境变量和命令行参数，仅影响当前命令/进程。

推荐优先级（低到高）：内置默认值 → 包内配置 → 用户配置 → 环境变量 → CLI 参数。

凭证必须来自环境变量、用户配置或安全存储，不能写入 npm 包、`agent.md` 或 Git。

运行时 PID、心跳、日志、状态和临时文件应集中在 Agent 自己的 `.runtime/` 或用户缓存目录中，并在 README 中说明生命周期和清理方式。

## 8. README 必须覆盖的用户流程

每个 Agent 的 README MUST 至少包含：

1. 支持平台和前置依赖；
2. npm 安装命令；
3. `setup install`、`setup check`、`configure install --target=opencode` 的完整步骤；
4. 支持的宿主目标（OpenCode 必须优先说明，DSH 如支持则单独说明）；
5. online/offline 两个变体的安装方式和网络边界；
6. SkillHub 和本地 Skill 的来源及 fallback 行为；
7. 常用命令与参数；
8. 配置项、环境变量和配置优先级；
9. 运行、检查、日志和排障方式；
10. 卸载顺序：停服务 → 按目标反注册 → npm 卸载 → 清理可选缓存；
11. 版本、许可证和已知限制。

推荐统一安装流程：

```bash
npm install -g <published-package>
<agent>-setup install
<agent>-setup check
<agent>-configure install --target=opencode
```

offline 变体的推荐安装流程必须显式体现无网络约束，例如：

```bash
npm install --offline -g ./witty-agent-<id>-offline-<version>.tgz
<agent>-setup install --offline
<agent>-setup check --offline
<agent>-configure install --target=opencode --offline
```

## 9. CI 注册与测试规范

每个 Agent MUST 有 `ci/agent.json`，至少包含：

```json
{
  "schemaVersion": 1,
  "id": "<agent-id>",
  "displayName": "...",
  "directory": "<agent-dir>",
  "changedPathPrefixes": ["<agent-dir>/"],
  "variants": ["online", "offline"],
  "defaultVariant": "online",
  "packageStyles": ["plain"],
  "supportedArchitectures": ["x86_64", "aarch64"],
  "publishRequiresAllVariants": true
}
```

CI 至少应验证：

- `package.json` 和 `agent.md` 存在且字段合法；
- `dist/`、`bin/`、`files` 清单与实际包内容一致；
- online/offline 包能分别构建；
- 打包前即使源码仓库没有 `skills/`，最终 tarball 仍包含声明的全部 Skill；
- offline 包在无网络环境中完成 npm 安装、setup、check、configure 和核心任务；
- offline 包不触发 SkillHub、npm registry、PyPI、远程 Git 或在线模型请求；
- offline 包能够直接使用制品内的 Python/Node 环境和资源，不执行在线依赖安装；
- `setup install/check` 和 `configure install/remove/status` 满足幂等性；
- SkillHub 不可用时本地 fallback 行为符合声明；
- 安装契约测试不修改仓库外无关文件；
- npm tarball 能在干净环境中安装并运行 CLI。

## 10. 新 Agent 最小验收清单

- [ ] 根目录有独立 `<agent-dir>`，并有 `agent.md`。
- [ ] `agent.md` 定义角色、边界、Skill、工具、工作流、安全和输出。
- [ ] `package.json` 有双 CLI：`setup` 与 `configure`。
- [ ] `setup install` 不直接修改 OpenCode 注册配置。
- [ ] `configure.mjs` 是宿主注册的唯一实现入口，默认目标为 OpenCode。
- [ ] `configure install/remove/status` 按 target 幂等并支持备份。
- [ ] DSH 若未实现会明确返回不支持，不会误写 OpenCode 或其他宿主配置。
- [ ] SkillHub 是默认首选来源，并有可测试的本地 fallback。
- [ ] 最终 online/offline 制品都包含声明的全部必需 Skill，即使源码仓库没有 `skills/`。
- [ ] 用户配置、凭证、运行时文件与包内容隔离。
- [ ] 有 README、`ci/agent.json` 和安装契约测试。
- [ ] online/offline 变体均存在，且行为和网络边界明确。
- [ ] plain 是当前主发布样式，安装文档不依赖 organization scope。
- [ ] offline 包的依赖闭包、Skill、模型和本地资源已随包或离线制品交付。
- [ ] offline 包已通过无网络安装和核心运行测试。
- [ ] 能完成“安装 → setup → check → configure → 使用 → remove → 卸载”的完整闭环。

## 11. 一个最小可交付示例

```text
demo-agent/
├── agent.md
├── package.json
├── package-lock.json
├── README.md
├── bin/
│   ├── demo-setup.mjs
│   └── configure.mjs
├── dist/index.js
├── lib/
│   ├── skill-manager.mjs
│   └── opencode-config.mjs
├── skills/
│   └── demo-local-fallback/SKILL.md
├── scripts/
│   ├── validate.mjs
│   ├── validate-dist.mjs
│   └── build-package.mjs
├── tests/test-install-contract.mjs
└── ci/agent.json
```

这个最小 Agent 不一定有后端服务，但必须能通过统一生命周期完成安装、Skill 准备、OpenCode 注册、状态检查和卸载。

## 12. 定稿前还需要补齐的实现级契约

当前规范已经覆盖 Agent 包的主结构，但如果要直接作为团队开发和验收标准，下面几项还需要进一步固定。建议把 P0 项纳入下一版规范，P1 项可以在第一批 Agent 稳定后补充。

### P0：建议在下一版明确

#### 12.1 Agent 运行时清单

`ci/agent.json` 主要服务 CI，不能完全替代运行时元数据。建议增加一个包内清单（例如 `agent.manifest.json`），至少描述：

```json
{
  "schemaVersion": 1,
  "id": "shennong-crash",
  "displayName": "Shennong Crash Agent",
  "prompt": "agent.md",
  "entrypoint": "dist/index.js",
  "targets": ["opencode", "dsh"],
  "defaultTarget": "opencode",
  "variants": ["online", "offline"],
  "skills": ["vmcore-analysis", "crash-report-generator"]
}
```

这样安装器、`configure.mjs`、CI 和文档不需要各自重复维护 Agent ID、入口、目标和 Skill 清单。

#### 12.2 Configure 适配器统一接口

需要固定每个 target adapter 的接口和返回结构，至少包括：

```text
install({ packageRoot, options })
remove({ packageRoot, options })
status({ packageRoot, options })
capabilities
```

`status` 建议统一返回 `target`、`supported`、`configured`、`changed`、`paths`、`version` 和 `reason`。执行 `install/remove` 前应先对所有目标做 preflight；任何一个目标不支持时，不应只修改部分配置。

还需要明确：备份命名、原子写入、JSONC 注释保留、无变化时不生成新备份、只删除本 Agent 自己管理的条目，以及各错误对应的退出码。

#### 12.3 SkillHub 安装协议

目前只规定了“SkillHub 优先”，还需要写死以下内容：

- [openEuler SkillHub](https://skillhub.openeuler.org/) 的 CLI/API 调用方式；
- Skill 名称、命名空间和版本/提交号格式；
- 是否允许浮动版本，默认是否锁定版本；
- 下载缓存、安装清单和锁文件位置；
- 校验和、签名或安全预审要求；
- SkillHub 不可用、版本不兼容、校验失败时的 fallback 条件；
- `online` 与 `offline` 模式下的网络访问边界；offline 必须默认拒绝外部网络；
- offline 包的依赖闭包如何交付：npm 依赖、Python wheel、模型、浏览器/系统资源和 Skill 是否内置；
- offline 包如何在干净机器上安装：完整 tarball、离线 npm cache、wheelhouse 或其他离线制品。

建议把最终解析结果记录为 `skill-lock.json`，避免同一 Agent 在不同机器上安装到不同 Skill 内容。offline 变体必须随包或随离线制品提供该锁文件引用的全部 Skill 内容。

#### 12.4 配置、升级和回滚协议

还应明确每类用户配置的路径、环境变量命名、升级保留策略和回滚规则，特别是：

- OpenCode 配置路径和 `XDG_CONFIG_HOME` 的处理；
- DSH 的 `DSH_HOME`、profile 和注册文件；
- Agent 自己管理的配置标识/owner 字段；
- 升级时如何迁移旧字段；
- 配置写坏时如何从最近一次备份恢复；
- `remove` 是否清理 SkillHub 内容、缓存和用户配置。

#### 12.5 发布包和 CI 门槛

`ci/agent.json` 的正式字段应与当前仓库保持一致，至少考虑纳入：

```json
{
  "driver": "ci/driver.mjs",
  "registryPackages": {
    "online": "witty-agent-<id>-online",
    "offline": "witty-agent-<id>-offline"
  },
  "publishRequiresAllVariants": true
}
```

同时应规定 tarball 必须包含/禁止包含哪些文件，并在干净目录中验证 `npm install`、两个 CLI、online/offline、无网络安装和宿主注册。

### P1：建议随后补充

1. **统一 CLI 体验**：`--help`、`--version`、`--json`、`--non-interactive`、`--dry-run` 和参数错误的退出码。
2. **兼容性矩阵**：Node、操作系统、架构、OpenCode 版本、DSH 版本、Python/uv 版本。
3. **安全模型**：SkillHub 内容的提示注入、恶意脚本、网络权限、外部命令和 MCP 权限边界。
4. **运行状态模型**：`not-installed`、`partial`、`ready`、`degraded`、`running`、`stale`、`failed` 等状态的定义。
5. **可观测性**：日志格式、敏感字段脱敏、请求关联 ID、保留周期和用户可查看位置。
6. **升级与兼容**：旧包名、旧命令别名、旧配置和旧 Skill 链接的迁移/淘汰策略。
7. **责任信息**：维护者、评审人、许可证、SBOM、漏洞响应和发布审批人。

其中最值得优先落地的是 `agent.manifest.json`、configure adapter 接口、SkillHub lockfile，以及安装/注册统一退出码；这四项会直接影响后续自动化和多 Agent 一致性。
