# witty-agent-factory 设计与实施方案

> 流水线运维平台 · 面向 witty-agents 生态的 Agent 构建 / 发布 / 审计中台

| 项 | 值 |
| --- | --- |
| 文档版本 | v1.0 |
| 基线日期 | 2026-09-17 |
| 代码落位 | `witty-agents/ci/factory/`（本仓库，约定） |
| 文档归档位置 | `ci/factory/docs/design/`（本目录，随代码演进，文档与实现同步更新） |
| 前端原型基线 | `./prototype/`（HTML 静态原型 v0.3，9 个页面，已随本文档一并归档） |
| 流水线基线 | 仓库根 `Jenkinsfile`（11 阶段 / 14 参数）、`ci/agents.json`（4 个 Agent）、`ci/scripts/*` |
| 运行环境基线 | ARM64 节点 Jenkins 2.555.3 + Docker Agent，Job `witty-agents-builder`、`witty-agents-online-publish-smoke-arm` |

---

## 1. 三条不可动摇的设计前提

在动手前必须先接受这三条，否则平台会退化成"第二个 Jenkins"：

1. **Jenkins 仍是唯一流水线引擎**。`Jenkinsfile` 定义阶段、门禁与发布顺序；平台不解析也不执行 Jenkinsfile，只读取它的执行结果（阶段、日志、报告、产物）。任何"平台自己拼构建步骤"的设计都是错的。
2. **仓库是唯一事实源**。Agent 注册（`ci/agents.json`）、Agent 能力（`<agent>/ci/agent.json`）、包版本（`<agent>/package.json`）、构建计划（`ci-artifacts/build-plan.json`）全部以仓库为准。平台只做只读同步，不回写仓库（Agent 启停在仓库改 `ci/agents.json`）。
3. **平台不持有 npm Token**。npm 发布仍由 Jenkins 凭据 `npm-token` 完成。平台发起发布 = 触发一次 `PUBLISH=true` 的构建并跟踪结果，而不是自己去 `npm publish`。dist-tag 回滚同理走受控 Job 或人工执行。

---

## 2. 文档导航

| 文档 | 内容 | 主要读者 |
| --- | --- | --- |
| [01-产品与用例.md](01-product-and-use-cases.md) | 平台定位、角色与权限矩阵、用例清单、页面映射、非功能需求 | 产品 / 全员 |
| [02-总体架构.md](02-architecture.md) | 架构图、分层、技术选型、上游系统交互、部署拓扑、安全边界 | 架构 / 后端 / 运维 |
| [03-后端设计.md](03-backend-design.md) | 模块划分、Jenkins 适配层、采集器、发布服务、RBAC、审计、AI 能力点 | 后端 |
| [04-数据模型.md](04-data-model.md) | 表结构 DDL、枚举与状态机、索引、保留策略、上游 JSON 映射 | 后端 |
| [05-API契约.md](05-api-contract.md) | REST 端点总表、关键接口请求响应示例、SSE 事件、错误码 | 前后端 |
| [06-前端设计.md](06-frontend-design.md) | 技术栈、设计令牌、路由与页面规格、组件清单、交互实现要点 | 前端 |
| [07-流水线集成规范.md](07-pipeline-integration.md) | 11 阶段 / 14 参数、注册表与报告 JSON、发布门禁 REL-01、采集清单 | 后端 / CI 维护者 |
| [08-部署运维与工程结构.md](08-deployment-and-repo-layout.md) | `ci/factory` 目录树、compose、环境变量、备份升级、可观测性 | 运维 / 全员 |
| [09-实施计划与验收.md](09-plan-and-acceptance.md) | 里程碑 M0–M4、WBS、测试策略、验收标准、风险 | 全员 |

**推荐阅读顺序**：01 → 02 → 07 → 03/04/05 → 06 → 08 → 09。
只想快速了解平台做什么，读 01 就够；只想动手写代码，先读 02 + 07，再按 03/04/05/06 分工。

---

## 3. 平台一句话说明

把当前只能通过 Jenkins 控制台 + 服务器磁盘 + npm 网页三处拼凑的流水线事实，收敛成一个有权限、有审计、有解释能力的运维平台：

```text
Jenkins Job ／ 仓库 ／ npm registry
        │（只读采集 + 受控写入）
        ▼
witty-agent-factory
  ├─ 看：Agent 健康、构建历史、11 阶段、日志、报告、产物、发布链路
  ├─ 做：触发构建（14 参数）、重跑、取消、发布确认、dist-tag 回滚
  ├─ 管：4 级 RBAC、成员与用户、项目配置（平台侧配置，不回写仓库）
  └─ 审：全量操作审计，AI 操作标记「用户 × Agent」
```

---

## 4. 与原型、与既有 CI 的关系

- **与原型**：原型的 9 个页面、设计令牌、交互细节（14 参数抽屉、日志高亮与错误导航、门禁清单、AI 面板）全部保留。原型源码已归档在 [`./prototype/`](prototype/index.html)，用浏览器直接打开 `prototype/index.html` 即为导览页，无需构建。原型中的 mock 数据在实现时替换为真实采集数据，其中若干处 mock 事实已过期（例如原型写 `xlite-perf-optimizer` 已禁用，实际 `ci/agents.json` 中它为 `enabled: true`），实现时一律以仓库为准，见 [07](07-pipeline-integration.md) 第 11 节。
- **与 `ci/jenkins`**：`ci/jenkins/` 负责"如何起一台 Jenkins"，`ci/factory/` 负责"如何在 Jenkins 之上做运维"。二者共存，互不替代；factory 使用一个只读或最小权限的 Jenkins 账号。

---

## 5. 术语表

| 术语 | 含义 |
| --- | --- |
| Agent | 仓库内一个可打包的独立能力单元（如 `shennong-crash`），对应 `<dir>/ci/agent.json` |
| 变体 Variant | 包内容变体：`online`（不含 Python wheels）/ `offline`（含 wheels，绑定架构） |
| 构建 Build | 一次 Jenkins Pipeline 执行，对应 `Jenkinsfile` 的 11 个阶段 |
| 阶段 Stage | Jenkinsfile 中的 stage，如 `Artifact Gates` |
| 发布 Release | 一次把 online 包推到 npm 的动作（主 Job `PUBLISH=true` 或 smoke Job） |
| dist-tag | npm 标签，平台内固定策略：`x86-test` / `arm-test` 用于测试发布，`latest` 受保护 |
| REL-01 | 发布五项门禁的代号，见 [07](07-pipeline-integration.md) 第 5 节 |
| 事实源 | 仓库 / Jenkins / npm registry 三处上游，平台内的 `agents`、`builds`、`releases` 都是它们的投影 |
