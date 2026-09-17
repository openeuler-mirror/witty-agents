# 05 · API 契约

## 1. 通用约定

| 项 | 约定 |
| --- | --- |
| Base URL | `/api/v1`（前端经 Nginx 反代，同源，无跨域） |
| 内容类型 | 请求/响应 `application/json; charset=utf-8`；日志流 `text/event-stream`；导出 `text/csv` |
| 鉴权 | 会话 Cookie（`factory_session`）；写操作额外带 `X-XSRF-TOKEN` |
| 时间 | 请求与响应统一 ISO8601 UTC（`2026-09-17T02:31:00Z`），前端本地化 |
| 分页 | 游标优先：`?cursor=<opaque>&limit=20`；列表响应含 `nextCursor`。偏移分页仅用于导出 |
| 排序 | `?sort=number&order=desc`，白名单字段 |
| 过滤 | 具名查询参数（如 `status=running,failure`、`agent=shennong-crash`、`from=&to=`） |
| 幂等 | 所有写接口接受 `Idempotency-Key` 头；相同 key 在 10 分钟内返回同一结果（防止重复触发构建） |
| 请求追踪 | 响应头 `X-Request-Id`，与审计 `request_id` 一致 |
| 字段裁剪 | `?fields=` 仅在详情接口开放（列表固定返回轻量字段） |

## 2. 响应与错误

### 2.1 成功

```json
{ "data": { }, "meta": { "nextCursor": "b_100", "stale": false } }
```

### 2.2 列表

```json
{
  "data": [ { "number": 21, "status": "success" } ],
  "meta": { "nextCursor": "b_20", "total": 137, "stale": false }
}
```

### 2.3 SSE

```text
event: log
data: {"lines":[{"no":812,"text":"[Pipeline] stage","level":"info"}],"lastOffset":41233}

event: status
data: {"status":"running","stage":"Build Packages"}

event: end
data: {"status":"success","finishedAt":"2026-09-15T12:49:29Z"}
```

### 2.4 HTTP 状态码

| 码 | 语义 |
| --- | --- |
| 200 | 成功 |
| 201 | 创建（如触发构建返回占位记录） |
| 202 | 已接受（异步动作：触发、取消、发布） |
| 400 | 参数非法（`E_VALIDATION`） |
| 401 | 未登录或会话失效（`E_UNAUTHENTICATED`） |
| 403 | 权限不足（`E_FORBIDDEN`） |
| 404 | 资源不存在（`E_NOT_FOUND`） |
| 409 | 状态冲突（`E_CONFLICT`，如构建已结束无法取消） |
| 422 | 业务规则拒绝（`E_GATE_FAILED`、`E_PARAM_DRIFT`） |
| 429 | 限流（`E_RATE_LIMITED`） |
| 503 | 上游不可用（`E_UPSTREAM_UNAVAILABLE`、只读模式 `E_READONLY`） |

### 2.5 错误体

```json
{
  "error": {
    "code": "E_GATE_FAILED",
    "message": "发布门禁未通过：SHA-256 回下载核验失败",
    "details": { "failedGates": ["sha256_compare"] },
    "requestId": "req_01HA..."
  }
}
```

## 3. 端点总表

图例：`R` = `audit:read` 等只读权限；权限点见 [01](01-product-and-use-cases.md) §3。

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/login` | 登录 | 公开 |
| POST | `/auth/logout` | 退出 | 登录 |
| GET | `/auth/me` | 当前用户 + 权限点集合 | 登录 |
| POST | `/auth/password` | 修改密码 | 登录 |
| GET | `/users` | 用户列表 | `user:manage` |
| POST | `/users` | 新建用户 | `user:manage` |
| PATCH | `/users/:id` | 编辑用户 | `user:manage` |
| POST | `/users/:id/disable` / `/enable` | 启停用户 | `user:manage` |
| POST | `/users/:id/reset-password` | 重置密码 | `user:manage` |
| GET | `/projects` | 项目列表 | 登录（仅返回可访问的） |
| GET | `/projects/:id` | 项目概览（统计聚合） | 项目成员 |
| GET | `/projects/:id/members` | 成员列表 | 项目成员 |
| POST/PATCH/DELETE | `/projects/:id/members[/:userId]` | 成员管理 | `project:member` |
| GET/PATCH | `/projects/:id/settings` | 项目设置读写 | 读：项目成员 / 写：`project:config` |
| POST | `/projects/:id/settings/test` | 连通性测试（Git / Jenkins） | `project:config` |
| POST | `/projects/:id/agents/sync` | 手动同步 `agents.json` | `project:config` |
| GET | `/projects/:id/agents` | Agent 列表（含版本、Skills、健康度） | 项目成员 |
| GET | `/projects/:id/agents/:agentId` | Agent 详情 | 项目成员 |
| GET | `/projects/:id/builds` | 构建列表（筛选 + 游标分页） | 项目成员 |
| POST | `/projects/:id/builds` | 触发构建 | `build:trigger`（含 `PUBLISH=true` 时额外需 `release:publish`） |
| GET | `/projects/:id/builds/:no` | 构建详情（含阶段、报告摘要） | 项目成员 |
| POST | `/projects/:id/builds/:no/cancel` | 取消 | `build:cancel` |
| POST | `/projects/:id/builds/:no/rerun` | 重跑 | `build:rerun` |
| POST | `/projects/:id/builds/:no/replay` | Replay 失败阶段（P2） | `project:config` |
| GET | `/projects/:id/builds/:no/log` | 日志分页读取（`?fromLine=&limit=`） | 项目成员 |
| GET | `/projects/:id/builds/:no/log/stream` | 日志 SSE | 项目成员 |
| GET | `/projects/:id/builds/:no/artifacts` | 产物清单 | 项目成员 |
| GET | `/projects/:id/builds/:no/artifacts/:artifactId/preview` | JSON 报告预览 | 项目成员 |
| GET | `/projects/:id/builds/:no/artifacts/:artifactId/download` | 产物下载（302 到 Jenkins 或代理流） | `artifact:download` |
| GET | `/projects/:id/builds/export.csv` | 构建记录导出 | `project:config` |
| GET | `/projects/:id/releases` | 发布列表 | 项目成员 |
| POST | `/projects/:id/releases/preflight` | 门禁预检（不产生副作用） | `release:publish` |
| POST | `/projects/:id/releases` | 发起发布 | `release:publish` |
| GET | `/projects/:id/releases/:id` | 发布详情（门禁、链路、双哈希） | 项目成员 |
| POST | `/projects/:id/releases/:id/retry-verify` | 重试回下载核验 | `release:publish` |
| POST | `/projects/:id/releases/:id/rollback/preview` | 回滚预览 | `release:rollback` |
| POST | `/projects/:id/releases/:id/rollback` | 执行回滚 | `release:rollback` |
| GET | `/projects/:id/dist-tags` | dist-tag 当前指向与历史 | 项目成员 |
| GET | `/admin/audit` | 审计查询 | `audit:read` |
| GET | `/admin/audit/export.csv` | 审计导出 | `audit:read` |
| GET | `/admin/audit/verify` | 审计哈希链校验 | `user:manage` |
| GET | `/notifications` | 我的通知 | 登录 |
| POST | `/notifications/read` | 标记已读 | 登录 |
| POST | `/ai/diagnose/build/:no` | COP-01 日志诊断 | `ai:invoke` |
| POST | `/ai/summarize/builds` | COP-03 构建汇总 | `ai:invoke` |
| POST | `/ai/suggest/params` | COP-02 参数推荐 | `ai:invoke` |
| POST | `/ai/explain/gate` | COP-04 门禁解释 | `ai:invoke` |
| POST | `/ai/suggest/settings` | COP-05 配置建议（返回 diff） | `ai:invoke` |
| POST | `/ai/apply/settings` | 应用配置建议（高危，人审） | `ai:apply:high` |
| POST | `/ai/feedback` | 👍/👎 反馈 | 登录 |
| GET | `/system/health` | 平台与上游健康（Jenkins、DB、同步水位） | 登录 |

## 4. 关键端点详细

### 4.1 触发构建

`POST /api/v1/projects/{id}/builds`

```json
{
  "mode": "incremental",
  "agent": "auto",
  "params": {
    "VARIANT": "default",
    "PACKAGE_STYLE": "organization",
    "TARGET_ARCH": "native",
    "PYTHON_BIN": "python3.11",
    "PYPI_INDEX_URL": "https://mirrors.huaweicloud.com/repository/pypi/simple",
    "OCR_MODEL_CACHE_DIR": "/home/witty-agents-jenkins/ocr-model-cache",
    "RUN_REAL_INSTALL_VALIDATION": true,
    "STRICT_OFFLINE_NETWORK_CHECK": true,
    "PUBLISH": false,
    "NPM_CREDENTIAL_ID": "npm-token",
    "GIT_CREDENTIAL_ID": "",
    "NPM_REGISTRY": "https://registry.npmjs.org/",
    "NPM_DIST_TAG": "x86-test"
  },
  "idempotencyKey": "trigger-20260917-001"
}
```

- `mode`：`incremental` → `AGENT=auto`；`full` → `AGENT=all`；`single` → 使用 `agent` 字段。
- 服务端会覆盖 `agent` 到 `params.AGENT`，避免两处冲突。
- `PUBLISH=true` 时服务端强制 `VARIANT=all`（`publishRequiresAllVariants`）并返回 422 说明原因。

响应 `202`：

```json
{
  "data": {
    "buildId": "b_01HA...",
    "status": "queued",
    "jobName": "witty-agents-builder",
    "queueUrl": "http://127.0.0.1:8080/queue/item/42/",
    "warnings": [
      { "code": "W_DIST_TAG_LATEST", "message": "NPM_DIST_TAG 默认值为 latest，已按平台策略拒绝；请显式指定 x86-test / arm-test" }
    ]
  }
}
```

### 4.2 构建详情

`GET /api/v1/projects/{id}/builds/{no}`

```json
{
  "data": {
    "number": 21,
    "jobName": "witty-agents-builder",
    "status": "success",
    "agent": "auto",
    "triggeredBy": { "type": "scm", "label": "pollSCM" },
    "commit": { "sha": "6cdfd81aeea99185259aa4223f5c7dcede68233f", "short": "6cdfd81", "message": "feat(nl2sql): 统一为 setup+configure 双命令结构 (0.2.0)" },
    "startedAt": "2026-09-15T12:48:03Z",
    "finishedAt": "2026-09-15T12:49:29Z",
    "durationMs": 86000,
    "params": { "AGENT": "auto", "VARIANT": "default", "PUBLISH": false, "TARGET_ARCH": "native" },
    "stages": [
      { "seq": 1, "name": "Initialize Parameters", "status": "success", "durationMs": 3000 },
      { "seq": 8, "name": "Artifact Gates", "status": "success", "durationMs": 41000 },
      { "seq": 11, "name": "Publish to npm", "status": "skipped", "durationMs": null }
    ],
    "reports": [
      { "kind": "ci_summary", "agentId": "shennong-crash", "variant": "online", "status": "passed" },
      { "kind": "ci_summary", "agentId": "nl2sql", "variant": "online", "status": "passed" }
    ],
    "artifacts": [
      { "id": "a_1", "fileName": "openeuler-agent-shennong-crash-online-0.10.6.tgz", "sizeBytes": 4404019, "kind": "tgz_online", "agentId": "shennong-crash" },
      { "id": "a_2", "fileName": "ci-artifacts/build-plan.json", "sizeBytes": 1228, "kind": "report_json" }
    ]
  },
  "meta": { "stale": false }
}
```

### 4.3 日志读取与流式

`GET /api/v1/projects/{id}/builds/{no}/log?fromLine=800&limit=200`

```json
{
  "data": {
    "lines": [
      { "no": 800, "text": "──── stage Artifact Gates ────", "level": "stage" },
      { "no": 801, "text": "gate: online-package-report.json exists PASS", "level": "info" }
    ],
    "totalLines": 1180
  }
}
```

- `level` 由服务端判定：`error` / `warn` / `stage` / `pass` / `info`，前端直接映射颜色，不在浏览器里做正则重算。
- 运行中构建时 `totalLines` 为当前水位，前端以 SSE 追加。

`GET .../log/stream`（SSE）

```text
event: log
data: {"lines":[{"no":1181,"text":"PASS checksum step 3/7","level":"pass"}],"lastOffset":54211,"totalLines":1181}

event: status
data: {"status":"running","stage":"Real Install Flow"}

event: end
data: {"status":"success"}
```

断线重连：前端带 `Last-Event-ID`（= 上次 `lastOffset`），服务端从该偏移继续。

### 4.4 发布预检

`POST /api/v1/projects/{id}/releases/preflight`

```json
{
  "buildNo": 21,
  "packageName": "witty-agent-shennong",
  "version": "0.10.6-ci.aarch64.0",
  "distTag": "arm-test"
}
```

响应 `200`：

```json
{
  "data": {
    "conclusion": "pass",
    "gates": [
      { "code": "repo_whitelist", "status": "pass", "evidence": "origin=https://gitcode.com/openeuler/witty-agents.git ✓" },
      { "code": "commit_on_master", "status": "pass", "evidence": "6cdfd81 是 origin/master 祖先提交 ✓" },
      { "code": "variants_passed", "status": "pass", "evidence": "online ✓ · offline ✓" },
      { "code": "version_free", "status": "pass", "evidence": "0.10.6-ci.aarch64.0 registry 无此版本 ✓" },
      { "code": "dist_tag_safe", "status": "pass", "evidence": "arm-test ✓ · latest=0.10.5-ci.x86-64.0 已快照" }
    ],
    "latestSnapshot": "0.10.5-ci.x86-64.0"
  }
}
```

`conclusion` 取值：`pass` / `fail` / `unknown`。`unknown` 时禁止进入下一步。

### 4.5 发起发布

`POST /api/v1/projects/{id}/releases`

```json
{
  "buildNo": 21,
  "packageName": "witty-agent-shennong",
  "version": "0.10.6-ci.aarch64.0",
  "distTag": "arm-test",
  "channel": "smoke-job",
  "confirmPublicPublish": true,
  "preflightToken": "pf_01HA..."
}
```

- `preflightToken`：预检返回的一次性令牌，有效期 5 分钟，绑定参数指纹；**防止绕过预检直接发布**。
- 服务端重新校验门禁（防止窗口期状态变化），不一致则返回 422 与新的门禁结果。

### 4.6 dist-tag 回滚

`POST /api/v1/projects/{id}/releases/{id}/rollback/preview`

```json
{
  "data": {
    "packageName": "witty-agent-shennong",
    "tag": "arm-test",
    "from": "0.10.6-ci.aarch64.0",
    "to": "0.10.5-ci.aarch64.0",
    "mode": "manual-command",
    "command": "npm dist-tag add witty-agent-shennong@0.10.5-ci.aarch64.0 arm-test --registry=https://registry.npmjs.org/",
    "impact": "下游依赖 arm-test 的用户将回退到上一版本；latest 不受影响"
  }
}
```

`POST .../rollback` 执行（`mode=manual-command` 时仅记录"已人工执行"并写审计；`mode=controlled-job` 时触发受控 Job）。

### 4.7 AI 能力点

`POST /api/v1/ai/diagnose/build/{no}`

```json
{
  "data": {
    "insightId": "ai_01HA...",
    "provider": "openai-compatible",
    "metrics": [
      { "key": "失败阶段", "value": "Artifact Gates", "tone": "bad" },
      { "key": "online 变体", "value": "通过", "tone": "good" }
    ],
    "rootCause": "offline wheel 完整性校验失败：归档包与重打包 wheel 的 SHA-256 不一致",
    "evidence": [
      { "label": "错误 1/3", "text": "ERROR offline wheel integrity check failed: sha256 mismatch", "logLine": 812 }
    ],
    "suggestions": [
      { "seq": 1, "text": "以 online 变体重跑发布链路", "action": { "type": "rerun", "params": { "VARIANT": "online" }, "risk": "low" } },
      { "seq": 2, "text": "切换 PYPI_INDEX_URL 至内网镜像", "action": { "type": "settings_diff", "risk": "high" } }
    ],
    "confidence": 78,
    "disclaimer": "阶段性结论，建议人工复核"
  }
}
```

护栏字段：`action.risk` ∈ `none`（只读）/ `low`（可代执行，需确认）/ `high`（必须人审）。发布类动作不会出现在 `action` 中。

## 5. 错误码表

| 码 | HTTP | 含义 | 处理建议 |
| --- | --- | --- | --- |
| `E_VALIDATION` | 400 | 参数校验失败 | 返回字段级错误 |
| `E_UNAUTHENTICATED` | 401 | 未登录/会话过期 | 前端跳登录 |
| `E_FORBIDDEN` | 403 | 权限不足 | 前端展示"无权限"并隐藏入口 |
| `E_NOT_FOUND` | 404 | 资源不存在 | — |
| `E_CONFLICT` | 409 | 状态冲突（构建已结束、并发修改配置） | 刷新后重试 |
| `E_GATE_FAILED` | 422 | 发布门禁未通过 | 展示失败项 + AI 解释 |
| `E_PARAM_DRIFT` | 422 | Jenkins 参数定义与平台不一致 | 提示同步后重试 |
| `E_PREFLIGHT_REQUIRED` | 422 | 缺少或过期的 preflightToken | 重新预检 |
| `E_RATE_LIMITED` | 429 | 限流 | 退避重试 |
| `E_UPSTREAM_UNAVAILABLE` | 503 | Jenkins/Git/registry 不可用 | 只读降级 + 横幅 |
| `E_READONLY` | 503 | 平台处于只读模式 | 提示运维 |

## 6. 与 Jenkins 参数的一致性校验

平台维护一份参数定义（类型、取值域、默认值、展示分组），启动与每次触发前与 Jenkins 的 `parameterDefinitions` 比对：

| 差异类型 | 行为 |
| --- | --- |
| Jenkins 新增参数 | 记 `W_PARAM_NEW`，触发时使用 Jenkins 默认值，并在 UI 标注"平台未覆盖" |
| Jenkins 删除参数 | 记 `W_PARAM_REMOVED`，从表单移除，禁止提交 |
| 类型不一致（bool ↔ string） | 记 `E_PARAM_DRIFT`，触发被拒绝 |
| 取值域不一致（choice 选项差异） | 记 `E_PARAM_DRIFT`（取值域由 Jenkinsfile 决定，平台不得放宽） |

该机制保证"平台表单永远不超过 Jenkins 的能力边界"，避免平台成为第二份流水线定义。
