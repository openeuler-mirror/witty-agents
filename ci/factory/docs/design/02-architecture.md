# 02 · 总体架构与技术选型

## 1. 架构总览

```
┌──────────────────────────── 使用者 ────────────────────────────┐
│  浏览器（Vue 3 SPA）                                            │
└───────────────┬────────────────────────────────────────────────┘
                │ HTTPS / JSON / SSE
┌───────────────▼────────────────────────────────────────────────┐
│                    witty-agent-factory                          │
│                                                                 │
│  ┌──────────────────────┐      ┌────────────────────────────┐  │
│  │  API 服务 (Fastify)   │      │  采集器 Worker (同进程/独立) │  │
│  │  ├ auth / rbac        │      │  ├ BuildPoller  30s        │  │
│  │  ├ agents             │      │  ├ LogStreamer   按需      │  │
│  │  ├ builds             │◄────►│  ├ ReportDigester 构建后   │  │
│  │  ├ releases           │      │  ├ RegistryWatcher 5min    │  │
│  │  ├ audit              │      │  └ RepoSync  10min         │  │
│  │  ├ settings           │      └────────────────────────────┘  │
│  │  └ ai (COP-01..08)    │                                      │
│  └──────────┬───────────┘                                      │
│             │                                                    │
│  ┌──────────▼───────────┐   ┌────────────────────────────────┐  │
│  │ 平台库 (SQLite/PG)    │   │ 集成层 integrations/            │  │
│  │ users/builds/releases │   │ ├ JenkinsClient  (REST + wfapi) │  │
│  │ audit/ai/settings     │   │ ├ GitClient      (GitCode API)  │  │
│  └───────────────────────┘   │ ├ RegistryClient (npm registry) │  │
│                               │ └ LlmClient      (Provider 抽象)│  │
│                               └────────────────────────────────┘  │
└───────────┬─────────────────────┬──────────────────┬─────────────┘
            │                     │                  │
    ┌───────▼────────┐   ┌────────▼───────┐  ┌───────▼─────────┐
    │ Jenkins        │   │ Git 仓库        │  │ npm registry    │
    │ witty-agents-  │   │ gitcode/atomgit │  │ registry.npmjs  │
    │ builder        │   │ openeuler/      │  │ .org            │
    │ + smoke Job    │   │ witty-agents    │  │                 │
    └────────────────┘   └────────────────┘  └─────────────────┘
      唯一执行引擎           唯一事实源           发布结果校验
```

要点：**三个上游都是"事实"，平台是"投影 + 控制面"**。平台可以触发 Jenkins、可以创建 MR，但不会绕开它们直接改状态。

## 2. 分层与模块职责

| 层 | 模块 | 职责 | 不做什么 |
|---|---|---|---|
| 表现层 | `packages/web` | 页面、组件、路由、状态、SSE 订阅 | 不直连 Jenkins / npm |
| 应用层 | `modules/*/routes.ts` + `service.ts` | 参数校验（zod）、权限判定、事务、审计埋点 | 不写 HTTP 细节 |
| 领域层 | `modules/*/domain.ts` | 状态机、门禁规则、派生指标（成功率、健康度） | 不依赖具体上游 SDK |
| 集成层 | `integrations/*` | Jenkins / Git / npm / LLM 的协议适配、重试、错误映射 | 不含业务规则 |
| 采集层 | `jobs/*` | 定时与事件驱动的上游事实同步 | 不直接改用户可见数据以外的状态 |
| 存储层 | `core/db` + `migrations` | Prisma schema、查询封装、事务 | — |

## 3. 上游系统交互矩阵

| 上游 | 读取 | 写入 | 认证方式 | 频率 |
|---|---|---|---|---|
| Jenkins | Job 配置（`/job/<j>/api/json`）、构建列表、构建详情、阶段（`wfapi/describe`）、日志（`consoleText` / `progressiveText`）、归档产物清单 | 触发（`buildWithParameters`）、取消（`stop`） | 服务账号 + API Token（HTTP Basic） | 列表 30s；运行中构建 3s |
| Git 仓库 | `ci/agents.json`、`<agent>/ci/agent.json`、`<agent>/package.json`、分支与 commit 信息 | 创建分支 / 提交 / 创建 MR（仅 Agent 启停与配置建议） | 仓库 Token（PAT，最小 scope） | 10min 或手动触发 |
| npm registry | 版本列表、dist-tags、发布时间、integrity | **不写** | 只读，无需认证（公开包） | 5min；发布期间 10s |
| LLM | 诊断 / 汇总 / 推荐 / 解释 | — | Provider API Key（可选，未配置则降级规则引擎） | 按需 |

## 4. 技术选型

| 维度 | 选择 | 理由 | 备选与放弃原因 |
|---|---|---|---|
| 后端语言 | Node.js 20 + TypeScript | 仓库现有 CI 脚本即 Node 20 ESM（`ci/scripts/*.mjs`），可直接复用其 JSON 结构与校验语义；Node 20 已是所有构建节点的硬性要求 | Python：与现有脚本生态割裂；Go：团队无积累 |
| Web 框架 | Fastify | 轻量、内置 schema 校验与序列化、SSE 支持好 | NestJS：对单体运维平台过重；Express：生态老化、校验需自己拼 |
| 校验 / 契约 | zod → `zod-to-openapi` → OpenAPI 3.1 → `openapi-typescript` 生成前端类型 | 单一 schema 来源，前后端不会漂移 | 手写类型：必然漂移 |
| ORM / 迁移 | Prisma | 迁移工具成熟，SQLite→PostgreSQL 切换代价低 | TypeORM：迁移体验差；写裸 SQL：迭代慢 |
| 数据库 | 默认 SQLite（WAL）+ 可切 PostgreSQL | 单机 compose 部署零运维；构建/审计数据量不构成瓶颈；Postgres 作为多实例或更高并发时的选项 | 直接上 PG：增加一个必须运维的组件 |
| 任务调度 | 进程内调度（`node-cron` + 内存队列）+ 单实例锁 | 单实例部署场景足够；避免引入 Redis/BullMQ | 外部队列：单体规模不需要 |
| 前端框架 | Vue 3 + TypeScript + Vite | 原型是原生 HTML/CSS，设计令牌可直接迁到 CSS 变量；Vue 模板贴近原型结构，迁移成本最低 | React：团队无强诉求，且原型迁移无优势 |
| 状态管理 | Pinia | Vue 3 官方推荐 | Vuex：已过时 |
| 路由 | Vue Router 4，路由级权限元信息 | 权限与路由天然结合 | — |
| UI 组件 | 自研轻量组件层（沿用原型 CSS 变量）+ 按需引入 ECharts | 原型已有完整视觉规范，引重型组件库会二次改造 | Element Plus：样式与原型冲突，改造成本高于自研 |
| 实时通道 | SSE（`text/event-stream`） | 单向推送即可；比 WebSocket 简单，Nginx 原生支持 | WebSocket：双向能力用不上，运维更复杂 |
| 日志查看 | 自研虚拟滚动 | 需要行号、分级着色、关键字高亮、错误导航等定制能力 | xterm.js：面向终端，不适合结构化日志 |
| 部署 | Docker Compose（沿用 `ci/jenkins` 风格） | 与现有部署方式一致，交接成本低 | K8s：当前只有一两台机器 |
| 反向代理 | Nginx（web 容器内置） | 静态资源 + API 反代 + SSE 缓冲关闭 | — |

## 5. 四条关键数据流

### 5.1 构建状态采集（常态）

```
BuildPoller(30s)
  → JenkinsClient.listBuilds(job, since=lastKnown)
  → 与库中 builds 比对（新增 / 状态变化 / 结束）
  → 新增：INSERT builds(status=running)
  → 结束：拉 wfapi/describe 写 build_stages
         拉归档清单写 artifacts
         拉关键报告 JSON 写 build_reports（结构化）
  → 触发通知（失败、状态翻转）
```

### 5.2 触发构建

```
POST /builds {agent, variant, ...14 params}
  → 权限判定 build:trigger（PUBLISH 相关参数额外判定 release:publish）
  → 参数与 Jenkinsfile 定义比对（类型 / 取值域）
  → 写审计（含参数快照）
  → JenkinsClient.triggerWithParameters(job, params)
  → 立即返回 202 + 占位 build（状态 queued）
  → BuildPoller 在下个周期补全真实构建号
```

### 5.3 日志实时流

```
浏览器 GET /builds/:no/log/stream (SSE)
  → 服务端为该构建建立 LogStreamer
  → 循环 GET progressiveText?start=<offset>（构建中 3s / 结束后停止）
  → 增量写入 build_logs 分片 + push SSE event:log
  → 结束事件 event:end，前端断流
```

### 5.4 发布

```
POST /releases/preflight {buildNo, package, version, distTag}
  → REL-01 五项检查（见 07）
  → 返回逐项结论
POST /releases {..., confirm:true}
  → 权限判定 release:publish
  → 写审计（含门禁快照 + 操作人）
  → 触发主 Job（PUBLISH=true）或 smoke Job
  → ReleaseWatcher 跟踪：构建完成 → 读 npm-publish-smoke-summary.json
  → 校验 latest 前后快照一致；不一致 → 告警 + 置为待人工核查
  → 更新 dist_tags 与 dist_tag_events
```

## 6. 部署拓扑

与 Jenkins 同机部署（推荐），或部署在同网段可达 Jenkins 内网地址的机器上。

```
ARM64 节点 123.60.114.33
├── Jenkins 容器 (jenkins, 127.0.0.1:8080)      ← 已有
│    └── Job: witty-agents-builder / ...-smoke-arm
└── factory compose (新增)
     ├── factory-web   (nginx :18080 静态 + /api 反代)
     ├── factory-api   (:3001, 仅容器网络暴露)
     └── factory-data  (volume: sqlite + 日志分片)
```

端口规划（避开现有占用：Jenkins 8080 / 18081、postgres 5432、milvus 等）：

| 服务 | 宿主机端口 | 说明 |
|---|---|---|
| factory-web | `127.0.0.1:18080` | 仅本机监听，经 SSH 隧道访问，与 Jenkins 的 `127.0.0.1:18081` 风格一致 |
| factory-api | 不映射 | 只经 web 容器反代 |

## 7. 安全边界与信任模型

| 边界 | 规则 |
|---|---|
| 用户 → 平台 | 必须登录；所有接口按权限点鉴权；写操作二次确认 + 审计 |
| 平台 → Jenkins | 使用最小权限服务账号（`authenticated` 即可：可读、可触发，不能改配置）；Token 加密存储；Jenkins 地址仅内网可达 |
| 平台 → Git | 使用单独 PAT，只授予目标仓库的 `write:repository`；**禁止直接推 master**，只允许推平台专用分支并创建 MR |
| 平台 → npm | 只读公开 registry，无需凭据 |
| 平台 → LLM | 只发送脱敏后的构建日志片段与统计特征，不发送源代码全文与凭据 |
| 平台自身 | 会话 Cookie `httpOnly + SameSite=Lax`；CSRF Token 保护写接口；登录与写操作限流 |

**密钥清单**（全部来自环境变量或 Docker Secret，不入库明文）：

```
FACTORY_JENKINS_TOKEN       Jenkins 服务账号 API Token（加密后入库，或直接读环境变量）
FACTORY_GIT_TOKEN           GitCode/AtomGit PAT（写回 MR 用）
FACTORY_LLM_API_KEY         LLM Provider Key（可选）
FACTORY_SECRET_KEY          平台自用密钥（加密上述凭据 + 签名会话）
FACTORY_ADMIN_PASSWORD      首次启动创建管理员用（仅初始化使用）
```

## 8. 与 `ci/jenkins` 的关系

| 维度 | `ci/jenkins/` | `ci/factory/` |
|---|---|---|
| 目标 | 把 Jenkins 跑起来（Controller、运行镜像、Job 自动创建） | 在 Jenkins 之上做运维、可视化与审计 |
| 产物 | `bootstrap.sh`、`docker-compose.yml`、`init.groovy.d/` | 本平台前后端 + 本套文档 |
| 依赖关系 | 独立 | 依赖一个可用的 Jenkins 与已配置的 Job |
| 冲突 | 无。factory 不修改 Jenkins 配置，只通过 API 访问 | — |

部署顺序：先有 Jenkins（`ci/jenkins/bootstrap.sh`）→ 再建 Job 并跑通一次构建 → 最后部署 factory 并绑定 Job。

## 9. 关键设计决策（ADR 摘要）

| # | 决策 | 结论 | 代价 |
|---|---|---|---|
| ADR-01 | 阶段与日志来源 | 主用 Jenkins `wfapi`（`/job/<j>/<n>/wfapi/describe`）；不可用时降级解析 `consoleText` 的 `[Pipeline]` 上下文 | 需要 Workflow API 插件；降级路径实现成本高 |
| ADR-02 | 阶段列表模板 | 平台内置 11 个阶段的名称与顺序模板，Jenkins 返回缺失的阶段显示为"未执行（条件阶段）" | 流水线新增阶段需同步模板（用版本号 + 校验兜底） |
| ADR-03 | Agent 启停写回 | 通过创建分支 + 提交 `ci/agents.json` + 创建 MR；平台只跟踪 MR 状态 | 依赖仓库 Token 与 MR API；无法"立即生效" |
| ADR-04 | 发布执行者 | 平台只触发 Jenkins，不直接 `npm publish` | 发布参数必须与 Jenkinsfile 保持一致 |
| ADR-05 | dist-tag 回滚 | 默认生成命令交人工执行（复制命令按钮）；可选启用"受控 Job 执行"模式 | 回滚是低频高危操作，人审成本可接受 |
| ADR-06 | 数据存储 | 平台库与 Jenkins 记录分离；平台自留 200 次构建与 90 天日志 | 需要清理任务；与 Jenkins 保留策略（20/10）不一致是有意的 |
| ADR-07 | 多项目模型 | 数据模型从第一天就支持多项目（`projects` + `project_members`），UI 可先只展示一个 | 少量额外复杂度 |
| ADR-08 | 前端组件库 | 自研组件层，不引 Element Plus | 需要自己实现表格分页、抽屉、对话框、Toast |
| ADR-09 | AI Provider | 抽象 Provider，默认关闭；未配置 Key 时所有 AI 面板显示"未配置"而非假装可用 | 需要额外的降级 UI 状态 |
| ADR-10 | 服务账号权限 | 平台不给 Jenkins 服务账号任何管理权限 | 无法通过平台修改 Jenkins 自身配置（这是期望行为） |
