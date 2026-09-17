# 08 · 部署运维与工程结构

## 1. `ci/factory` 目录树

```
ci/factory/
├── README.md                       # 项目说明、快速开始
├── docs/                           # 本套设计文档（随代码演进，保持同步）
├── package.json                    # pnpm workspace 根
├── pnpm-workspace.yaml
├── docker-compose.yml              # 生产部署（web + api + data）
├── docker-compose.dev.yml          # 本地开发（热更新 + 可选 mock Jenkins）
├── .env.example                    # 全部环境变量样例（不含真实密钥）
├── Makefile                        # 常用命令：dev / build / test / e2e / gen:api
├── packages/
│   ├── shared/                     # 前后端共享：zod schema、常量（14 参数、11 阶段）、类型
│   │   ├── src/params.ts           # 参数定义（类型/取值域/分组/默认值）
│   │   ├── src/stages.ts           # 11 阶段模板
│   │   ├── src/permissions.ts      # 权限点枚举
│   │   └── src/reports.ts          # 报告 JSON 的 zod schema
│   ├── api/                        # 后端（结构见 03 §1）
│   │   └── Dockerfile
│   └── web/                        # 前端（结构见 06 §1）
│       ├── nginx.conf              # 静态托管 + /api 反代 + SSE 关闭缓冲
│       └── Dockerfile
├── scripts/
│   ├── dev.sh                      # 一键起本地环境
│   ├── seed-admin.ts               # 创建初始管理员
│   ├── gen-openapi.ts              # zod → OpenAPI
│   └── smoke-jenkins.ts            # 校验 Jenkins 连通与权限
└── test/
    ├── fixtures/                   # 从真实环境采集的样例（见 07 §10）
    │   ├── jenkins-build-21.json
    │   ├── wfapi-describe.json
    │   ├── build-plan.json
    │   ├── ci-summary-online.json
    │   ├── install-flow-online.json
    │   └── npm-publish-smoke-summary.json
    └── e2e/                        # Playwright
```

## 2. 组件与镜像

| 组件 | 镜像 | 说明 |
|---|---|---|
| `factory-api` | 基于 `node:20-alpine` 构建（多阶段：builder + runner） | 非 root 运行（uid 1000），只读根文件系统 + 可写 `/app/data` |
| `factory-web` | 基于 `nginx:1.27-alpine` | 静态资源 + `/api` 反代；SSE 路径关闭 `proxy_buffering` |
| 数据卷 | `factory-data` | SQLite 文件 + 日志分片目录（若用 PostgreSQL 则另有 `factory-pg-data`） |

## 3. docker-compose 设计

```yaml
services:
  api:
    build: { context: ., dockerfile: packages/api/Dockerfile }
    env_file: [.env]
    volumes: [ "factory-data:/app/data" ]
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3001/api/v1/system/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped
    networks: [ factory ]

  web:
    build: { context: ., dockerfile: packages/web/Dockerfile }
    ports: [ "127.0.0.1:18080:80" ]        # 仅本机监听，经 SSH 隧道访问（与 Jenkins 18081 风格一致）
    depends_on: [ api ]
    restart: unless-stopped
    networks: [ factory ]

networks: { factory: {} }
volumes: { factory-data: {} }
```

关于为什么只监听 `127.0.0.1`：与现有 Jenkins（`127.0.0.1:18081`）一致，避免把运维入口直接暴露到公网；需要外部访问时通过 SSH 隧道或前置反向代理 + 认证。

## 4. 环境变量

`.env.example`（提交仓库，不含密钥）：

```dotenv
# 基础
FACTORY_BASE_URL=http://127.0.0.1:18080
FACTORY_PORT=3001
FACTORY_LOG_LEVEL=info

# 数据
FACTORY_DATABASE_URL=file:/app/data/factory.db

# 密钥（32 字节随机，生产必须替换）
FACTORY_SECRET_KEY=replace-with-32-byte-random

# Jenkins
FACTORY_JENKINS_URL=http://host.docker.internal:8080
FACTORY_JENKINS_USER=witty-agent
FACTORY_JENKINS_TOKEN=replace-with-api-token
FACTORY_JENKINS_JOBS=witty-agents-builder,witty-agents-online-publish-smoke-arm

# Git
FACTORY_GIT_PROVIDER=atomgit
FACTORY_GIT_REPO=openeuler/witty-agents
FACTORY_GIT_TOKEN=

# AI（可留空 → 规则引擎）
FACTORY_LLM_PROVIDER=
FACTORY_LLM_BASE_URL=
FACTORY_LLM_MODEL=
FACTORY_LLM_API_KEY=
```

注意：容器内访问宿主机 Jenkins 需用 `host.docker.internal`（Linux 下 compose 需加 `extra_hosts: ["host.docker.internal:host-gateway"]`）或直接使用宿主机内网 IP。

## 5. 初始化与首次运行

```bash
# 1. 准备配置
cp ci/factory/.env.example ci/factory/.env
#    填入 Jenkins Token / Git Token / Secret Key

# 2. 生成自用密钥
openssl rand -base64 32

# 3. 启动
docker compose -f ci/factory/docker-compose.yml up -d --build

# 4. 创建初始管理员（一次性）
docker compose exec api node scripts/seed-admin.js --user admin --password '<强密码>'

# 5. 校验上游连通性
docker compose exec api node scripts/smoke-jenkins.js
#    输出：Job 可达 / 参数定义一致 / 最近构建可读 / 归档可列

# 6. 建立 SSH 隧道后访问
ssh -N -L 18080:127.0.0.1:18080 -p 33410 root@123.60.114.33
#    浏览器打开 http://127.0.0.1:18080/
```

首次启动后应完成的配置：

1. 创建项目 `witty-agents`，绑定仓库与 2 个 Jenkins Job；
2. 点击"测试连通"，确认 Git 与 Jenkins 均通过；
3. 点击"同步 agents.json"，确认 4 个 Agent 全部同步（与 `ci/agents.json` 一致）；
4. 触发一次 `AGENT=auto / VARIANT=default / PUBLISH=false` 的构建，验证采集链路；
5. 检查构建详情的阶段、日志、报告是否完整。

## 6. 与 `ci/jenkins` 共存

| 资源 | `ci/jenkins` | `ci/factory` | 冲突风险 |
|---|---|---|---|
| 端口 | Jenkins `127.0.0.1:18081`（容器映射） | factory-web `127.0.0.1:18080` | 无 |
| 数据目录 | `/home/witty-agents-jenkins/` | Docker volume `factory-data` | 无 |
| Docker 网络 | `shennong-jenkins-deploy`（默认） | `factory` | 无 |
| Jenkins API | — | 只读 + 触发/取消 | 需要服务账号，不影响 Jenkins 配置 |

部署顺序：Jenkins 就绪 → Job 至少成功构建一次 → 部署 factory → 绑定 → 首次同步。

## 7. 备份与恢复

| 数据 | 备份方式 | 频率 | 恢复 |
|---|---|---|---|
| `factory-data` 卷（SQLite + 日志分片） | `docker run --rm -v factory-data:/data -v $PWD:/backup alpine tar czf /backup/factory-$(date +%F).tgz -C /data .` | 每日（脚本 + cron） | 停服 → 还原卷 → 起服 |
| `.env`（含密钥） | 密码管理器 / 受控目录，**不入 Git** | 变更时 | 手动恢复 |
| 审计日志 | 随卷备份 + 可选导出 CSV 到受控存储 | 每日 | 从备份恢复 |
| Jenkins Home | 由 `ci/jenkins` 负责（不属本平台） | — | — |

恢复演练要求：至少每季度一次，在测试环境验证"备份 → 恢复 → 数据一致"。

## 8. 升级与回滚

```bash
# 升级（拉取新代码后）
git pull
docker compose -f ci/factory/docker-compose.yml up -d --build
# 启动时自动执行 prisma migrate deploy（只前滚）

# 回滚
git checkout <上一个可用 tag 或 commit>
docker compose -f ci/factory/docker-compose.yml up -d --build
```

约定：
- 破坏性迁移必须拆成两步（见 04 §6），保证旧版本代码能在新库结构上运行一个版本；
- 每次升级前先备份 `factory-data`；
- 镜像打 tag（`factory-api:$(git rev-parse --short HEAD)`）便于回滚到具体构建。

## 9. 可观测性

### 9.1 健康检查

`GET /api/v1/system/health` 返回：

```json
{
  "data": {
    "status": "ok",
    "db": { "status": "ok", "latencyMs": 2 },
    "jenkins": { "status": "ok", "url": "http://127.0.0.1:8080", "latencyMs": 41, "degraded": false },
    "registry": { "status": "ok", "latencyMs": 120 },
    "sync": { "buildPoller": "12s ago", "repoSync": "3m ago", "registryWatcher": "1m ago" }
  }
}
```

### 9.2 关键指标（Prometheus 文本格式 `/metrics`，可选）

| 指标 | 类型 | 用途 |
|---|---|---|
| `factory_builds_total{agent,status}` | counter | 构建规模与成功率 |
| `factory_build_duration_seconds` | histogram | 构建耗时分布 |
| `factory_jenkins_request_duration_seconds` | histogram | 上游延迟 |
| `factory_jenkins_errors_total{endpoint}` | counter | 上游错误率 |
| `factory_sync_lag_seconds{collector}` | gauge | 数据新鲜度（核心告警项） |
| `factory_ai_requests_total{kind,provider,result}` | counter | AI 调用量与失败率 |

### 9.3 日志

- 结构化 JSON（Pino），字段：`ts/level/requestId/userId/route/status/durationMs/msg`；
- 不记录请求体全文（可能含参数与凭据），只记录关键字段；
- 容器日志由 Docker 轮转（`max-size=10m, max-file=5`）。

### 9.4 告警建议（可由外部监控拉取）

| 条件 | 级别 |
|---|---|
| `factory_sync_lag_seconds{buildPoller} > 300` | warning（采集停了） |
| `jenkins.degraded = true` 持续 5 分钟 | warning |
| 构建失败（`builds.status=failure` 新增） | warning |
| 发布 `latest` 漂移 | critical |
| 发布 `manual_review` | critical |
| 磁盘使用率 > 85%（服务器层） | warning |

## 10. 安全加固清单（上线前逐项确认）

- [ ] `.env` 不入 Git；`FACTORY_SECRET_KEY` 为随机生成且长度合规；
- [ ] Jenkins 使用独立服务账号 + API Token（不复用个人账号），权限最小化；
- [ ] Git Token 仅授予目标仓库写权限，且只用于创建 MR 分支；
- [ ] factory-web 仅监听 `127.0.0.1`；如需外部访问必须前置 TLS 与认证；
- [ ] 首次登录强制修改初始管理员密码；
- [ ] 审计哈希链校验接口可用且返回一致；
- [ ] 日志脱敏规则覆盖 token / 密码 / 私钥 / 带凭据 URL；
- [ ] 数据备份脚本已配置并完成一次恢复演练；
- [ ] 容器以非 root 运行，根文件系统只读；
- [ ] 依赖定期升级（`pnpm audit` + 镜像基础层更新）。
