# 04 · 数据模型

## 1. 关系概览

```text
users ──┬── sessions
        ├── project_members ── projects ── project_settings
        ├── audit_logs
        └── notifications

projects ──┬── project_settings        （仓库绑定、Jenkins Job 绑定、参数默认值）
           ├── agents                 （来自 ci/agents.json 的投影，只读）
           ├── builds ──┬── build_stages
           │            ├── build_logs        （分片）
           │            ├── build_reports     （结构化报告）
           │            └── artifacts
           └── releases ──┬── release_gates
                          ├── dist_tag_events
                          └── ai_insights（复核/解释结果）

sync_states（每个采集器的水位）    ai_feedback    audit_logs
```

设计原则：

- **上游事实与平台事实分离**：`agents` / `builds` / `releases` 是上游投影，可被采集器覆盖；`users` / `audit_logs` / `project_settings` 是平台独有，绝不被采集覆盖。
- **保留原始证据**：报告 JSON 原文、日志原文、参数快照都入库（或落文件 + 指针），保证可追溯。
- **可重放**：任何派生字段（成功率、健康度）都能从原始记录重算，不依赖缓存表。

## 2. 表定义

> 语法以 SQLite 为准；迁移到 PostgreSQL 时把 `TEXT` 保持、`INTEGER PRIMARY KEY AUTOINCREMENT` 换成 `BIGSERIAL`、时间字段统一 `TIMESTAMPTZ`。所有时间字段存 UTC ISO8601 字符串或 epoch ms，前端本地化展示。

### 2.1 身份与权限

```sql
CREATE TABLE users (
  id            TEXT PRIMARY KEY,              -- ulid
  username      TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL,
  password_hash TEXT,                          -- argon2id；SSO 用户为 NULL
  auth_provider TEXT NOT NULL DEFAULT 'local', -- local | oidc | ldap
  system_role   TEXT NOT NULL DEFAULT 'viewer',-- sysadmin | pm | dev | viewer
  status        TEXT NOT NULL DEFAULT 'active',-- active | disabled
  token_version INTEGER NOT NULL DEFAULT 1,    -- 改密码/禁用时自增，用于即时失效
  last_login_at TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE sessions (
  id          TEXT PRIMARY KEY,                -- 随机 32B，存哈希
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_version INTEGER NOT NULL,
  ip          TEXT,
  user_agent  TEXT,
  expires_at  TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_exp  ON sessions(expires_at);

CREATE TABLE login_attempts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT NOT NULL,
  ip         TEXT NOT NULL,
  success    INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_login_attempts ON login_attempts(username, ip, created_at);
```

### 2.2 项目与配置

```sql
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  key         TEXT NOT NULL UNIQUE,            -- 如 witty-agents
  name        TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'active',  -- active | archived
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE project_members (
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role        TEXT NOT NULL,                   -- pm | dev | viewer
  joined_at   TEXT NOT NULL,
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE project_settings (
  project_id   TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  -- 仓库绑定
  git_provider TEXT NOT NULL DEFAULT 'gitcode',
  git_repo     TEXT NOT NULL,                  -- openeuler/witty-agents
  git_branch   TEXT NOT NULL DEFAULT 'master',
  script_path  TEXT NOT NULL DEFAULT 'Jenkinsfile',
  -- Jenkins 绑定（可多个 Job：主 Job + smoke Job）
  jenkins_jobs TEXT NOT NULL,                  -- JSON: [{name, role:'main'|'smoke', arch}]
  -- 14 个参数的默认值（JSON，字段名与 Jenkinsfile 一致）
  param_defaults TEXT NOT NULL,
  -- 并发与保留
  version_baseline INTEGER NOT NULL DEFAULT 1, -- 乐观锁：配置被改动时自增
  updated_by   TEXT,
  updated_at   TEXT NOT NULL
);
```

`param_defaults` 示例（与真实 Jenkinsfile 的 14 个参数一一对应）：

```json
{
  "AGENT": "auto",
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
  "NPM_DIST_TAG": "latest"
}
```

### 2.3 Agent 投影

```sql
CREATE TABLE agents (
  id            TEXT NOT NULL,                 -- shennong-crash（来自 agents.json）
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  display_name  TEXT,                          -- 来自 agent.json.displayName / package.json
  directory     TEXT NOT NULL,                 -- shennong-crash-agent
  enabled       INTEGER NOT NULL,              -- 来自 agents.json.enabled
  config_path   TEXT NOT NULL,                 -- shennong-crash-agent/ci/agent.json
  path_prefixes TEXT NOT NULL,                 -- JSON 数组（增量构建依据）
  variants      TEXT,                          -- JSON 数组，如 ["online","offline"]
  package_styles TEXT,                         -- JSON 数组
  archs         TEXT,                          -- JSON 数组
  registry_packages TEXT,                      -- JSON: {online: "witty-agent-shennong-online"}
  publish_requires_all_variants INTEGER,
  version       TEXT,                          -- 来自 package.json
  registry_name TEXT,                          -- npm 上的实际包名（如 witty-agent-shennong）
  skills        TEXT,                          -- JSON 数组 [{id, description}]
  description   TEXT,
  synced_commit TEXT,                          -- 同步时的 master commit
  synced_at     TEXT NOT NULL,
  PRIMARY KEY (project_id, id)
);

### 2.4 构建域

```sql
CREATE TABLE builds (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL,
  job_name      TEXT NOT NULL,                 -- witty-agents-builder / ...-smoke-arm
  number        INTEGER,                       -- Jenkins 构建号；queued 时为 NULL
  status        TEXT NOT NULL,                 -- queued|running|success|failure|aborted|stale
  agent         TEXT,                          -- auto|all|<agent id>（AGENT 参数）
  params        TEXT NOT NULL,                 -- JSON：14 参数全量快照
  triggered_by  TEXT,                          -- user id | 'pollSCM' | 'timer' | 'ai:<userId>'
  trigger_type  TEXT NOT NULL,                 -- manual | scm | rerun | replay | ai
  commit_sha    TEXT,
  commit_message TEXT,
  branch        TEXT,
  started_at    TEXT,
  finished_at   TEXT,
  duration_ms   INTEGER,
  stage_failed  TEXT,                          -- 失败阶段名（便于列表直接展示）
  reports_ok    INTEGER,                       -- 报告是否已消化（0/1）
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_builds_job_no ON builds(project_id, job_name, number) WHERE number IS NOT NULL;
CREATE INDEX idx_builds_list ON builds(project_id, number DESC);
CREATE INDEX idx_builds_status ON builds(project_id, status);
CREATE INDEX idx_builds_agent ON builds(project_id, agent, number DESC);

CREATE TABLE build_stages (
  build_id    TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  seq         INTEGER NOT NULL,
  name        TEXT NOT NULL,
  status      TEXT NOT NULL,                   -- success|failed|aborted|skipped|running|not_executed
  duration_ms INTEGER,
  PRIMARY KEY (build_id, seq)
);

CREATE TABLE build_logs (                      -- 分片存储，避免单行过大
  build_id   TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  byte_start INTEGER NOT NULL,
  byte_end   INTEGER NOT NULL,
  line_start INTEGER NOT NULL,
  line_end   INTEGER NOT NULL,
  content    TEXT NOT NULL,                    -- 已剥离 ANSI 的纯文本
  PRIMARY KEY (build_id, chunk_index)
);

CREATE TABLE build_reports (                   -- 结构化报告，字段级查询
  build_id    TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,                   -- build_plan|ci_summary|package_report|install_flow|publish_smoke
  agent_id    TEXT,
  variant     TEXT,
  status      TEXT,                            -- passed|failed|unknown
  payload     TEXT NOT NULL,                   -- 原始 JSON
  parse_error TEXT,
  PRIMARY KEY (build_id, kind, COALESCE(agent_id,''), COALESCE(variant,''))
);

CREATE TABLE artifacts (
  id           TEXT PRIMARY KEY,
  build_id     TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  file_name    TEXT NOT NULL,
  kind         TEXT NOT NULL,                  -- report_json|tgz_online|tgz_offline|log|other
  size_bytes   INTEGER,
  sha256       TEXT,
  agent_id     TEXT,
  variant      TEXT,
  arch         TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX idx_artifacts_build ON artifacts(build_id);
```

### 2.5 发布域

```sql
CREATE TABLE releases (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL,
  kind          TEXT NOT NULL,                 -- package_publish | smoke_publish
  package_name  TEXT NOT NULL,                 -- witty-agent-shennong
  version       TEXT NOT NULL,                 -- 0.10.6-ci.aarch64.0
  dist_tag      TEXT NOT NULL,                 -- arm-test | x86-test
  registry      TEXT NOT NULL DEFAULT 'https://registry.npmjs.org/',
  arch          TEXT NOT NULL,                 -- aarch64 | x86_64
  build_id      TEXT REFERENCES builds(id),    -- 关联构建
  source_build  TEXT,                          -- 产物来源构建号（可能是更早的构建）
  status        TEXT NOT NULL,                 -- preflight_failed|running|passed|failed|manual_review|rolled_back
  latest_before TEXT,                          -- 发布前 latest 指向
  latest_after  TEXT,                          -- 发布后 latest 指向
  candidate_sha256 TEXT,
  redownload_sha256 TEXT,
  integrity     TEXT,
  operator_id   TEXT NOT NULL,
  confirmed_publish INTEGER NOT NULL DEFAULT 0,-- 是否勾选 CONFIRM_PUBLIC_PUBLISH
  started_at    TEXT NOT NULL,
  finished_at   TEXT
);
CREATE INDEX idx_releases_pkg ON releases(package_name, started_at DESC);
CREATE INDEX idx_releases_status ON releases(project_id, status);

CREATE TABLE release_gates (
  release_id  TEXT NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
  seq         INTEGER NOT NULL,
  code        TEXT NOT NULL,                   -- repo_whitelist|commit_on_master|variants_passed|version_free|dist_tag_safe
  status      TEXT NOT NULL,                   -- pass|fail|unknown
  evidence    TEXT NOT NULL,                   -- 展示给人看的证据字符串
  checked_at  TEXT NOT NULL,
  PRIMARY KEY (release_id, seq)
);

CREATE TABLE dist_tags (
  project_id   TEXT NOT NULL,
  package_name TEXT NOT NULL,
  tag          TEXT NOT NULL,
  version      TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  updated_by   TEXT,
  PRIMARY KEY (project_id, package_name, tag)
);

CREATE TABLE dist_tag_events (
  id           TEXT PRIMARY KEY,
  package_name TEXT NOT NULL,
  tag          TEXT NOT NULL,
  from_version TEXT,
  to_version   TEXT NOT NULL,
  source       TEXT NOT NULL,                  -- publish | rollback | external
  release_id   TEXT REFERENCES releases(id),
  actor_id     TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX idx_dte_pkg ON dist_tag_events(package_name, tag, created_at DESC);
```

### 2.6 审计、AI 与系统

```sql
CREATE TABLE audit_logs (
  id            TEXT PRIMARY KEY,
  ts            TEXT NOT NULL,
  actor_type    TEXT NOT NULL,                 -- user | ai | system
  actor_id      TEXT NOT NULL,                 -- 用户 id；AI 场景形如 "u_123 x agent"
  actor_label   TEXT NOT NULL,                 -- 展示名，如 "张伟 × Agent"
  event         TEXT NOT NULL,                 -- build.trigger / release.start / ...
  resource_type TEXT NOT NULL,
  resource_id   TEXT,
  snapshot      TEXT,                          -- JSON
  result        TEXT NOT NULL,
  ip            TEXT,
  request_id    TEXT NOT NULL,
  prev_hash     TEXT,                          -- 哈希链
  hash          TEXT NOT NULL
);
CREATE INDEX idx_audit_ts ON audit_logs(ts DESC);
CREATE INDEX idx_audit_event ON audit_logs(event, ts DESC);
CREATE INDEX idx_audit_actor ON audit_logs(actor_id, ts DESC);

CREATE TABLE ai_insights (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,                   -- COP-01..COP-06
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  provider    TEXT NOT NULL,                   -- openai-compatible | rules
  payload     TEXT NOT NULL,                   -- JSON 结果
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_ai_cache ON ai_insights(kind, resource_type, resource_id, content_hash);

CREATE TABLE ai_feedback (
  id          TEXT PRIMARY KEY,
  insight_id  TEXT REFERENCES ai_insights(id) ON DELETE CASCADE,
  user_id     TEXT NOT NULL,
  rating      TEXT NOT NULL,                   -- up | down
  comment     TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE notifications (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  level       TEXT NOT NULL,                   -- info | warning | error
  title       TEXT NOT NULL,
  body        TEXT,
  link        TEXT,
  read_at     TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_notif_user ON notifications(user_id, created_at DESC);

CREATE TABLE sync_states (
  name           TEXT PRIMARY KEY,             -- build_poller / repo_sync / registry_watcher ...
  last_run_at    TEXT,
  last_success_at TEXT,
  last_error     TEXT,
  cursor         TEXT,                         -- 水位（如最后处理的构建号、日志偏移）
  lock_owner     TEXT,
  lock_expires_at TEXT
);
```

## 3. 枚举与状态机

| 域 | 字段 | 取值 | 说明 |
| --- | --- | --- | --- |
| 用户 | `system_role` | `sysadmin` / `pm` / `dev` / `viewer` | 系统级角色 |
| 项目成员 | `role` | `pm` / `dev` / `viewer` | 项目级角色（sysadmin 天然全项目） |
| 构建 | `status` | `queued` / `running` / `success` / `failure` / `aborted` / `stale` | `stale` 由平台超时保护产生 |
| 阶段 | `status` | `success` / `failed` / `aborted` / `skipped` / `running` / `not_executed` | `skipped` = 条件未满足；`not_executed` = 因前序失败未到达 |
| 发布 | `status` | `preflight_failed` / `running` / `passed` / `failed` / `manual_review` / `rolled_back` | `manual_review` 对应 SHA-256 不一致 |
| 门禁 | `status` | `pass` / `fail` / `unknown` | `unknown` 表示上游查询失败，禁止据此放行 |
| 报告 | `status` | `passed` / `failed` / `unknown` | 来自报告 JSON 的 `status` 字段 |

构建状态迁移约束（服务层强制）：

```text
queued → running → success|failure|aborted|stale
queued → aborted            （排队中被取消）
终态不可再变更（除非采集到上游修正，写审计说明）
```

## 4. 索引与典型查询

| 查询场景 | SQL 要点 |
| --- | --- |
| 构建列表（筛选 + 分页） | `WHERE project_id=? AND (? IS NULL OR status=?) AND (? IS NULL OR agent=?) AND number<=? ORDER BY number DESC LIMIT ?`；依赖 `idx_builds_list` |
| 构建详情阶段 | `SELECT * FROM build_stages WHERE build_id=? ORDER BY seq` |
| 日志分片按需加载 | `WHERE build_id=? AND line_start<=? AND line_end>=?` |
| Agent 健康度 | 对每个 agent 取最近 20 次构建的 `status` 聚合（可用物化视图/定时快照，避免每次全表扫描） |
| 发布历史 | `idx_releases_pkg` + `ORDER BY started_at DESC` |
| 审计筛选 | `idx_audit_ts` + 事件/操作者复合索引；导出走游标分页流式输出 |
| `latest` 漂移检测 | `dist_tags` 单表查询，`RegistryWatcher` 每 5 分钟比对 |

## 5. 数据保留与清理

| 数据 | 平台保留策略 | 与 Jenkins 对照 |
| --- | --- | --- |
| 构建记录 | 200 次/项目（可配置） | Jenkins `logRotator` 仅保留 20 次构建、10 份产物 |
| 构建日志 | 90 天 或 最近 50 次构建（先到者优先保留） | Jenkins 不保证保留 |
| 归档产物 | **不复制 tgz 到平台**，只存清单与 sha256；下载走 Jenkins 归档链接 | 产物仍在 Jenkins |
| 报告 JSON | 永久（体积小，是核心证据） | Jenkins 保留 10 份 |
| 审计日志 | 2 年（合规要求可调整） | Jenkins 无对应能力 |
| AI 缓存 | 30 天 | — |
| 通知 | 90 天 | — |

清理任务（`Retention`）需遵守：**先删日志分片与产物清单，再删构建记录**；删除前把构建记录归入 `archived` 状态（保留列表可查的行，去掉重量字段）而不是硬删，便于审计追溯。

## 6. 迁移策略

- 使用 Prisma Migrate，迁移文件入库（`prisma/migrations/`）；
- 服务启动时执行 `migrate deploy`（只做前滚迁移，不回滚）；
- SQLite → PostgreSQL 的差异：`COALESCE` 复合主键改为生成列或唯一索引；`TEXT` 时间字段在 PG 下可选 `TIMESTAMPTZ`，但为了跨库一致建议保持 TEXT；
- 破坏性变更（删列/改类型）必须走两步：新增列 → 双写 → 数据回填 → 切换读取 → 下线旧列。

## 7. 上游 JSON → 平台字段映射

| 上游来源 | 字段 | 平台落点 |
| --- | --- | --- |
| `ci/agents.json` | `agents[].id/enabled/configPath/changedPathPrefixes` | `agents.*` |
| `<agent>/ci/agent.json` | `displayName/directory/variants/packageStyles/supportedArchitectures/registryPackages/publishRequiresAllVariants` | `agents.*` |
| `<agent>/package.json` | `version/name/description/keywords` | `agents.version`、`agents.registry_name`、`agents.description` |
| `ci-artifacts/build-plan.json` | `status/sourceCommit/requestedAgent/requestedVariant/packageStyle/targetArchitecture/publish/agents[]` | `build_reports(kind=build_plan)`；`builds.commit_sha` |
| `<agent>/artifacts/ci-summary.json` | `status/variant/...` | `build_reports(kind=ci_summary, agent, variant).status` |
| `<agent>/artifacts/*-package-report.json` | `packageName/version/sizeBytes/sha256/gates` | `build_reports(kind=package_report)` + `artifacts.sha256` |
| `<agent>/ci-reports/install-flow-*.json` | `status/setupIdempotent/configureIdempotent/removeIdempotent` | `build_reports(kind=install_flow)` |
| `ci-artifacts/npm-publish-smoke-summary.json` | `status/packageName/version/distTag/latestTag{before,after}/*Sha256/integrity` | `build_reports(kind=publish_smoke)` → `releases.*` |
| Jenkins `wfapi/describe` | `stages[].name/status/durationMillis` | `build_stages.*` |
| Jenkins build actions | `parameters[]`、`causes[].shortDescription` | `builds.params`、`builds.triggered_by/trigger_type` |
| npm registry | `versions`、`dist-tags`、`time` | `dist_tags`、`dist_tag_events`、`releases.latest_after` |
