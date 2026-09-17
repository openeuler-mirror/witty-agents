# 07 · 流水线集成规范

本文件是平台与真实流水线之间的"接口契约"。平台所有展示与校验，都必须能在此找到依据；**任何与本文件冲突的旧文档，以仓库代码为准**。

## 1. 上游事实清单

| 文件 | 作用 | 平台用途 |
| --- | --- | --- |
| `Jenkinsfile` | 仓库级流水线定义：11 阶段、14 参数、options、triggers、归档规则 | 阶段模板、参数定义、触发接口的依据 |
| `ci/agents.json` | Agent 注册表（白名单 + 启用状态 + 增量前缀） | Agent 列表与启用状态 |
| `<agent>/ci/agent.json` | 单个 Agent 的能力与打包元数据 | 变体、包风格、架构、registry 包名 |
| `<agent>/package.json` | 版本号与包描述 | Agent 展示版本 |
| `ci/scripts/resolve-plan.mjs` | 生成 `ci-artifacts/build-plan.json` | 构建计划报告 |
| `ci/scripts/run-agent-phase.mjs` | 8 个 phase 的统一驱动 | 阶段 → phase 映射 |
| `ci/scripts/publish-packages.mjs` | 正式发布与版本冲突自动 bump | 发布结果与 bump 记录 |
| `ci/jenkins/Jenkinsfile.online-publish-smoke` | 发布冒烟流水线 | Smoke Job 通道 |
| `ci/scripts/publish-smoke-package.mjs` | 候选包生成 / 发布 / 可见性等待 / 回下载 / 哈希比对 | 发布链路证据 |
| `ci/lib/registry-package.mjs` | registry 候选包生成与校验 | 同上 |
| `ci/JENKINS_OPERATION.md`、`ci/README.md`、`ci/jenkins/README.md` | 操作说明 | 平台"文档"入口（注意见 §9） |

## 2. 流水线 11 阶段

来自 `Jenkinsfile` 的真实定义（顺序即执行顺序）：

| # | 阶段 | 执行体 | 条件 | 失败影响 | 平台展示要点 |
| --- | --- | --- | --- | --- | --- |
| 1 | Initialize Parameters | 内联 shell | 总是 | 构建失败 | 展示归一整定的 14 个参数与 Node 版本校验 |
| 2 | Resolve Build Plan | `ci/scripts/resolve-plan.mjs` | 总是 | 构建失败 | 展示 `build-plan.json`：命中/跳过的 Agent 与原因 |
| 3 | Prepare Agents | `--phase=prepare` | 总是 | 构建失败 | 展示注册的 Agent |
| 4 | Prepare Assets | `--phase=prepare-assets` | 总是 | 构建失败 | 展示 LFS / OCR 缓存命中情况 |
| 5 | Install Build Dependencies | `--phase=install-dependencies` | 总是 | 构建失败 | 依赖安装耗时 |
| 6 | Validate Agents | `--phase=validate` | 总是 | 构建失败 | 契约校验结果 |
| 7 | Build Packages | `--phase=build` | 总是 | 构建失败 | 产物名、大小 |
| 8 | Artifact Gates | `--phase=artifact-gates` | 总是 | **构建失败** | 门禁项与失败原因（最常见失败阶段） |
| 9 | Install Contract Checks | `--phase=install-contract` | 总是 | 构建失败 | 幂等安装契约 |
| 10 | Real Install Flow | `--phase=real-install` | `RUN_REAL_INSTALL_VALIDATION=true` | 构建失败 | setup/configure/remove 幂等结果 |
| 11 | Publish to npm | `publish-packages.mjs` | `PUBLISH=true` | 构建失败 | 发布动作、bump、integrity |

配套的 pipeline 级配置（平台需在"项目设置/健康度"中体现）：

```groovy
options {
  timestamps()                                // 日志带时间戳 → 平台剥离 ANSI 后保留时间
  disableConcurrentBuilds()                   // 同时只允许一个构建 → 平台触发需提示"将进入队列"
  buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '10'))
  timeout(time: 240, unit: 'MINUTES')         // 平台侧 stale 判定阈值
}
triggers { pollSCM('H/5 * * * *') }           // 平台需区分"自动触发"与"人工触发"
```

运行环境（平台"系统状态"卡片需展示）：

```text
agent: docker { image 'witty-agents-ci-runtime:oe2403sp4-node20-py311', label 'built-in' }
args : --user 0:0 --cap-add SYS_ADMIN --cap-add NET_ADMIN --security-opt seccomp=unconfined
       -v /home/witty-agents-jenkins/cache/npm:/root/.npm
       -v /home/witty-agents-jenkins/cache/pip:/root/.cache/pip
       -v /home/witty-agents-jenkins/ocr-model-cache:/home/witty-agents-jenkins/ocr-model-cache:ro
archive: ci-artifacts/**, **/artifacts/**, **/ci-reports/*.json （fingerprint）
post  : chown -R 1000:1000 $WORKSPACE
```

## 3. 流水线 14 参数

平台表单、校验与快照均以此为准（类型与取值域由 Jenkinsfile 决定，平台不得放宽）：

| # | 参数 | 类型 | 默认值 | 平台分组 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 1 | `AGENT` | string | `auto` | 1 构建范围 | `auto` / `all` / `<agent id>`；平台用"模式"卡片映射 |
| 2 | `VARIANT` | choice | `default` | 2 变体与架构 | `default` / `online` / `offline` / `all` |
| 3 | `PACKAGE_STYLE` | choice | `organization` | 2 变体与架构 | `organization` → `@openeuler/*`；`plain` → 非 scoped |
| 4 | `TARGET_ARCH` | choice | `native` | 2 变体与架构 | offline 必须与原生节点架构一致 |
| 5 | `PYTHON_BIN` | string | `python3.11` | 高级 | — |
| 6 | `PYPI_INDEX_URL` | string | `https://mirrors.huaweicloud.com/repository/pypi/simple` | 高级 | 同时作为 `PIP_INDEX_URL` |
| 7 | `OCR_MODEL_CACHE_DIR` | string | `/home/witty-agents-jenkins/ocr-model-cache` | 高级 | LFS 不可用时的模型来源 |
| 8 | `RUN_REAL_INSTALL_VALIDATION` | boolean | `true` | 3 验证 | 控制阶段 10 |
| 9 | `STRICT_OFFLINE_NETWORK_CHECK` | boolean | `true` | 3 验证 | offline 断网命名空间强校验 |
| 10 | `PUBLISH` | boolean | `false` | 发布（仅项目管理员） | 控制阶段 11；需官方 master |
| 11 | `NPM_CREDENTIAL_ID` | string | `npm-token` | 发布 | Jenkins Secret Text 的**ID**，不是 Token |
| 12 | `GIT_CREDENTIAL_ID` | string | 空 | 发布 | 留空则 bump 提交只留在 workspace |
| 13 | `NPM_REGISTRY` | string | `https://registry.npmjs.org/` | 发布 | — |
| 14 | `NPM_DIST_TAG` | string | `latest` | 发布 | **平台必须拦截 `latest`**（见 §5.4） |

## 4. 注册表与 Agent 元数据

### 4.1 `ci/agents.json`

```json
{
  "schemaVersion": 1,
  "agents": [
    { "id": "shennong-crash", "enabled": true,
      "configPath": "shennong-crash-agent/ci/agent.json",
      "changedPathPrefixes": ["shennong-crash-agent/"] }
  ]
}
```

- `enabled=false` 的 Agent 不参与增量构建；该字段只在仓库修改，平台只读同步、不提供启停入口。
- 仓库唯一事实源；平台只做投影，不做本地覆盖。

### 4.2 `<agent>/ci/agent.json`

```json
{
  "schemaVersion": 1,
  "id": "shennong-crash",
  "displayName": "Shennong Crash Agent",
  "directory": "shennong-crash-agent",
  "driver": "ci/driver.mjs",
  "changedPathPrefixes": ["shennong-crash-agent/"],
  "variants": ["online", "offline"],
  "defaultVariant": "online",
  "packageStyles": ["organization", "plain"],
  "supportedArchitectures": ["x86_64", "aarch64"],
  "registryPackages": { "online": "witty-agent-shennong-online" },
  "publishRequiresAllVariants": true
}
```

平台校验规则（触发前就地提示，不依赖构建失败）：

- `PACKAGE_STYLE` 必须在 `packageStyles` 内；
- `TARGET_ARCH` 必须在 `supportedArchitectures` 内；
- `VARIANT` 必须在 `variants` 内（除 `default` 由 `defaultVariant` 解析）；
- `PUBLISH=true` 且 `publishRequiresAllVariants=true` → `VARIANT` 必须为 `all`。

### 4.3 `build-plan.json`

```json
{
  "schemaVersion": 1,
  "status": "ready",
  "sourceCommit": "6cdfd81aeea99185259aa4223f5c7dcede68233f",
  "requestedAgent": "auto",
  "requestedVariant": "default",
  "packageStyle": "organization",
  "targetArchitecture": "native",
  "publish": false,
  "changeDetection": "…",
  "agents": [ { "id": "shennong-crash", "variants": ["online"], "…": "…" } ],
  "generatedAt": "2026-09-15T12:48:10.000Z"
}
```

`status` 取值 `ready` / `no-relevant-changes`；后者表示增量构建未命中任何 Agent（阶段 3–11 会被跳过）。平台需把这种情况显示为"无相关变更（正常结束）"，而不是失败。

## 5. 发布门禁（REL-01）

平台预检必须与 Jenkinsfile 的实际判断语义一致，不允许"平台通过但 Jenkins 拒绝"。

### 5.1 项 1 · 官方仓库白名单

```groovy
case "$origin_url" in
  https://gitcode.com/openeuler/witty-agents|https://gitcode.com/openeuler/witty-agents.git|\
  https://atomgit.com/openeuler/witty-agents|https://atomgit.com/openeuler/witty-agents.git|\
  git@gitcode.com:openeuler/witty-agents.git|git@atomgit.com:openeuler/witty-agents.git) ;;
  *) echo "Publishing is allowed only from the official repository, got: $origin_url" >&2; exit 1 ;;
esac
```

平台预检取当前绑定 Job 最近一次成功构建所检出的仓库地址，与同一白名单比对。**实践提示**：当前两个 Job 仍指向个人 fork（`atomgit.com/cui-gaoleng/witty-agents.git`），因此该项会显示为 fail —— 这正是平台要暴露的问题，而不是平台缺陷。

### 5.2 项 2 · commit 必须包含于 `origin/master`

```groovy
git fetch --no-tags origin master
git merge-base --is-ancestor HEAD refs/remotes/origin/master || {
  echo 'Publishing is allowed only for a commit contained in origin/master.' >&2; exit 1
}
```

平台侧等价实现：调用 Git 平台 API 校验 commit 是否在 `master` 祖先链中（或缓存 `master` 的提交图做本地判定）。

### 5.3 项 3 · 全部本地产物变体通过

- `agent.json` 的 `publishRequiresAllVariants=true`（如 shennong-crash）→ `VARIANT` 必须为 `all`，且该构建的每个变体报告 `ci-summary.json.status=passed`；
- 平台从 `build_reports(kind=ci_summary)` 读取，而不是解析日志。

### 5.4 项 4 / 项 5 · 版本未占用 与 dist-tag 安全

`NPM_DIST_TAG` 的默认值是 `latest`，这是流水线里最危险的一个默认值。平台策略：

1. **前端拦截**：表单中填 `latest` 直接报错并给出替代值；
2. **后端兜底**：触发接口收到 `NPM_DIST_TAG=latest` 且 `PUBLISH=true` → 返回 422 `E_GATE_FAILED`；
3. **预检可见**：预检第 5 项展示当前 `latest` 指向，并在发布后比对是否被改动。

### 5.5 平台预检 vs Jenkins 执行

```text
平台预检（只读，可反复执行）   → 不产生副作用，用于"能不能发布"的判断
Jenkins Publish 阶段（执行）  → 真正的写操作，仍以 Jenkins 内部判断为准
```

两者是"预检—复核"关系，不是替代关系。若 Jenkins 拒绝而平台预检通过，说明平台预检缺少一条规则，需补规则并记录到本文件。

## 6. dist-tag 策略与发布冒烟流水线

### 6.1 dist-tag 约定

| dist-tag | 用途 | 由谁设置 | 平台行为 |
| --- | --- | --- | --- |
| `x86-test` | x86_64 冒烟发布 | smoke 流水线按架构自动设置 | 展示、记录历史 |
| `arm-test` | aarch64 冒烟发布 | 同上 | 展示、记录历史 |
| `latest` | 正式默认版本 | **任何自动流程都不得修改** | 监控漂移，改动即高危告警 |

### 6.2 smoke 流水线（`ci/jenkins/Jenkinsfile.online-publish-smoke`）

特性（平台需在发布详情中呈现）：

- 只接受 Shennong 的 unscoped online 本地产物，发布时转换为 `witty-agent-shennong`；
- 版本必须是 prerelease（如 `0.10.6-ci.aarch64.0`）；
- dist-tag 不能是 `latest`，由流水线按架构自动设置（`x86-test` / `arm-test`）；
- 发布前后核对 `latest`，若首次发布导致 npm 自动创建 `latest`，脚本会移除并确认恢复；
- 链路：生成 registry 候选包 → publish → 等待可见 → 真实回下载 → SHA-256 比对；
- 结果落盘：`ci-artifacts/npm-publish-smoke-summary.json`、`ci-artifacts/npm-download/`。

`npm-publish-smoke-summary.json` 关键字段（平台必须解析）：

```json
{
  "status": "passed",
  "action": "published",
  "packageName": "witty-agent-shennong",
  "version": "0.10.6-ci.aarch64.0",
  "distTag": "arm-test",
  "latestTag": { "action": "preserved", "before": "0.10.5-ci.x86-64.0", "after": "0.10.5-ci.x86-64.0" },
  "builtOnArchitecture": "aarch64",
  "sourceSha256": "…", "registrySha256": "…", "downloadedSha256": "…",
  "integrity": "sha512-…",
  "verifiedAt": "2026-09-14T08:37:47.643Z"
}
```

平台据此渲染发布详情：`latestTag.action=preserved` → 绿色"latest 未被改动"；`sourceSha256 ≠ downloadedSha256` → 红色"待人工核查"，并开放复核重试（REL-07）。

## 7. 版本冲突自动 bump

主 Job 的 Publish 阶段在遇到"版本已存在且内容不同"时会自动 bump patch 版本、重建并重发（`publish-packages.mjs`）。是否把 bump 提交推回远端取决于 `GIT_CREDENTIAL_ID`：

| `GIT_CREDENTIAL_ID` | 行为 | 平台展示 |
| --- | --- | --- |
| 留空 | bump 只发生在 workspace，远端仓库版本不变 | 黄色提示"版本 bump 未推回仓库，下次构建会再次冲突" |
| 已配置 | bump 提交推回源分支 | 展示 bump 前后版本与推送结果 |

平台需在发布详情中显式呈现这条信息，避免"发出去的版本和仓库里的版本不一致"却不自知。

## 8. 报告 JSON 清单

平台 `ReportDigester` 需要处理的文件与关键字段：

| 文件 | `kind` | 关键字段 | 用途 |
| --- | --- | --- | --- |
| `ci-artifacts/build-plan.json` | `build_plan` | `status`, `sourceCommit`, `agents[]`, `publish` | 构建计划卡片 |
| `<agent>/artifacts/ci-summary.json` | `ci_summary` | `status`, `variant` | 变体总体结论、门禁 3 |
| `<agent>/artifacts/*-package-report.json` | `package_report` | `packageName`, `version`, `sizeBytes`, `sha256`, `gates` | 产物卡、体积门禁 |
| `<agent>/artifacts/*-npm-pack.json` | `npm_pack` | `filename`, `files[]`, `size` | npm 打包明细 |
| `<agent>/ci-reports/install-flow-*.json` | `install_flow` | `status`, `setupIdempotent`, `configureIdempotent`, `removeIdempotent` | 安装链路卡片 |
| `ci-artifacts/npm-publish-smoke-summary.json` | `publish_smoke` | 见 §6.2 | 发布链路卡片 |
| `ci-artifacts/publish-summary.json` | `publish_summary` | `packages[]`, `versionBumps[]` | 正式发布结果 |

解析失败不阻塞：`build_reports.parse_error` 记录原因，UI 提供"查看原始文件"。

## 9. 采集映射与刷新频率

| 平台数据 | 上游 | 触发方式 | 频率 |
| --- | --- | --- | --- |
| Agent 注册与元数据 | `ci/agents.json` + `agent.json` + `package.json`（master） | 定时 + 手动 | 10 min |
| 构建列表与状态 | Jenkins Job API | 定时 | 30 s（有运行中构建 5 s） |
| 阶段列表 | Jenkins `wfapi/describe` | 构建结束时 | 一次性 |
| 日志 | `consoleText` / `progressiveText` | 结束 / SSE 订阅 | 3 s |
| 归档产物清单 | Jenkins build API | 构建结束时 | 一次性 |
| 报告 JSON | Jenkins artifact | 构建结束时 | 一次性 |
| 版本与 dist-tags | npm registry | 定时 | 5 min（发布期间 10 s） |
| 系统状态（执行器、队列） | Jenkins `/computer`、`/queue` | 定时 | 60 s |

## 10. 真实环境基线（可作为集成测试夹具）

> 以下为 2026-09-17 在 ARM64 节点实测所得，建议直接做契约测试的期望值。

### 主 Job `witty-agents-builder`

```text
仓库   : https://atomgit.com/cui-gaoleng/witty-agents.git
分支   : */ci/witty-agents-package-pipeline-v1
Script : Jenkinsfile
构建   : #21 SUCCESS（2026-09-15 20:48，1 分 26 秒）checkout 6cdfd81
归档   : 4 个 Agent 的 online 包 + build-plan/ci-summary/install-flow 报告
参数   : AGENT=auto, VARIANT=default, PACKAGE_STYLE=organization,
         TARGET_ARCH=native, PUBLISH=false, NPM_DIST_TAG=latest(默认未改)
触发   : #16–#21 全部为 "Started by an SCM change"
```

### Smoke Job `witty-agents-online-publish-smoke-arm`

```text
#13 SUCCESS（2026-09-14 16:31）→ 发布 witty-agent-shennong@0.10.6-ci.aarch64.0 / arm-test
latest 发布前后均为 0.10.5-ci.x86-64.0（action=preserved）
源包 SHA-256 = 回下载 SHA-256（c79423c47393d930e03fd8f70f6dfe231112d6bd630004afd60ede0bcde17b59）
```

### npm registry 现状（发布监控的初始状态）

```text
versions : 0.10.5-ci.x86-64.0, 0.10.5-ci.aarch64.0, 0.10.6-ci.aarch64.0
dist-tags: latest  → 0.10.5-ci.x86-64.0   ← 历史遗留，仍指向测试版本
           x86-test→ 0.10.5-ci.x86-64.0
           arm-test→ 0.10.6-ci.aarch64.0
```

平台上线后，工作台应长期显示一条待办："`latest` 仍指向测试版本 `0.10.5-ci.x86-64.0`，需团队确认正式版本后再切换。"（这是移交遗留项，不是平台可自动修复的问题。）

## 11. 已知偏差与注意事项

| 偏差 | 说明 | 平台应对 |
| --- | --- | --- |
| Job 命名不统一 | 运维手册建议的主 Job 名为 `witty-agent-package-ci`，实际为 `witty-agents-builder` | 平台按"绑定配置"读 Job 名，不做硬编码；设置页提示与手册不一致 |
| 仍指向 fork 分支 | 两个 Job 都指向 `cui-gaoleng` 的 fork | 预检项 1 会 fail；工作台提供"仓库绑定待切换"待办 |
| 文档与代码不一致 | `ci/JENKINS_OPERATION.md` 写的运行镜像是 `shennong-oe2403sp4-acceptance:runtime-v2`，实际为 `witty-agents-ci-runtime:oe2403sp4-node20-py311` | 平台展示"实际值来自 Jenkinsfile"，并在设置页标注文档待更新 |
| 原型 mock 与仓库不一致 | 原型称 `xlite-perf-optimizer` 已禁用，实际 `enabled: true` | 一律以 `ci/agents.json` 为准 |
| 构建日志含 ANSI | 真实日志被 `timestamps()` 与高亮包裹 | 服务端剥离后再入库（见 03 §3.2） |
| `latest` 历史遗留 | 首次公开发布时由 npm 自动创建 | 平台监控但不自动改；作为长期待办展示 |
| Jenkins 首页存在无关红 Job | `witty-ub-build` 等每日失败 | 平台只纳管绑定 Job，不展示无关 Job 的红色状态 |
| 测试环境未安装 `pipeline-stage-view` | wfapi 当前返回 404 | 按 §12.1 补齐插件；未补齐前平台走日志解析降级 |
| 测试环境授权为 `FullControlOnceLoggedIn` | 服务账号实为完全控制（含 Administer） | 按 §12.2 切换 Matrix 授权；属 Jenkins 侧整改 |
| 测试环境 Jenkins 暴露 `0.0.0.0:8080` | 与 §12.3 基线不符 | 全新部署按基线执行；测试环境列入运维整改 |

## 12. Jenkins 基线前提（全新部署必须满足）

平台假设上游 Jenkins 满足以下基线。本节面向"独立全新部署"的目标状态编写，不以任何既有测试环境的现状为依据；全新部署（`ci/jenkins/bootstrap.sh`）应把本节固化为自动化配置，部署后由 `scripts/smoke-jenkins.ts` 逐项校验并输出报告。

### 12.1 插件

| 插件 | 用途 | 缺失影响 |
| --- | --- | --- |
| `pipeline-stage-view` | 提供 `wfapi/describe` REST 端点（阶段视图主路径，见 [03](03-backend-design.md) §3.2/§3.3） | wfapi 返回 404，阶段视图降级为 consoleText 解析，UI 明示"降级" |
| `workflow-aggregator`、`docker-workflow`、`credentials-binding`、`timestamper` 等 | Pipeline 本身运行所需 | 无流水线可跑（Jenkins 自身前提） |

注意：`workflow-api` 插件 ≠ wfapi REST 端点，后者由 `pipeline-stage-view` 提供。`ci/jenkins/plugins.txt` 已声明 `pipeline-stage-view`，部署时必须确认实际安装成功（存在插件目录且无 `.jpi.tmp` 残留）。

### 12.2 授权策略（Matrix 最小权限）

Jenkins 授权策略使用 **Matrix-based security**（或以 Role-Based Strategy 插件等价实现），平台服务账号授予且仅授予：

| 权限 | 授予 | 用途 |
| --- | --- | --- |
| Overall/Read | ✔ | API 基础访问 |
| Job/Read | ✔ | 构建、阶段、日志、产物清单读取 |
| Job/Build | ✔ | `buildWithParameters` 触发 |
| Job/Cancel | ✔ | 停止构建 |
| Job/Workspace | ✔ | 产物下载 |
| Run/Replay | 可选（P2） | Replay 失败阶段；未授予时平台隐藏 Replay 入口 |
| Overall/Administer、Job/Configure、Job/Delete、Credentials/* | ✘ | 平台不需要，禁止授予 |

约束与容错：

- 服务账号使用 **API Token**（不使用登录密码）做 HTTP Basic；平台侧加密存储。
- `/queue/api/json` 在 Overall/Read 下可用；`/computer/api/json`（系统状态卡）在最小矩阵下可能不可用，平台必须降级为隐藏该卡片而不是报错。
- 禁止采用 `FullControlOnceLoggedIn`（登录即完全控制）作为正式授权策略——它只允许作为联调期临时手段，重新部署时必须纠正。
- 平台自身的写操作集合恒等于 {触发、取消、Replay}；即使账号被错误授予了更高权限，平台也不得调用任何配置类端点。

### 12.3 网络暴露

Jenkins 仅监听 `127.0.0.1` 或内网地址，外部访问经 SSH 隧道或前置反向代理 + 认证；不直接暴露到公网。factory-web 沿用同一风格（[08](08-deployment-and-repo-layout.md) §3）。

### 12.4 校验

`scripts/smoke-jenkins.ts` 输出：Job 可达 / 参数定义一致 / wfapi 可用（明示主路径或降级）/ 服务账号权限符合矩阵（无 Administer）/ 最近构建与归档可读 / 监听地址符合 §12.3。任一项不满足则打印指向本节的修复指引。
