# 06 · 前端设计

## 1. 技术栈与工程结构

| 项 | 选择 |
| --- | --- |
| 框架 | Vue 3（`<script setup>` + TypeScript） |
| 构建 | Vite 6 |
| 路由 | Vue Router 4（路由级权限元信息） |
| 状态 | Pinia |
| 请求 | 自研薄封装 `api/`（基于 `fetch`，统一错误码、CSRF、取消、重试策略） |
| 图表 | ECharts（按需引入：环形图、柱状图、趋势图） |
| 样式 | 原生 CSS + CSS 变量（迁移自原型的 `:root` 令牌），不引 UI 框架 |
| 测试 | Vitest（单元）+ Playwright（E2E，覆盖 3 条主旅程） |

```text
ci/factory/packages/web/
├── index.html
├── vite.config.ts
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/
    │   ├── index.ts               # 路由表 + 权限 meta
    │   └── guards.ts              # 登录守卫、权限守卫
    ├── api/
    │   ├── client.ts              # fetch 封装（CSRF、错误码、requestId）
    │   ├── types.gen.ts           # 由 OpenAPI 生成，禁止手改
    │   └── modules/{auth,agents,builds,releases,audit,settings,ai}.ts
    ├── stores/
    │   ├── session.ts             # 当前用户、权限点
    │   ├── project.ts             # 当前项目、设置、同步水位
    │   ├── builds.ts              # 列表筛选条件与分页游标
    │   ├── notifications.ts
    │   └── ui.ts                  # 主题、抽屉、Toast 队列
    ├── layouts/
    │   ├── AppShell.vue           # 顶栏 + 侧栏
    │   └── AuthLayout.vue
    ├── pages/
    │   ├── LoginPage.vue
    │   ├── DashboardPage.vue
    │   ├── ProjectOverviewPage.vue
    │   ├── AgentsPage.vue
    │   ├── BuildsPage.vue
    │   ├── BuildDetailPage.vue
    │   ├── ReleasesPage.vue
    │   ├── ReleaseDetailPage.vue
    │   ├── ProjectSettingsPage.vue
    │   ├── UsersPage.vue
    │   ├── AuditPage.vue
    │   └── NotFoundPage.vue
    ├── components/
    │   ├── common/                # Btn / Tag / Card / Modal / Drawer / Toast / Switch / Pager / Empty
    │   ├── data/                  # DataTable（列配置）/ FilterBar / StatCard / DonutChart / BarChart
    │   ├── build/                 # StageFlow / StageList / LogViewer / ArtifactList / ReportViewer / TriggerDrawer
    │   ├── release/               # GateList / ReleaseTimeline / DistTagTable / RollbackDialog
    │   ├── agent/                 # AgentCard / AgentDetailDrawer / SkillList / InstallCommand
    │   └── ai/                    # AiPanel / AiMetrics / AiConfidence / AiDiffCard / AiActions
    └── styles/
        ├── tokens.css             # 设计令牌（唯一来源）
        └── base.css
```

## 2. 设计令牌

直接继承原型 `assets/style.css` 的 `:root`，作为唯一视觉来源：

```css
:root {
  /* 主色 */
  --primary: #1e6fff;      --primary-hover: #4d8fff;   --primary-bg: #ebf2ff;
  /* 中性 */
  --bg: #f5f7fa;           --surface: #fff;
  --border: #d9e0e8;       --border-2: #e8edf3;
  --text: #1f2a3a;         --text2: #6b7a8d;           --text3: #b0bac5;
  /* 语义 */
  --success: #00b365;      --success-bg: #ecfdf5;
  --warning: #f59e0b;      --warning-bg: #fff7ed;
  --danger: #ef4444;       --danger-bg: #fef2f2;
  --violet: #7c3aed;       --violet-bg: #f5f3ff;
  /* 排版与形状 */
  --mono: ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, monospace;
  --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px;
  --shadow: 0 2px 8px rgba(0,0,0,.06);
  --shadow-up: 0 8px 24px rgba(0,0,0,.1);
}
```

语义映射约定（新增，避免各处硬编码）：

| 语义 | 令牌 |
| --- | --- |
| 构建成功 / 通过 | `--success` + `--success-bg` |
| 构建失败 / 拒绝 | `--danger` + `--danger-bg` |
| 运行中 / 排队 | `--primary` + `--primary-bg`（脉动圆点 `pulse` 动画） |
| 已取消 / 已跳过 / 禁用 | `--text3`（灰） |
| 发布 / AI | `--violet` + `--violet-bg` |
| 待人工核查 | `--warning` + `--warning-bg` |

字体：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`，正文 14px，日志 13px 等宽。

## 3. 路由与权限

| 路由 | 页面 | `meta.permission` | 说明 |
| --- | --- | --- | --- |
| `/login` | LoginPage | — | 独立布局 |
| `/` | 重定向到 `/dashboard` | — | — |
| `/dashboard` | DashboardPage | 登录 | 工作台 |
| `/projects/:projectId` | ProjectOverviewPage | 项目成员 | 概览 |
| `/projects/:projectId/agents` | AgentsPage | 项目成员 | Agent 管理 |
| `/projects/:projectId/builds` | BuildsPage | 项目成员 | 构建列表 |
| `/projects/:projectId/builds/:no` | BuildDetailPage | 项目成员 | 构建详情 |
| `/projects/:projectId/releases` | ReleasesPage | 项目成员 | 发布列表 |
| `/projects/:projectId/releases/:id` | ReleaseDetailPage | 项目成员 | 发布详情 |
| `/projects/:projectId/settings` | ProjectSettingsPage | `project:config`（读权限给项目成员） | 项目设置 |
| `/admin/users` | UsersPage | `user:manage` | 系统管理员 |
| `/admin/audit` | AuditPage | `audit:read` | — |
| `/403` `/404` | — | — | — |

三级权限渲染策略（对应原型的三种"视角"）：

1. **菜单层**：无权限的菜单项不渲染（如只读访客看不到"管理"）。
2. **区块层**：无权限的区块整体隐藏（如触发抽屉里的"发布选项"区块对开发成员隐藏）。
3. **动作层**：`v-permission="'build:trigger'"` 指令隐藏按钮；对"可见但不能点"的场景（如已结束构建的取消按钮）用 `disabled` + tooltip 说明原因。

指令实现：

```ts
// directives/permission.ts
export const vPermission: Directive<HTMLElement, string> = {
  mounted(el, binding) {
    const { has } = useSessionStore()
    if (!has(binding.value)) el.remove()   // 直接移除，不占位
  }
}
```

## 4. 页面规格

### 4.1 工作台 `/dashboard`

| 区块 | 数据来源 | 交互 |
| --- | --- | --- |
| 4 张统计卡（Agent 数、构建总数、成功率、最近发布） | `GET /projects/:id` 聚合 | 点击"最近发布"跳发布详情 |
| AI 趋势解读面板（COP-06） | `POST /ai/...`（按需） | 折叠/展开，👍/👎 |
| Agent 构建/下载统计（环形图 + 对比柱状图） | 聚合接口（含 Agent 维度） | Agent 多选筛选（本地状态）、Top-N 聚合为"其他" |
| 最近构建表（5 行） | 构建列表 `limit=5` | 行点击进详情 |
| 待办发布卡 | 存在 `manual_review` 或 `latest` 漂移时显示 | "去处理" + "AI 解释" |
| 项目动态时间线 | 审计事件流（对本项目可见的事件） | 点击跳对应资源 |
| 近 7 日构建趋势 | 按日聚合 | 图例说明颜色含义（绿=全通过，蓝=部分通过，红=有失败） |

### 4.2 构建列表 `/projects/:id/builds`

- 筛选：状态、Agent（含"增量 auto"选项）、触发人、起止日期；筛选条件同步到 URL query，可分享/刷新保持。
- 分页：服务端游标分页，页大小 20；原型要求"真分页"，不接受前端假分页。
- 行内操作：取消（运行中）、重跑（已完成）、下载产物（成功）、查看（行点击）。
- 顶部操作：触发构建（抽屉）、AI 汇总（COP-03）、导出 CSV。
- 列：编号 / Agent / 参数 chips（VARIANT、STYLE、ARCH）/ 触发人 / 状态 / 耗时 / 时间 / 操作。

### 4.3 触发构建抽屉 `TriggerDrawer`

与原型保持三段折叠结构，并按 Jenkinsfile 的 14 个参数分组：

| 分组 | 参数 | 控件 |
| --- | --- | --- |
| 1 构建范围 | 模式（增量 / 全量 / 指定 Agent） | 三选一卡片；映射到 `AGENT=auto / all / <id>` |
| 2 变体与架构 | `VARIANT`、`PACKAGE_STYLE`、`TARGET_ARCH` | 下拉；选 `offline` 时展开架构提示（必须与节点架构一致） |
| 3 验证 | `RUN_REAL_INSTALL_VALIDATION`、`STRICT_OFFLINE_NETWORK_CHECK` | 开关 |
| 高级（折叠，默认收起） | `PYTHON_BIN`、`PYPI_INDEX_URL`、`OCR_MODEL_CACHE_DIR` | 输入框 |
| 发布（折叠，仅 `release:publish` 可见） | `PUBLISH`、`NPM_CREDENTIAL_ID`、`NPM_REGISTRY`、`NPM_DIST_TAG`、`GIT_CREDENTIAL_ID` | 开关 + 输入；`NPM_DIST_TAG` 禁止填 `latest`（前端拦截 + 后端兜底） |

抽屉行为：

- 打开时按 `mode` 计算初始值，切换模式时保留已填的其他参数；
- 底部固定"取消 / 触发构建"；点击触发前做本地校验，再调接口；
- 触发成功后 Toast 提示"已触发构建 #N（或已入队）"，并立即在列表顶部插入占位行（`queued`）以便用户看到反馈；
- 同一参数集合在 10 分钟内重复提交时，`Idempotency-Key` 命中直接返回同一结果，前端给出"这是刚才那次触发"的提示。

### 4.4 构建详情 `/projects/:id/builds/:no`

| 区块 | 说明 |
| --- | --- |
| 摘要条 | Agent、参数 chips（超出折叠为 `+5`）、触发人、commit（可复制）、耗时（含 240min 上限提示）、起止时间 |
| 操作区 | 下载全量日志、取消、Replay（P2）、重跑 |
| Stage 视图 | 11 个阶段的横向流程图，点击定位日志锚点；未执行阶段灰显并提示"条件阶段未执行" |
| 日志视图 | 见 §4.5 |
| AI 诊断面板（COP-01） | 指标卡 + 根因 + 证据链（可跳日志行）+ 建议（含一键重跑） |
| 产物折叠区 | 分组展示：报告 JSON（可预览）/ online tgz / offline tgz；显示大小与 sha256；下载走鉴权链接 |
| 报告结构化视图 | 把 `ci-summary.json`、`install-flow-*.json` 渲染成"通过项/失败项"清单，而不是让用户读 JSON |

### 4.5 日志视图 `LogViewer`（前端最复杂的组件）

需求（全部来自原型）：分级着色、关键字高亮、上一/下一错误、搜索回车定位、行号点击复制、自动跟随、"回到底部"、虚拟滚动。

| 能力 | 实现要点 |
| --- | --- |
| 分级着色 | 服务端返回 `level` 字段；`stage` 行用分隔样式，`error` 红、`warn` 黄、`pass` 绿 |
| 语义高亮 | 服务端已标注的 span（sha256、版本号、dist-tag、commit、包名、Agent id、URL）用 `<mark>` 类渲染；高亮规则集中在一处，避免与后端脱敏规则冲突 |
| 错误导航 | 维护 `errorLineIndex[]`，点击在上/下一个错误行间跳转并居中 + 闪烁动画 |
| 搜索 | 回车触发：本地在当前已加载分片内高亮命中数；未命中且还有远端数据时，调用 `?search=` 由服务端定位（大日志场景） |
| 虚拟滚动 | 固定行高 22px + 缓冲区上下各 50 行；只渲染可视区域 |
| 自动跟随 | 距底部 < 48px 视为跟随；用户上滚自动取消跟随并显示"回到底部"按钮 |
| 分片加载 | 首屏加载最后 200 行（构建结束时）；向上滚动触发 `fromLine` 更早分片 |
| SSE 追加 | 运行中构建订阅 `/log/stream`，`event:log` 追加行，`event:end` 关闭连接 |
| 复制 | 点击行号复制整行文本 |

### 4.6 发布详情 `/projects/:id/releases/:id`

严格对齐原型的四块内容：门禁清单（5 项，可展开证据）、发布链路时间线（门禁 → 候选包 → publish → 可见性等待 → 回下载 → 哈希比对）、dist-tag 历史表（当前指向 / 上一指向）、关联产物与报告。

门禁项失败时：该项红色高亮 + "AI 解释与修复建议"入口（COP-04）。

### 4.7 其他页面

- **Agent 管理**：卡片墙（名称、id、状态标签、描述、版本、Skills 数、下载数、操作按钮）+ 详情抽屉（能力说明、Skills 清单、在线/离线安装命令可复制、增量前缀、AI 前缀检测）。平台不提供启停开关；卡片仅展示 `agents.json` 的 `enabled` 状态（参与构建 / 已禁用），启停在仓库完成。
- **用户管理**：表格 + 启停开关（二次确认，提示"禁用后会话立即失效"）+ 角色矩阵只读表。
- **审计日志**：时间/操作者/事件/资源/快照列；筛选支持事件类型、"仅 AI 代执行"、关键字；行点击看详情；导出 CSV。
- **项目设置**：Git 绑定、Jenkins 绑定（支持多 Job）、参数默认值（按组分卡片，保存时校验 `version_baseline`）、危险操作区（同步 agents.json、重新拉取报告）。

## 5. 组件清单（关键组件契约）

| 组件 | 关键 props | 事件 |
| --- | --- | --- |
| `DataTable` | `columns`, `rows`, `loading`, `rowKey`, `pageMode: 'cursor'\|'offset'` | `row-click`, `load-more` |
| `FilterBar` | `filters: FilterDef[]`, `modelValue` | `update:modelValue`（同步到 URL） |
| `StatusTag` | `status`, `kind: 'build'\|'release'\|'stage'` | — |
| `StageFlow` | `stages: Stage[]`, `activeId` | `select`（滚动定位日志） |
| `LogViewer` | `buildId`, `initialLines`, `live: boolean` | `copy-line`, `jump-artifact` |
| `ArtifactList` | `artifacts: Artifact[]`, `canDownload` | `preview`, `download` |
| `ReportViewer` | `report: BuildReport` | `open-raw` |
| `TriggerDrawer` | `open`, `projectId`, `defaults`, `prefill` | `submitted(buildId)` |
| `GateList` | `gates: ReleaseGate[]` | `explain(code)` |
| `DistTagTable` | `tags`, `history` | `rollback(tag)` |
| `AiPanel` | `kind`, `resourceId`, `autoLoad: boolean` | `apply(action)`, `feedback(up\|down)` |
| `AiDiffCard` | `field`, `before`, `after`, `risk` | `apply`, `discard` |
| `CommandBox` | `command`, `hint` | `copy` |

## 6. 状态管理

| Store | 持有 | 说明 |
| --- | --- | --- |
| `session` | 当前用户、权限点集合、`has(permission)` | 登录后一次性拉取 `/auth/me` |
| `project` | 当前项目、设置、同步水位、绑定 Job | 路由切换时按 `projectId` 加载 |
| `builds` | 列表筛选条件、游标、缓存页 | 筛选条件与 URL query 双向绑定 |
| `notifications` | 未读通知数、列表 | 每 60s 轮询或由 SSE 推送 |
| `ui` | Toast 队列、抽屉/弹窗开合、全局 loading、降级横幅 | — |

约定：**服务端数据不进 Pinia 做长期缓存**，页面级组件自己持有列表数据（避免缓存一致性问题）；Pinia 只存"跨页面共享的状态"。

## 7. 与后端的契约同步

```text
后端 zod schema
   ↓ zod-to-openapi
OpenAPI 3.1 (docs/openapi.json，随代码提交)
   ↓ openapi-typescript
前端 src/api/types.gen.ts
```

- 生成脚本 `pnpm gen:api`，CI 中校验生成结果与提交一致（防止手改类型）。
- 前端 API 模块只做"调用 + 类型断言"，业务判断（权限、状态机）不做在请求层。
- 错误统一在 `client.ts` 转成 `ApiError { code, message, details, requestId }`，页面按 `code` 分支处理（如 `E_GATE_FAILED` 直接渲染门禁清单）。

## 8. 无障碍与响应式

- 键盘：抽屉/弹窗 Esc 关闭、Tab 焦点圈（`focus-visible` 已有令牌）、日志视图支持 `↑/↓` 滚动与 `Ctrl+F` 触发搜索框。
- 对比度：语义色组合（`--danger` on `--danger-bg`）已验证 ≥ 4.5:1。
- 响应式：≥1440px 三栏；1024–1440px 双栏；<1024px 侧栏折叠为抽屉、表格横向滚动；日志视图最小宽度 720px。
- 打印/导出：发布详情支持"打印为 PDF"（可选 P2）。

## 9. 与原型的有意差异

| 原型 | 实现 | 原因 |
| --- | --- | --- |
| 顶栏"视角"切换（演示用） | 去掉，改为真实角色驱动 | 生产环境不允许用户自选权限 |
| mock 数据（假构建、假用户、假 Agent） | 全部替换为真实采集数据 | — |
| 原型写 `xlite-perf-optimizer` 已禁用 | 以 `ci/agents.json` 为准（当前 `enabled: true`） | 原型 mock 落后于仓库 |
| 单 Job（`witty-agent-package-ci`） | 支持绑定多个 Job（主 + smoke），并在 UI 标明来源 Job | 真实环境存在 `witty-agents-builder` 与 `...-smoke-arm` 两个 Job |
| 日志里手写的 `──── stage X ────` 分隔 | 优先用 `wfapi` 阶段数据，日志分隔仅作降级 | 真实 Jenkins 日志无该格式 |
| 无分页的短列表 | 全部服务端游标分页 | 真实构建记录会持续增长 |
| Agent 卡片启停开关（直接翻转 enabled）、权限矩阵"MR 需审批"字样 | 去掉启停开关，只读展示 `enabled` 状态 | 平台不回写仓库（ADR-03）；开关与 MR 字样为旧版遗留，原型后续清理 |
