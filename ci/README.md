# Witty Agents 仓库级 Jenkins Pipeline

新服务器从零部署 Jenkins、自动创建 Job，以及 Jenkins 如何读取本仓库的完整说明见
[`ci/jenkins/README.md`](jenkins/README.md)。

## 1. 当前能力

仓库根目录的 `Jenkinsfile` 是统一入口。它负责：

```text
SCM/人工触发
→ 解析受影响 Agent
→ 调用 Agent 自己的 CI driver
→ 构建与产物门禁
→ 安装契约和真实安装验证
→ 归档
→ 可选 npm 发布
```

当前 `ci/agents.json` 中只有 `shennong-crash` 已启用。NL2SQL、openEuler Ops 和 XLite
均已按仓库目录登记但明确禁用；它们还没有完成统一 CI 契约。手工选择或自动检测到这些
目录发生变更时，Pipeline 会在 Resolve Build Plan 阶段给出明确错误，不会用无关 Agent
的绿色结果掩盖未验证改动。

## 2. Jenkins 如何读取代码仓

Jenkins 不会读取操作者手工进入的本地目录。Job 通过 SCM 配置与 Git 仓库建立关联，
每次构建时自动将目标分支 checkout 到 Jenkins 管理的 workspace，再读取该版本中的
根目录 `Jenkinsfile`。

```text
Job 的 Pipeline from SCM 配置
→ Repository URL 确定仓库
→ Branch Specifier 确定分支
→ Script Path 定位 Jenkinsfile
→ Jenkins 自动 checkout 到 workspace
→ 执行 Jenkinsfile
```

仓库服务器上第一次执行 `git clone`，只是为了取得 `ci/jenkins/` 中的部署文件；Jenkins
服务启动后，Job 会独立通过 SCM 拉取构建代码，不依赖这份初始化 clone 目录。

### 手工创建 Job

Job 推荐名称为 `witty-agent-package-ci`，类型使用 **Pipeline script from SCM**：

| 配置 | 值 |
|---|---|
| Repository URL | 当前联调 fork；正式发布必须切官方 `openeuler/witty-agents` |
| Branch Specifier | CI 联调分支 |
| Script Path | `Jenkinsfile` |
| Lightweight checkout | 可开启 |

新服务器使用 `ci/jenkins/bootstrap.sh` 时，上述 Job 和 SCM 字段会自动创建，无需再次
手工填写。仓库、分支和可选 Git 凭据 ID 从 `ci/jenkins/.runtime.env` 读取。

不要再把新 Job 的 Script Path 设置为 `Jenkinsfile.shennong`；该文件仅作为旧版
Shennong 专用基线保留。

从旧 Jenkinsfile 首次切换时，页面可能仍只显示旧参数。保存 Script Path 后先点一次
**Build Now**：新版 Pipeline 会按安全默认值执行 `auto + online + organization +
PUBLISH=false`，同时把新参数登记到 Job。第一次结束后再进入 **Build with Parameters**，
即可看到 `AGENT`、`PACKAGE_STYLE` 和 `TARGET_ARCH` 等新参数。

根 Jenkinsfile 自带 `pollSCM('H/5 * * * *')`，每五分钟检查一次 SCM；页面仍可通过
**Build with Parameters** 手工触发。

## 3. 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `AGENT` | `auto` | 填 `auto`、`all` 或 `ci/agents.json` 中登记的 Agent ID；手工联调建议填 `shennong-crash` |
| `VARIANT` | `default` | Shennong 的 default 是 online；也可选 online/offline/all |
| `PACKAGE_STYLE` | `organization` | `organization` 为 `@openeuler/*`，`plain` 为普通 npm 包 |
| `TARGET_ARCH` | `native` | 使用当前原生节点；离线包不允许跨架构冒充 |
| `PYTHON_BIN` | `python3.11` | 支持 Python 3.11/3.12 |
| `PYPI_INDEX_URL` | 华为云 PyPI 镜像 | online setup 和 offline wheel 构建使用的索引；必要时可切回官方源 |
| `OCR_MODEL_CACHE_DIR` | `/srv/witty-agents-jenkins/ocr-model-cache` | LFS 服务不可用时的可信 OCR 缓存 |
| `RUN_REAL_INSTALL_VALIDATION` | `true` | 运行完整安装、setup、configure、remove 和卸载 |
| `STRICT_OFFLINE_NETWORK_CHECK` | `true` | offline 必须进入断网 namespace |
| `PUBLISH` | `false` | 是否发布；联调阶段不要勾选 |
| `NPM_CREDENTIAL_ID` | `npm-token` | Jenkins Secret Text 凭据 ID |
| `NPM_REGISTRY` | npm 官方源 | 发布目标 |
| `NPM_DIST_TAG` | `latest` | npm dist-tag |

`VARIANT` 与 `PACKAGE_STYLE` 是不同维度：前者决定包内容，后者决定 npm 名称。

| PACKAGE_STYLE | online 包名 | offline 包名 |
|---|---|---|
| organization | `@openeuler/agent-shennong-crash-online` | `@openeuler/agent-shennong-crash-offline` |
| plain | `openeuler-agent-shennong-crash-online` | `openeuler-agent-shennong-crash-offline` |

## 4. 推荐的首次手工联调顺序

所有联调构建都保持 `PUBLISH=false`。

### 第一次：组织在线包

```text
AGENT=shennong-crash
VARIANT=online
PACKAGE_STYLE=organization
TARGET_ARCH=native
RUN_REAL_INSTALL_VALIDATION=true
STRICT_OFFLINE_NETWORK_CHECK=true
PUBLISH=false
```

预期：在线包小于 10 MiB，安装/setup/configure/卸载全部通过。

### 第二次：普通在线包

只修改：

```text
PACKAGE_STYLE=plain
```

预期：产物名为 `openeuler-agent-shennong-crash-online`，重复 configure 不重复写配置，
remove 只移除 Shennong 注册。

### 第三次：组织离线包

```text
AGENT=shennong-crash
VARIANT=offline
PACKAGE_STYLE=organization
TARGET_ARCH=native
RUN_REAL_INSTALL_VALIDATION=true
STRICT_OFFLINE_NETWORK_CHECK=true
PUBLISH=false
```

预期：记录包体积、wheel 数、OS/CPU/Python ABI；真实安装在断网 namespace 中通过。

### 第四次：双包联调

```text
AGENT=shennong-crash
VARIANT=all
PACKAGE_STYLE=organization
TARGET_ARCH=native
RUN_REAL_INSTALL_VALIDATION=true
STRICT_OFFLINE_NETWORK_CHECK=true
PUBLISH=false
```

预期：online/offline 在同一构建中全部通过并同时归档。

普通包的 offline/all 可以在前三次成功、团队确认普通包名称后补跑。

## 5. 如何判断构建成功

Jenkins 最终状态必须是绿色 `SUCCESS`，并确认这些 stage 通过：

1. `Resolve Build Plan`
2. `Prepare Agents`
3. `Prepare Assets`
4. `Install Build Dependencies`
5. `Validate Agents`
6. `Build Packages`
7. `Artifact Gates`
8. `Install Contract Checks`
9. `Real Install Flow`

联调时 `Publish to npm` 显示 skipped 是正常的，因为 `PUBLISH=false`。

Artifacts 中应包含：

- `ci-artifacts/build-plan.json`
- `<agent>/artifacts/*.tgz`
- `<agent>/artifacts/*-package-report.json`
- `<agent>/artifacts/*-npm-pack.json`
- `<agent>/artifacts/ci-summary.json`
- `<agent>/ci-reports/install-flow-*.json`

重点查看：

- `packageName` 与 `PACKAGE_STYLE` 一致；
- `contentComplete=true`；
- online 的 `onlineSizePassed=true`；
- offline 的 `pythonDependencyClosureVerified=true`；
- `install-flow` 中 setup/configure/remove 幂等均为 true；
- offline 的 `networkIsolation` 为 `unshare` 或 `user-netns`。

## 6. 发布流程

首次联调禁止勾选 `PUBLISH`。正式发布前必须确认：

1. Job 的 SCM 已切到官方 `openeuler/witty-agents`；
2. 当前 commit 已进入官方 `master`；
3. `VARIANT=all`；
4. 选择并确认一种 `PACKAGE_STYLE`；
5. `npm-token` 有对应组织包或普通包的发布权限；
6. 构建和真实安装全部通过。

发布器从产物报告读取真实包名，不在 Jenkinsfile 中硬编码 Shennong 包名。已存在的同
版本只有在 registry SHA-512 integrity 与本次 tgz 完全一致时才跳过；内容不同会失败，
不会覆盖。

## 7. 新增 Agent 的方式

新增 Agent 不复制、也不修改 Jenkinsfile。需要：

1. Agent 自己具备可独立执行的构建、打包和验证命令；
2. 在 Agent 目录增加 `ci/agent.json` 和标准 `ci/driver`；
3. 在根 `ci/agents.json` 白名单登记并启用；
4. 输出统一的 package report 和 install-flow report；
5. 先以 `PUBLISH=false` 跑通，再评审发布权限。

NL2SQL 当前未满足第 1 项，因此只登记状态、不启用构建。

## 8. 架构边界

当前 Jenkins 节点为 openEuler x86_64，因此可以生成正式 x86_64 offline 包。
aarch64 offline 包必须在原生 openEuler aarch64 Jenkins 节点构建。`TARGET_ARCH=aarch64`
不会让 x86 节点模拟 ARM；它会明确失败，防止错误标记产物。

同一 npm 包名和版本不能发布两份内容不同的架构包。双架构正式发行前，需要团队确定：

- 只发布一个官方目标架构；或
- 使用带架构后缀的子包，再提供统一元包。

## 9. 回滚

新 Pipeline 不删除旧 `Jenkinsfile.shennong`。若首次联调异常，将 Job 的 Script Path
临时改回 `Jenkinsfile.shennong` 即可恢复旧版 Shennong 专用流程；构建记录和产物不受影响。
