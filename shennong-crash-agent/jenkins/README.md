# Shennong npm Jenkins Pipeline

Jenkins 使用仓库根目录的 `Jenkinsfile.shennong`。任务应配置为 **Pipeline script
from SCM**，Script Path 填写：

```text
Jenkinsfile.shennong
```

这样 `pollSCM('H/5 * * * *')` 才能每五分钟检查一次代码变化；Jenkins 页面仍可
随时通过 **Build with Parameters** 手动触发。

当前 x86 Job 在 Jenkins `built-in` 节点上启动
`shennong-oe2403sp4-acceptance:runtime-v2` 构建容器。该容器不挂载 Docker
socket，仅获得断网验收所需的 `SYS_ADMIN`、`NET_ADMIN` 能力。ARM 正式离线包应在
独立 aarch64 openEuler 节点使用对应原生镜像构建，不能用 x86 模拟产物替代。

## Agent 前置条件

- openEuler 构建机；
- Node.js 20+；
- npm 10+；
- Python 3.11 或 3.12；
- `python -m pip` 和 `git-lfs`；
- 构建离线包时允许联网下载 wheels；
- 验证离线包时安装 `util-linux`、`iproute`，并支持 `unshare --net` 或 user network namespace；
- 真实安装验收需要 `libglvnd-glx`、`glib2`、`libXext`、`libXrender`、`libSM`；
- Jenkins Secret Text 凭据 `npm-token`（只在发布阶段读取）。

## 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `VARIANT` | `all` | `online`、`offline` 或两种都构建 |
| `PYTHON_BIN` | `python3.11` | 构建 wheels 和创建三套 venv 的 Python |
| `PYPI_INDEX_URL` | PyPI 官方源 | online setup 和 offline wheel 构建使用的 Python 包索引 |
| `OCR_MODEL_CACHE_DIR` | `/home/shennong-jenkins/ocr-model-cache` | Git LFS 不可用时使用的可信 OCR 模型缓存 |
| `RUN_REAL_INSTALL_VALIDATION` | `true` | 执行真实 install/setup/configure 流程 |
| `STRICT_OFFLINE_NETWORK_CHECK` | `true` | 无法建立断网命名空间时让离线验证失败 |
| `PUBLISH` | `false` | 是否发布；只有 `VARIANT=all` 且提交位于 `origin/master` 才允许 |
| `NPM_CREDENTIAL_ID` | `npm-token` | npm Token 的 Jenkins 凭据 ID |
| `NPM_REGISTRY` | npm 官方仓库 | 发布目标 |
| `NPM_DIST_TAG` | `latest` | npm 发布标签 |

## 验证和产物

流水线会验证插件入口、包名、在线包 10 MiB 限制、知识文件完整性、离线 wheel
闭包，以及以下真实流程：

```text
npm install
→ shennong-setup
→ 重复 shennong-setup
→ shennong-configure
→ 重复 shennong-configure
→ shennong-configure remove
→ 重复 remove
→ shennong-setup stop
→ npm uninstall
```

离线真实流程在网络命名空间中执行。最终归档：

- `artifacts/*.tgz`；
- `artifacts/*-package-report.json`；
- `artifacts/*-npm-pack.json`；
- `artifacts/ci-summary.json`；
- `artifacts/publish-summary.json`（仅发布构建）；
- `ci-reports/install-flow-*.json`。

OCR 模型始终在打包前校验固定 SHA-256。流水线优先执行 `git lfs pull`；仓库 LFS
服务不可用时，必须通过 `OCR_MODEL_CACHE_DIR` 提供三个已物化模型。缓存内容不进入 Git。

发布前会同时检查远端仓库必须是官方 `openeuler/witty-agents`，并确认当前提交位于
`origin/master`。已发布的同版本仅在 SHA-512 integrity 与当前构建完全一致时允许跳过，
内容不一致会直接失败，防止两个包只发布一半后被错误覆盖。

首次联调保持 `PUBLISH=false`，依次运行 `online`、`offline`、`all`；前三次全部通过
后再审核发布阶段。
