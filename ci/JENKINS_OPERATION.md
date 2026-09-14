# Jenkins 流水线操作指南：从触发到打包发布

本文档覆盖 how to 从 Jenkins 创建/触发流水线，到构建、打包、离线产物、发布 npm 的完整流程，以及 Web 界面操作指导。所有命令与参数均对应仓库内 `Jenkinsfile` 与 `ci/scripts/*` 的真实实现。

---

## 1. 链路概览

```
Jenkins Job → Initialize Parameters → Resolve Build Plan → Prepare Agents
    → Prepare Assets → Install Build Dependencies → Validate Agents
    → Build Packages → Artifact Gates → Install Contract Checks
    → Real Install Flow → Publish to npm → Archive Artifacts
```

- 统一入口：仓库根目录 [Jenkinsfile](../../Jenkinsfile)。
- Agent 配置：每个 Agent 一个 `ci/agent.json`（`id/directory/driver/variants/packageStyles/...`）。
- 驱动脚本：每个 Agent 一个 `ci/driver.mjs`，实现 8 个 phase。
- 当前已启用 4 个 Agent：`shennong-crash`、`nl2sql`、`openeuler-ops`、`xlite-perf-optimizer`。

---

## 2. 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| Jenkins 节点 | openEuler Python 3.11 / 30.9.2 **两套原生节点（x86_64 + aarch64）** | 离线含编译 wheel 的 Agent（shennong、nl2sql）必须原生架构构建，双架构需 x86 与 arm 各一套 |
| 运行镜像 | `shennong-oe2403sp4-acceptance:runtime-v2` | Jenkinsfile 中 agent 直接引用，需上架到节点 |
| Node.js | ≥ 20 | 流水线在 Initialize 阶段强制校验 |
| Python | `python3.11`（含 venv） | 构建/校验 Agent 本地 Python 环境 |
| OCR 模型缓存 | `OCR_MODEL_CACHE_DIR` | 默认 `/home/shennong-jenkins/ocr-model-cache`；Git LFS 不可用时供 shennong 用 |
| npm token | Jenkins Secret Text | 凭据 id 默认 `npm-token`，仅发布阶段读取 |
| 网络 | npm registry + PyPI（默认华为云镜像）可达；离线安装验证用 `unshare`/`ip` | `STRICT_OFFLINE_NETWORK_CHECK=true` 时必需 |

---

## 3. 在 Jenkins Web 上创建 Job

1. 进入 Jenkins → **New Item** → 输入名称（如 `witty-agents-ci`）→ 选择 **Pipeline** → OK。
2. **Pipeline** 区：
   - `Definition`: **Pipeline script from SCM**
   - `SCM`: **Git**，填仓库地址（官方 `gitcode.com/openeuler/witty-agents` 或 `atomgit.com/openeuler/witty-agents`）
   - `Branches to build`: `master`
   - `Script Path`: **`Jenkinsfile`**
3. 保存。

> 双架构发布时，在 **x86_64 节点** 和 **aarch64 节点** 各建一个 Job（或两套 Jenkins 环境），参数 `TARGET_ARCH` 分别设 `x86_64` / `aarch64`。

---

## 4. 参数速查

| 参数 | 取值 | 默认 | 含义 |
|---|---|---|---|
| `AGENT` | `auto`/`all`/Agent id | `auto` | `all` 或具体 id（如 `shennong-crash`） |
| `VARIANT` | `default`/`online`/`offline`/`all` | `default` | 打包内容变体 |
| `PACKAGE_STYLE` | `organization`/`plain` | `organization` | `organization`=scoped `@openeuler/*`；`plain`=非 scoped 个人包 |
| `TARGET_ARCH` | `native`/`x86_64`/`aarch64` | `native` | 离线包架构；`native` 自动按节点 `uname -m` 解析 |
| `PYTHON_BIN` | 字符串 | `python3.11` | 构建/校验用 Python |
| `PYPI_INDEX_URL` | URL | 华为云镜像 | 在线依赖 / 离线 wheel 的索引 |
| `OCR_MODEL_CACHE_DIR` | 路径 | `/home/shennong-jenkins/ocr-model-cache` | OCR 模型缓存 |
| `RUN_REAL_INSTALL_VALIDATION` | bool | `true` | 跑真实安装验证（install→setup×2→configure×2→remove→stop→uninstall） |
| `STRICT_OFFLINE_NETWORK_CHECK` | bool | `true` | 离线 real-install 要求 `unshare` 网络命名空间断网 |
| `PUBLISH` | bool | `false` | 是否发布 |
| `NPM_CREDENTIAL_ID` | 凭据 id | `npm-token` | 含 npm token 的 Secret Text |
| `NPM_REGISTRY` | URL | `https://registry.npmjs.org/` | 仅发布阶段使用 |
| `NPM_DIST_TAG` | 字符串 | `latest` | npm dist-tag |

---

## 5. 触发与运行

**手动触发**：打开 Job → **Build with Parameters** → 选好参数 → **Build**。

**定时/触发**：Jenkinsfile 已配置 `pollSCM('H/5 * * * *')`，自动轮询。

**查看进度**：Job → **Console Output**（Blue Ocean 或 Classic View 均可），可实时看每个 stage 的 `[agent-phase] ==== <Agent>: <phase> ====` 日志。

推荐的试跑参数（先验证一小步）：
- `AGENT=openeuler-ops`（最轻，无 Python 编译依赖）
- `VARIANT=all`，`PACKAGE_STYLE=plain`
- `TARGET_ARCH=native`，`RUN_REAL_INSTALL_VALIDATION=true`
- `PUBLISH=false`

---

## 6. Stage 说明

| Stage | 脚本 | 作用 |
|---|---|---|
| Initialize Parameters | — | 归一整定参数、清理 `ci-artifacts/`、校验 Node≥20 |
| Resolve Build Plan | `resolve-plan.mjs` | 解析受影响的 Agent、变体、架构，产出 `ci-artifacts/build-plan.json` |
| Prepare Agents | `run-agent-phase.mjs --phase=prepare` | 驱动的准备与前置检查 |
| Prepare Assets | `--phase=prepare-assets` | 拉取/校验资产（模型、示例等） |
| Install Build Dependencies | `--phase=install-dependencies` | `npm ci`（+ PKG 缓存），生成 lockfile |
| Validate Agents | `--phase=validate` | 语法/契约校验 |
| Build Packages | `--phase=build` | 调 `build-package.mjs` 打 tgz（online 直接装依赖；offline 预打包 wheel） |
| Artifact Gates | `--phase=artifact-gates` | `verify-ci-artifacts.mjs` 校验包名/架构/体积/清单/体积 |
| Install Contract Checks | `--phase=install-contract` | `test-install-contract.mjs` 幂等安装契约 |
| Real Install Flow | `--phase=real-install` | `verify-package-install.mjs` 真实安装/卸载 |
| Publish to npm | `publish-packages.mjs` | 仅 `PUBLISH=true` 时执行 |
| Archive Artifacts | `post.always` | 归档 `ci-artifacts/**,**/artifacts/**,**/ci-reports/*.json` |

### 打包产物命名（本次已落地架构后缀）

- online：`{base}-online`，如 `witty-agent-nl2sql-online`
- offline：`{base}-offline-{x86_64|aarch64}`，如 `witty-agent-nl2sql-offline-aarch64`

产物位于各 Agent 的 `artifacts/`：

| 产物 | 说明 |
|---|---|
| `<variant>-package-report.json` | 包名、版本、架构、wheel 平台、嫌疑人体积 |
| `*.tgz` | npm 包 |
| `package-variant.json` | 变体元数据 |

---

## 7. 双架构（x86 + arm）

离线含编译 wheel 的 Agent（shennong、nl2sql）需要双架构两份，做法：

1. **x86_64 节点**：Job 参数 `TARGET_ARCH=x86_64` 跑一次；
2. **aarch64 节点**：Job 参数 `TARGET_ARCH=aarch64` 跑一次。

`TARGET_ARCH=native`（推荐）会自动按节点架构解析，无需手工指定。两份 offline tgz 因带架构后缀而互不冲突。

> 架构无关的 Agent（openeuler-ops、xlite）离线包一份通吃，任选一台跑一次即可。
> 说明：当前 Jenkinsfile 的 agent 是固定 `built-in` label 的单节点；若集群只有一个 label，需在 x86 与 arm 两套环境上各建一个 Job（或二选一跑 `native`）。

---

## 8. 发布到 npm

发布是**受控动作**，满足以下几项才执行：

1. `PUBLISH=true`；
2. 提交必须**已包含于 `origin/master`**（`git merge-base --is-ancestor HEAD origin/master`）；
3. 仓库 origin 必须是官方地址（`gitcode.com/openeuler/witty-agents` 或 `atomgit.com/openeuler/witty-agents`，含 https/git@ 形式）；
4. 发布前在 Jenkins **Credentials** 中建好 Recipe 名为 `npm-token`（或改 `NPM_CREDENTIAL_ID`）的 Secret Text，内含 npm token。

发布逻辑（`publish-packages.mjs`）：
- 读取 `build-plan.json`，按 Agent×variant 遍历，校验 `report.packageStyle == plan.packageStyle`；
- 计算本地 tgz 的 sha512 integrity，与 registry 已发布版本比对：一致则跳过（`verified-existing`），不一致则报错，缺失则发布；
- `@` 开头的 scoped 包自动加 `--access public`；plain（非 scoped）默认 public；
- 发布成功生成 `ci-artifacts/publish-summary.json`。

Web 操作：**Build with Parameters** → `PUBLISH=true` → 打开 Console Output，看到 `Published or verified N package(s)` 即成功；到 npm 页面核对包名/版本/integrity。

---

## 9. Web 操作指导（逐步）

1. **登录 Jenkins** → 找到 Job。
2. **创建/编辑**：见第 3 节；改 `Script Path` 指向 `Jenkinsfile`。
3. **配凭据**：管理 Jenkins → Credentials → 新建 Secret Text，id 与 `NPM_CREDENTIAL_ID` 一致。
4. **触发**：Job → Build with Parameters → 设参数 → Build。
5. **看结果**：Job → Build History → 某次 Build → Console Output。
6. **看产物**：该 Build → Artifacts（`ci-artifacts/`、各 `**/artifacts/`、`**/ci-reports/*.json` 已被归档）。
7. **失败定位**：Console Output 里搜 `[agent-phase]` 定位到 Agent，按 `[stage]` 定位到阶段；再读对应 `artifacts/*-package-report.json` / `ci-reports/*.json` 的 `status`/`error`。
8. **发布**：确认 master 已包含本次提交、PUBLISH=true、凭据就绪后重跑。

---

## 10. 不依赖 Jenkins 的手动命令（排障/本地联调）

在任一原生节点上，可在仓库根目录手工等价执行：

```bash
cd witty-agents

export AGENT=openeuler-ops
export VARIANT=all
export PACKAGE_STYLE=plain        # 或 organization（scoped）
export TARGET_ARCH=native
export PYTHON_BIN=python3.11
export PYPI_INDEX_URL=https://mirrors.huaweicloud.com/repository/pypi/simple
export PIP_INDEX_URL=$PYPI_INDEX_URL
export RUN_REAL_INSTALL_VALIDATION=true
export STRICT_OFFLINE_NETWORK_CHECK=true
export PUBLISH=false

# 1) 解析构建计划
node ci/scripts/resolve-plan.mjs \
  --agent="$AGENT" --variant="$VARIANT" --package-style="$PACKAGE_STYLE" \
  --target-arch="$TARGET_ARCH" --publish="$PUBLISH" \
  --output=ci-artifacts/build-plan.json

# 2) 逐阶段执行
for phase in prepare prepare-assets install-dependencies validate build \
             artifact-gates install-contract real-install; do
  node ci/scripts/run-agent-phase.mjs --phase=$phase
done

# 3) 发布（需 NPM_TOKEN 环境变量，且满足第 8 节门槛）
# export NPM_TOKEN=xxxxx
# export NPM_REGISTRY=https://registry.npmjs.org/
# node ci/scripts/publish-packages.mjs --plan=ci-artifacts/build-plan.json
```

产物在 `<agent>/artifacts/`，报告在 `<agent>/ci-reports/`。

---

## 11. 常见问题

| 现象 | 原因/处理 |
|---|---|
| `NPM_TOKEN is required` | 发布阶段未注入 npm token；检查凭据 id 与 `NPM_CREDENTIAL_ID` 是否一致 |
| `Publishing is allowed only from the official repository` | 仓库 origin 非官方地址，改用官方 master 触发 |
| `package name mismatch` | `PACKAGE_STYLE`/`TARGET_ARCH` 与构建时不一致；离线包名已带架构后缀，确保两处一致 |
| `offline: report architecture mismatch` | `verify-ci-artifacts` 读 `TARGET_ARCH` 校验，需与构建时架构一致 |
| `contentComplete=false` / LFS 指针 | shennong OCR 模型未 materialize；确认节点挂载 `OCR_MODEL_CACHE_DIR` 或 `git lfs pull` |
| `offline real-install` 无法断网 | 需 `unshare`/`ip`；或设 `STRICT_OFFLINE_NETWORK_CHECK=false` 降级 |
| `already exists with different content` | registry 已有同版本不同内容的包；改版本或核对构建来源 |

---

## 12. 命令/文件速查

| 用途 | 路径 |
|---|---|
| 流水线定义 | `Jenkinsfile` |
| Agent 注册表 | `ci/agents.json` |
| 解析计划 | `ci/scripts/resolve-plan.mjs` |
| 阶段驱动 | `ci/scripts/run-agent-phase.mjs` |
| 发布 | `ci/scripts/publish-packages.mjs` |
| 打包 | `<agent>/scripts/build-package.mjs` |
| 门禁 | `<agent>/scripts/verify-ci-artifacts.mjs` |
| 契约/安装 | `<agent>/tests/test-install-contract.mjs`、`<agent>/scripts/verify-package-install.mjs` |