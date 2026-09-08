# Witty Agents Jenkins 服务部署与代码仓接入

本目录用于在一台没有 Jenkins 的服务器上启动通用 Jenkins 服务，并自动创建
`witty-agent-package-ci` Job。适用于首次部署和更换服务器。

## 1. Jenkins 如何读到代码仓

Jenkins 服务和构建代码是两部分：

- `ci/jenkins/` 负责启动 Jenkins、安装插件并创建 Job；
- 仓库根目录 `Jenkinsfile` 负责真正的构建、检查、归档和发布流程。

初始化时执行一次 `git clone`，是为了取得本目录中的部署文件。Jenkins 启动后，不会
把这份 clone 目录直接当作构建目录，而是通过 Job 中的 **Pipeline script from SCM**
配置重新拉取代码：

```text
WITTY_AGENTS_REPO_URL   → Git 仓库地址
WITTY_AGENTS_BRANCH     → 需要构建的分支
WITTY_AGENTS_SCRIPT_PATH → 仓库中的 Jenkinsfile
```

每次构建的数据流为：

```text
Jenkins Job
→ 从 Repository URL 拉取 Branch Specifier 指定的分支
→ 保存到 Jenkins 自动管理的 workspace
→ 从 workspace 读取 Script Path 指定的 Jenkinsfile
→ Jenkinsfile 读取 ci/agents.json
→ 调用目标 Agent 的 ci/driver.mjs
→ 构建、检查、真实安装验证和产物归档
```

因此不需要登录服务器后手工进入某个 Agent 目录再启动构建，也不需要把个人电脑上的
代码路径填写给 Jenkins。

## 2. 服务器准备

服务器需要：

- Linux；
- Docker Engine；
- Docker Compose v2；
- `curl`、`python3`；
- 足够的磁盘空间；
- 流水线运行镜像 `witty-agents-ci-runtime:oe2403sp4-node20-py311`。

流水线运行镜像和 Jenkins Controller 不是同一个镜像：

- `witty-agents-jenkins-controller:lts-jdk21` 提供 Jenkins 页面和调度能力；
- `witty-agents-ci-runtime:oe2403sp4-node20-py311` 提供 openEuler、Node.js、Python 和
  安装验收依赖，真正执行 Agent 构建。

如果服务器已有旧运行镜像，可以在 `.runtime.env` 填写：

```text
WITTY_AGENTS_RUNTIME_IMAGE_SOURCE=<旧镜像名称>
```

`bootstrap.sh` 会为它增加通用标签，不会删除旧标签。若服务器没有可用运行镜像，
Jenkins 仍可启动，但第一次构建会因为找不到运行镜像而失败。

## 3. 从 clone 仓库到启动 Jenkins

### 3.1 拉取仓库

```bash
git clone https://gitcode.com/openeuler/witty-agents.git
cd witty-agents
```

使用联调 fork 时，将地址替换为 fork 地址并 checkout 对应分支。

### 3.2 生成运行配置

第一次执行：

```bash
bash ci/jenkins/bootstrap.sh
```

脚本会生成：

```text
ci/jenkins/.runtime.env
```

然后停止，提醒确认仓库和分支。打开该文件，至少确认：

```text
WITTY_AGENTS_REPO_URL=https://gitcode.com/openeuler/witty-agents.git
WITTY_AGENTS_BRANCH=*/master
WITTY_AGENTS_SCRIPT_PATH=Jenkinsfile
WITTY_AGENTS_JOB_NAME=witty-agent-package-ci
```

联调分支示例：

```text
WITTY_AGENTS_REPO_URL=https://gitcode.com/Kimsohee/witty-agents.git
WITTY_AGENTS_BRANCH=*/ci/shennong-npm-pipeline-v2
```

公开仓库不需要 Git 凭据。私有仓库需要先在 Jenkins 中添加 Git 凭据，再将其 ID 写入：

```text
WITTY_AGENTS_GIT_CREDENTIAL_ID=<Jenkins凭据ID>
```

### 3.3 启动服务

确认 `.runtime.env` 后再次执行：

```bash
bash ci/jenkins/bootstrap.sh
```

脚本会依次完成：

1. 创建 `/home/witty-agents-jenkins/` 持久化目录；
2. 生成只保存在服务器上的 Jenkins 初始密码；
3. 构建带 Pipeline、Git 和 Docker 插件的 Jenkins Controller；
4. 启动 `witty-agents-jenkins` 容器；
5. 创建管理员账号；
6. 自动创建 `witty-agent-package-ci` Pipeline Job；
7. 把 Job 关联到 `.runtime.env` 中配置的仓库、分支和 `Jenkinsfile`。

查看服务状态：

```bash
docker compose \
  --env-file ci/jenkins/.runtime.env \
  -f ci/jenkins/docker-compose.yml \
  ps
```

查看启动日志：

```bash
docker compose \
  --env-file ci/jenkins/.runtime.env \
  -f ci/jenkins/docker-compose.yml \
  logs --tail=200 jenkins
```

## 4. 从个人电脑访问 Jenkins

Jenkins 默认只监听服务器本机的 `127.0.0.1:18081`，需要使用 SSH 隧道访问：

```bash
ssh -i <SSH私钥路径> \
  -N -L 18081:127.0.0.1:18081 \
  <服务器用户>@<服务器IP>
```

例如：

```bash
ssh -i ~/.ssh/witty_agents_jenkins_ed25519 \
  -N -L 18081:127.0.0.1:18081 \
  root@60.204.250.91
```

`-i` 后面是个人电脑上用于登录服务器的 SSH 私钥路径。它不是 Jenkins 密码，也不是
npm Token。私钥不能发给他人，也不能提交到 Git 仓库。

隧道建立后浏览器打开：

```text
http://127.0.0.1:18081/
```

初始管理员用户名来自 `.runtime.env`，密码文件默认为：

```text
ci/jenkins/secrets/admin-password
```

该文件已被 `.gitignore` 排除。不要把内容发到群聊或提交到仓库。

## 5. 第一次构建

进入 `witty-agent-package-ci`。Job 已经由初始化脚本配置为：

```text
Definition：Pipeline script from SCM
SCM：Git
Repository URL：WITTY_AGENTS_REPO_URL
Branch Specifier：WITTY_AGENTS_BRANCH
Script Path：WITTY_AGENTS_SCRIPT_PATH
```

第一次点击 **Build Now**，Jenkins 会从 Git 拉取代码并读取根 `Jenkinsfile`。这次运行
同时登记 `AGENT`、`VARIANT`、`PACKAGE_STYLE` 等参数。完成后页面会出现
**Build with Parameters**。

根 `Jenkinsfile` 设置了 `pollSCM('H/5 * * * *')`。第一次成功加载后，Jenkins 每五分钟
检查配置分支是否出现新提交；检测到变化后自动构建。自动构建默认不发布 npm。

## 6. 现有服务器改名

如果服务器已经存在 `shennong-npm-package-ci`，不必重新安装 Jenkins。可以在 Job 页面
选择 **Rename**，改为：

```text
witty-agent-package-ci
```

然后在 **Configure → Pipeline** 中确认 Script Path 是根目录 `Jenkinsfile`。改名不会
改变历史构建和 Artifacts。

运行镜像和缓存目录也应使用通用名称：

```text
witty-agents-ci-runtime:oe2403sp4-node20-py311
/home/witty-agents-jenkins/
```

如果需要临时回滚，保留 Script Path 为 `Jenkinsfile`，只把 Branch Specifier 切换到
最近一次验证通过的分支或提交，避免在 Jenkins 页面中维护另一份脚本。

## 7. x86 与 ARM 在线包发布验收

正式流水线仍要求从官方 `master` 同时发布 online 和 offline 两个包。若只需要验证某台
原生 x86 或 ARM Jenkins 节点能否完成“构建 online 包 → 发布 npm → 从 npm 下载并
核对”的链路，可另建一个手工 Pipeline Job，并将 **Script Path** 设置为：

```text
ci/jenkins/Jenkinsfile.online-publish-smoke
```

这个 Job 不配置定时触发，只在人工确认后发布，而且有三层限制：

- 只接受 Shennong 的 unscoped online 包；
- 版本必须是 prerelease，例如 `0.10.5-ci.aarch64.0`；
- dist-tag 不能是 `latest`，例如 ARM 使用 `arm-test`。

发布 Job 必须指向已经复核、只有受信任维护者能写入的分支或提交，并限制 Job 的构建
权限。`npm-token` 建议使用只允许发布该测试包的 granular token；不要让发布 Job 直接
运行来自外部 PR 的未复核 Jenkinsfile 或脚本。

两台 Jenkins 使用同一份脚本，选择对应的节点架构并填写匹配的预发布版本。dist-tag 由
流水线按架构自动设置，不能在构建页面中改成其他地址或标签：

| 构建节点 | `EXPECTED_ARCH` | 版本示例 | dist-tag 示例 |
|---|---|---|---|
| x86_64 | `x86_64` | `0.10.5-ci.x86-64.0` | `x86-test` |
| ARM64 | `aarch64` | `0.10.5-ci.aarch64.0` | `arm-test` |

npm 地址固定为官方 registry，凭据固定读取 Jenkins Secret Text `npm-token`。每次发布
必须使用尚未占用的新版本号，并勾选 `CONFIRM_PUBLIC_PUBLISH`。Job 会依次执行
代码检查、online 打包、包门禁、安装流程、npm 发布、注册表可见性等待和真实回下载。
最后比较构建包与下载包的 SHA-256；两者一致才算通过。结果保存在：

```text
ci-artifacts/npm-publish-smoke-summary.json
ci-artifacts/npm-download/
shennong-crash-agent/artifacts/online-package-report.json
```

这里分别在两种架构运行，是为了验证两台原生 Jenkins 节点和各自的构建发布链路。
online 包不携带 Python wheels，不应解释为存在两种正式的架构专用 online 包。

## 8. 停止、重启和迁移

停止服务：

```bash
docker compose \
  --env-file ci/jenkins/.runtime.env \
  -f ci/jenkins/docker-compose.yml \
  down
```

重新启动：

```bash
bash ci/jenkins/bootstrap.sh
```

`down` 不会删除 `/home/witty-agents-jenkins/home`，因此 Job、用户、凭据和构建记录仍然
保留。迁移服务器时，在 Jenkins 停止状态下备份整个
`/home/witty-agents-jenkins/`，在新服务器恢复到相同路径后再启动。

npm Token、Git 私钥和其他凭据保存在 Jenkins Home 中。迁移备份必须按敏感数据管理，
不能放进 Git 仓库。
