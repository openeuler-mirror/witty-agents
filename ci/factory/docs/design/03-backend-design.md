# 03 · 后端设计

## 1. 工程结构

```text
ci/factory/packages/api/
├── src/
│   ├── main.ts                      # 启动：加载配置 → 迁移 → 启动调度器 → 监听
│   ├── app.ts                       # Fastify 实例装配（插件、错误处理、路由注册）
│   ├── config.ts                    # 环境变量解析（zod 校验，缺失即启动失败）
│   ├── core/
│   │   ├── db.ts                    # Prisma client 单例
│   │   ├── errors.ts                # AppError 体系 + HTTP 映射
│   │   ├── logger.ts                # Pino（含 requestId 透传）
│   │   ├── audit.ts                 # audit(event) 统一埋点
│   │   ├── crypto.ts                # AES-256-GCM 加解密封装
│   │   ├── rbac.ts                  # 权限点定义 + 判定函数
│   │   └── scheduler.ts             # 定时任务注册与单实例锁
│   ├── integrations/
│   │   ├── jenkins/
│   │   │   ├── client.ts            # HTTP 封装：认证、重试、超时、限流
│   │   │   ├── endpoints.ts         # 端点常量（见 §3.2）
│   │   │   ├── types.ts             # Jenkins 响应类型（宽松），内部归一化
│   │   │   └── mapper.ts            # Jenkins 模型 → 平台模型
│   │   ├── git/
│   │   │   ├── client.ts            # Git 托管只读读取（raw / contents API）
│   │   │   └── registry-sync.ts     # agents.json / agent.json / package.json 抓取
│   │   ├── registry/
│   │   │   └── npm.ts               # 版本、dist-tags、发布时间、integrity（只读）
│   │   └── llm/
│   │       ├── provider.ts          # 接口定义
│   │       ├── openai-compatible.ts # OpenAI 兼容实现
│   │       └── rules.ts             # 无 LLM 时的规则降级实现
│   ├── modules/
│   │   ├── auth/                    # 登录、会话、CSRF、限流
│   │   ├── users/                   # 用户与系统角色
│   │   ├── projects/                # 项目、成员、设置
│   │   ├── agents/                  # Agent 投影（只读同步）
│   │   ├── builds/                  # 构建查询、触发、取消、重跑、日志、产物
│   │   ├── releases/                # 预检、发布、dist-tag、回滚
│   │   ├── audit/                   # 查询与导出
│   │   ├── notifications/           # 站内通知
│   │   └── ai/                      # COP-01..08
│   │       ├── context.ts           # 上下文构造（构建 + 报告 + 历史）
│   │       ├── prompts.ts           # 提示词模板
│   │       ├── guard.ts             # 护栏判定（只读 / 低危 / 高危）
│   │       └── redact.ts            # 脱敏
│   ├── jobs/
│   │   ├── build-poller.ts
│   │   ├── log-streamer.ts
│   │   ├── report-digester.ts
│   │   ├── registry-watcher.ts
│   │   ├── repo-sync.ts
│   │   └── retention.ts             # 数据保留清理
│   └── routes/                      # 路由聚合（按模块挂载 /api/v1）
├── prisma/
│   ├── schema.prisma
│   └── migrations/
└── test/
    ├── unit/
    ├── contract/                    # 对 Jenkins/Registry 的契约测试（录制回放）
    └── integration/                 # 真实 Jenkins（可选，CI 中默认跳过）
```

## 2. 模块清单

| 模块 | 关键职责 | 主要输出 |
| --- | --- | --- |
| auth | 密码校验（argon2id）、会话签发、CSRF、登录限流 | `session` Cookie、`/auth/me` |
| users | 用户 CRUD、系统角色、禁用即踢会话 | `users` 表 |
| projects | 项目、成员、设置、配置版本基线 | `projects`、`project_members`、`project_settings` |
| agents | 从仓库同步 Agent 投影（只读） | `agents` |
| builds | 查询、触发、取消、重跑、日志、产物、报告 | `builds`、`build_stages`、`build_reports`、`artifacts` |
| releases | 预检、发起、跟踪、dist-tag、回滚 | `releases`、`release_gates`、`dist_tags`、`dist_tag_events` |
| audit | 事件写入与查询导出 | `audit_logs` |
| notifications | 事件 → 通知 | `notifications` |
| ai | 5 个能力点 + 护栏 + 审计标记 | `ai_insights`、`ai_feedback` |

## 3. Jenkins 适配层

### 3.1 认证与连接

- 认证：HTTP Basic，`<服务账号>:<API Token>`；Token 通过 `FACTORY_JENKINS_TOKEN` 注入或加密入库。
- 地址：`FACTORY_JENKINS_URL`，例如 `http://127.0.0.1:8080`（同机）或内网地址。
- 超时：连接 3s、读 15s（拉日志/产物清单单独放宽到 60s）。
- 重试：GET 幂等请求指数退避重试 3 次（500/502/503/超时）；POST 触发类请求**不自动重试**（避免重复构建）。
- 限流：对 Jenkins 全局并发上限（默认 4），避免拖慢 Jenkins。
- 降级：连续 3 次失败 → 标记 `jenkins:degraded`，接口返回缓存数据并带 `stale: true`。

### 3.2 使用的 Jenkins 端点

| 用途 | 端点 | 备注 |
| --- | --- | --- |
| Job 基本信息 | `GET /job/<job>/api/json?tree=name,color,lastBuild[number],nextBuildNumber,inQueue` | 首页与健康度 |
| 参数定义 | `GET /job/<job>/api/json?tree=property[parameterDefinitions[...]]` | 用于校验平台表单与 Jenkinsfile 一致 |
| 构建列表 | `GET /job/<job>/api/json?tree=builds[number,result,timestamp,duration,building,actions[parameters[name,value]]]` | 分页用 `{0,100}` 范围语法 |
| 构建详情 | `GET /job/<job>/<n>/api/json?tree=result,timestamp,duration,building,actions[parameters[name,value],causes[shortDescription]],changeSet[items[commitId,msg,author[fullName]]]` | 触发人、commit |
| 阶段列表 | `GET /job/<job>/<n>/wfapi/describe` | 11 阶段的状态与耗时；**需 pipeline-stage-view 插件**（提供 wfapi 端点，见 [07](07-pipeline-integration.md) §12.1；未安装返回 404） |
| 阶段步骤 | `GET /job/<job>/<n>/execution/node/<nodeId>/wfapi/describe` | 按需展开；同上依赖 pipeline-stage-view |
| 全量日志 | `GET /job/<job>/<n>/consoleText` | 结束后一次性拉取 |
| 增量日志 | `GET /job/<job>/<n>/logText/progressiveText?start=<offset>` | 响应头 `X-Text-Size`、`X-More-Data` |
| 归档产物 | `GET /job/<job>/<n>/api/json?tree=artifacts[fileName,relativePath]` | 目录结构 |
| 产物内容 | `GET /job/<job>/<n>/artifact/<relativePath>` | 拉取报告 JSON / tgz |
| 触发构建 | `POST /job/<job>/buildWithParameters?<params>` + `Jenkins-Crumb` | 需 CSRF Crumb |
| 取消构建 | `POST /job/<job>/<n>/stop` | — |
| 阻塞队列 | `GET /queue/api/json?tree=items[id,task[name],why]` | 判断"排队中" |
| 执行器 | `GET /computer/api/json` | 系统状态卡 |

**注意事项（来自真实环境踩坑）**：

1. 调用含 `[ ]` 的 `tree` 参数时，若底层用 curl 必须加 `-g` 关闭 URL glob；Node 的 `fetch` 不受影响，但要把参数交给 `URLSearchParams` 正确编码。
2. 构建日志含大量 ANSI 转义（Jenkins 的 `timestamps()` + 高亮），**必须在服务端剥离 ANSI 与 OSC 序列后再入库**，否则前端无法做关键字高亮（这是原型与真实环境的差异点之一）。
3. `result` 在构建进行中为 `null`，平台状态需自算：`queued → running → success|failure|aborted`。
4. Jenkinsfile 里 `disableConcurrentBuilds()` 生效时，重复触发会进队列而非并行；平台需在触发响应中区分"已入队"和"已开始"。

### 3.3 阶段与日志归一化

```ts
// 内置阶段模板（与 Jenkinsfile 保持一致的顺序）
const STAGE_TEMPLATE = [
  'Initialize Parameters',
  'Resolve Build Plan',
  'Prepare Agents',
  'Prepare Assets',
  'Install Build Dependencies',
  'Validate Agents',
  'Build Packages',
  'Artifact Gates',
  'Install Contract Checks',
  'Real Install Flow',   // 条件：RUN_REAL_INSTALL_VALIDATION=true
  'Publish to npm',      // 条件：PUBLISH=true
] as const
```

归一化规则：

1. 以 `wfapi/describe` 返回的 stage 为准（`SUCCESS / FAILED / ABORTED / IN_PROGRESS / NOT_EXECUTED`）。
2. 模板中存在、结果中缺失的阶段 → 标为 `skipped`（条件阶段未执行）。
3. `wfapi` 不可用（插件缺失或权限不足）时 → 降级解析 `consoleText`：以 `[Pipeline] { (Stage Name)` 与 `[Pipeline] // stage` 配对识别；仍失败则整段展示为单阶段"未拆分"。降级状态需在 UI 明示。
4. 阶段耗时取 `durationMillis`；缺失时不展示而不是显示 `0s`。

部署基线要求安装 `pipeline-stage-view`（见 [07](07-pipeline-integration.md) §12.1）；`scripts/smoke-jenkins.ts` 启动时探测 wfapi 可用性，输出当前处于主路径还是降级路径。

## 4. 采集器 Worker

| 采集器 | 触发方式 | 周期 | 动作 |
| --- | --- | --- | --- |
| `BuildPoller` | 定时 | 30s（有运行中构建时 5s） | 同步构建列表与状态，结束时触发 `ReportDigester` |
| `LogStreamer` | 事件（SSE 订阅 / 运行中构建） | 3s | 拉 `progressiveText` 增量，写分片 + 推送 |
| `ReportDigester` | 事件（构建结束） | 一次性 | 下载并解析 `build-plan.json`、`ci-summary.json`、`*-package-report.json`、`install-flow-*.json`、`npm-publish-smoke-summary.json`，写 `build_reports` |
| `RegistryWatcher` | 定时 | 5min（发布期间 10s） | 同步版本与 dist-tags，检测 `latest` 漂移并告警 |
| `RepoSync` | 定时 / 手动 | 10min | 同步 `ci/agents.json` 与各 `agent.json`、`package.json`（版本、displayName） |
| `Retention` | 定时 | 每日 03:00 | 清理超期构建记录与日志分片（保留策略见 04 第 5 节） |

所有采集器共享约定：

- 单实例锁（`sync_states` 表 + 行级锁）防止重复执行；
- 每次执行写 `sync_states`（`lastRunAt`、`lastSuccessAt`、`lastError`），前端"同步于 X 分钟前"直接读这个表；
- 采集失败不影响 API 可用性，只影响数据新鲜度。

## 5. 构建服务

### 5.1 触发流程

```text
validateParams(body)                     // zod：类型 + 取值域 + 互斥规则
  ├─ PUBLISH=true 需要 release:publish 权限
  ├─ VARIANT=offline 时 TARGET_ARCH 必须与绑定节点架构一致（否则提示必然失败）
  └─ NPM_DIST_TAG 不允许为 latest（高风险默认值，见 07 §5.4）
preflight(body)                          // 可选：先只校验不触发
audit('build.trigger', {...params})
jenkins.triggerWithParameters(job, params)
return 202 { requestId, jenkinsQueueUrl }
```

参数校验必须以 **Jenkins 侧的 `parameterDefinitions`** 为准做二次比对：若 Jenkins 定义与平台内置定义不一致（例如流水线新增了参数），接口返回 `E_PARAM_DRIFT` 并提示同步，避免"平台能填但 Jenkins 不认识"。

### 5.2 构建状态机

```text
queued ──► running ──┬──► success
                     ├──► failure
                     ├──► aborted      （用户取消 / Jenkins 中止）
                     └──► unstable     （未使用，预留）
```

- `queued`：已接受触发请求，尚无构建号；
- 构建号补全后进入 `running`；
- `result` 非空即终态；
- 超时保护：若 `running` 超过 240 分钟（与 Jenkins `timeout` 一致）仍未结束，标记 `stale` 并告警（可能 Jenkins 重启丢了构建）。

### 5.3 取消与重跑

- 取消：仅对 `queued` / `running` 构建开放；写审计；调用 `/stop`。
- 重跑：以完全相同参数触发新构建，返回新构建引用；不修改原构建记录。
- Replay（P2）：仅对失败构建开放，需 `project:config` 之上权限，且在 UI 明示"复用原构建脚本"。

## 6. 发布服务

### 6.1 门禁预检实现（REL-01）

5 项检查全部可独立调用（`POST /releases/preflight`），返回逐项结论与证据字符串：

| # | 检查项 | 实现 | 证据示例 |
| --- | --- | --- | --- |
| 1 | 仓库是官方白名单 | 与 Jenkinsfile 相同的白名单比对（`gitcode.com/openeuler/witty-agents`、`atomgit.com/openeuler/witty-agents`，含 https/git@ 形式） | `origin=https://gitcode.com/openeuler/witty-agents.git ✓` |
| 2 | commit 是 `origin/master` 祖先 | 调用 Git 平台 API 比对 commit 是否在 master 历史中 | `a1b2c3d 是 origin/master 祖先提交 ✓` |
| 3 | 全部本地产物变体通过 | 读取该构建的 `build_reports`，校验 `ci-summary.json.status=passed`；`agent.publishRequiresAllVariants=true` 时要求变体全覆盖 | `online ✓ · offline ✓` |
| 4 | 版本未占用 | 查询 registry 是否存在同名版本 | `0.10.6-ci.aarch64.0 registry 无此版本 ✓` |
| 5 | dist-tag 与 `latest` 安全 | 目标 dist-tag 不得为 `latest`；记录 `latest` 发布前快照 | `arm-test ✓ · latest=0.10.5-ci.x86-64.0 已快照` |

任一项失败 → 拒绝发起发布，并在 UI 以失败项高亮 + AI 解释（COP-04）。

### 6.2 发布执行

两种执行通道（项目设置里选择）：

- **主 Job 通道**：触发 `witty-agents-builder`，`PUBLISH=true` + `VARIANT=all`。
- **Smoke Job 通道**：触发 `witty-agents-online-publish-smoke-arm`，适用于只验证发布链路本身。

两者都以发布记录（`releases`）为核心聚合对象，跟踪以下证据：

```text
releases.id
 ├─ release_gates        五项预检结果（含证据文本）
 ├─ 关联 build           触发产生的构建
 ├─ build_reports        构建结束后落库的 npm-publish-smoke-summary.json
 ├─ dist_tag_events      发布前后的 tag 指向变化
 └─ 复核动作             SHA-256 不一致时的人工/AI 重试记录
```

### 6.3 `latest` 保护

平台侧独立实现"快照—比对"：

```text
before = registry.distTags(pkg).latest      // 发布前
... 发布 ...
after  = registry.distTags(pkg).latest      // 发布后
if (before !== after) → 高危告警 + 该发布标记 fail + 通知全部项目管理员
```

注意：`latest` 可能**本来就指向测试版本**（真实环境里它仍指向 `0.10.5-ci.x86-64.0`）。平台不擅自修正历史遗留，只保证"本次发布没让它变得更糟"，并在工作台长期标记为待办事项。

### 6.4 dist-tag 回滚

```text
POST /releases/:id/rollback/preview  → 返回 from/to 与影响面
POST /releases/:id/rollback          → 权限 + 二次确认 + 审计
  ├─ 模式 A（默认）：返回可复制命令，人工在授权环境执行
  └─ 模式 B（可选）：触发受控 Jenkins Job 执行（需运维先建好该 Job）
```

平台自身永不直接调用 `npm dist-tag`。

## 7. 鉴权与会话

| 项 | 方案 |
| --- | --- |
| 密码存储 | argon2id（`memoryCost=64MB, timeCost=3, parallelism=1`） |
| 会话 | 服务端 session 表 + 随机 sessionId（`httpOnly` / `Secure` / `SameSite=Lax` Cookie），默认 8h，记住我 30 天 |
| CSRF | 双提交 Cookie：`XSRF-TOKEN` Cookie + `X-XSRF-TOKEN` 头，写接口校验 |
| 限流 | 登录 5 次/5 分钟/IP；写接口 30 次/分钟/用户 |
| 锁定 | 连续 5 次失败锁定 10 分钟（AUTH-03） |
| 禁用即刻生效 | 用户 `disabled` 时鉴权中间件校验 `tokenVersion`，立即拒绝并清理会话 |
| 扩展 | 预留 `auth_provider` 字段（`local` / `oidc` / `ldap`） |

## 8. RBAC 与审计

### 8.1 权限判定

```ts
// 路由声明式声明所需权限，中间件统一判定
app.post('/builds', { preHandler: [requirePermission('build:trigger')] }, handler)

// 数据级权限（如"只能取消自己触发的构建"）在 service 层补充判定
assertCanCancel(user, build)   // 开发成员仅可取消 triggeredBy === user.id
```

系统管理员是超级权限；项目管理员权限限定在 `project_members` 所属项目内。

### 8.2 审计事件模型

```ts
type AuditEvent = {
  actorType: 'user' | 'ai' | 'system'
  actorId: string            // 用户 id；ai 场景为 "user#id x agent"
  event: string              // 见下表
  resourceType: string       // build | release | agent | user | setting
  resourceId: string
  snapshot: Json             // 关键输入快照（参数、diff、门禁结果）
  result: 'success' | 'failure'
  ip?: string
  requestId: string
}
```

必须埋点的事件：

| 事件 | 触发点 | 快照内容 |
| --- | --- | --- |
| `auth.login` / `auth.login_failed` | 登录 | 用户名、IP、UA |
| `user.create` / `user.disable` / `user.role_change` | 用户管理 | 变更前后 |
| `project.member_change` | 成员管理 | 成员、旧角色、新角色 |
| `build.trigger` / `build.rerun` / `build.cancel` | 构建操作 | 参数全量快照 |
| `artifact.download` | 产物下载 | 产物名、大小、sha256 |
| `release.preflight` / `release.start` / `release.finish` / `release.rollback` | 发布 | 门禁结果、`latest` 前后快照 |
| `setting.update` | 项目配置 | 字段级 diff |
| `ai.invoke` / `ai.apply` | AI 能力点 | 能力点编号、输入摘要、是否人审 |

审计表 append-only：应用层不提供 UPDATE/DELETE；`prevHash` 串联记录哈希，`GET /admin/audit/verify` 可校验链完整性（AUD-05）。

## 9. AI 能力点（COP）

### 9.1 Provider 抽象

```ts
interface AiProvider {
  readonly id: string                     // 'openai-compatible' | 'rules'
  complete(req: { system: string; user: string; maxTokens: number }): Promise<string>
}
```

- 未配置 `FACTORY_LLM_API_KEY` → 使用 `rules` Provider（纯规则/统计），所有面板照常可用，只是结论精度下降；UI 标注"规则引擎"。
- 建议平台侧独立配置 Key，不复用 Jenkins 的 LLM 凭据（避免跨系统耦合）。

### 9.2 五个能力点与输入

| 能力点 | 输入 | 输出结构 |
| --- | --- | --- |
| COP-01 日志诊断 | 失败构建的阶段列表 + 误差行上下文（前后 5 行）+ 历史同类失败 | 指标卡、根因判定、证据链（可跳转日志行）、建议动作（可一键重跑） |
| COP-02 参数推荐 | 最近 N 次失败参数 + 本次变更文件 + Agent 的 `agent.json` | 推荐参数 chips、理由、置信度、应用填充按钮 |
| COP-03 构建汇总 | 最近 20 次构建的指标与阶段分布 | 失败率、聚集阶段、Top 失败 Agent、建议 |
| COP-04 门禁解释 | 失败门禁项 + registry 遥测 + 历史同因案例 | 概率分布、修复建议、是否低危可代执行 |
| COP-05 配置建议 | 项目设置 + 构建耗时统计 | diff 预览（字段/旧值/新值）+ 影响面 + 人审确认卡 |

### 9.3 护栏（硬约束）

```text
只读类（COP-01/02/03/04/06）  → 直接返回，不改变系统状态
低危执行类（COP-07）          → 仅限：重跑构建、重试 SHA-256 核验、刷新同步
                                必须二次确认 + 审计标记「用户 × Agent」
高危变更类（COP-05）          → 生成 diff，必须人工点"应用"，应用前校验配置基线版本
发布类（发布 / 回滚 / dist-tag）→ AI 永不代执行，只能建议
```

### 9.4 反馈与缓存

- 每个 AI 面板底部有 👍/👎，写 `ai_feedback`；
- 结果按 `(能力点, 资源 id, 内容 hash)` 缓存到 `ai_insights`，默认 30 分钟；
- 构建运行中不生成 COP-01（无最终结果），仅在终态触发。

### 9.5 脱敏（发送给 LLM 前）

必做替换：`npm_*token*`、`*password*`、`Authorization`、私钥块、含凭据的 URL、内网 IP 段（可配置保留）、完整 SHA-256（保留前 10 后 6）。脱敏规则集中在 `modules/ai/redact.ts`，并有独立单元测试用例集。

## 10. 错误处理与降级

| 场景 | 行为 |
| --- | --- |
| Jenkins 不可达 | 标记 `jenkins:degraded`；读接口返回缓存 + `stale: true` + 顶部横幅；写接口明确失败（不允许假成功） |
| Jenkins 参数定义与平台不一致 | 触发接口返回 `E_PARAM_DRIFT`，并给出差异字段 |
| registry 查询失败 | 发布预检第 4/5 项返回"未知"而非"通过"；不允许在未知状态下发布 |
| 报告 JSON 解析失败 | 构建仍可查看，`build_reports` 记录 `parseError`，UI 展示原始 JSON |
| Git 读取失败 | Agent 数据按缓存展示并标记 `stale`，其余功能不受影响 |
| LLM 调用失败/超时 | 面板展示错误并提供"重试"；不影响任何流水线功能 |
| 数据库不可写 | 只读模式启动（`FACTORY_READONLY=1`），所有写接口 503 |

统一错误响应（见 05 §2.5）：

```json
{ "error": { "code": "E_PARAM_DRIFT", "message": "Jenkins 参数定义与平台不一致", "details": {}, "requestId": "req_01H..." } }
```

## 11. 配置项

| 环境变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `FACTORY_PORT` | 否 | `3001` | API 监听端口 |
| `FACTORY_BASE_URL` | 是 | — | 对外访问地址（生成链接、CSRF 校验） |
| `FACTORY_DATABASE_URL` | 否 | `file:./data/factory.db` | 默认 SQLite；可填 `postgresql://...` |
| `FACTORY_SECRET_KEY` | 是 | — | 32 字节密钥（加密凭据 + 会话签名） |
| `FACTORY_JENKINS_URL` | 是 | — | 如 `http://127.0.0.1:8080` |
| `FACTORY_JENKINS_USER` / `FACTORY_JENKINS_TOKEN` | 是 | — | 服务账号与 API Token |
| `FACTORY_JENKINS_JOBS` | 是 | — | 绑定的 Job（逗号分隔，第一个为主 Job） |
| `FACTORY_GIT_PROVIDER` | 是 | `gitcode` | `gitcode` / `atomgit` |
| `FACTORY_GIT_REPO` | 是 | — | `openeuler/witty-agents` |
| `FACTORY_GIT_TOKEN` | 否 | — | 只读 Token；仅私有仓库读取需要，公开仓库留空 |
| `FACTORY_LLM_PROVIDER` | 否 | 空 | 空 = 规则引擎 |
| `FACTORY_LLM_API_KEY` | 否 | — | — |
| `FACTORY_LLM_BASE_URL` / `FACTORY_LLM_MODEL` | 否 | — | OpenAI 兼容端点与模型名 |
| `FACTORY_LOG_LEVEL` | 否 | `info` | Pino 级别 |
| `FACTORY_READONLY` | 否 | `0` | 只读模式 |
