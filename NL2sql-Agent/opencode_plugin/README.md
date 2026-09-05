# OpenCode 接入

1. 本机 Web 已启动：`./scripts/start_web.sh`（`http://127.0.0.1:8199`）。
2. 将本目录 `skills/` 链到 OpenCode skills，或复制过去。
3. `role-prompt.md` 可作为 nl2sql Agent 系统提示；也可用 `./scripts/register_opencode.sh`。

Agent **只 HTTP 调** NL2SQL API，不自己连 ES/OG/HBase。  
LLM 用 NL2SQL 的 `.env` / 设置页，**不会**改用 OpenCode 会话里的模型。

切源、冷启动规则、一致性：`POST /api/datasources/test`、`/api/rules/init/*`、`/api/consistency/run`。  
契约见 `skills/nl2sql/references/api.md`，测试步骤见仓库 `docs/TEST.md`。
