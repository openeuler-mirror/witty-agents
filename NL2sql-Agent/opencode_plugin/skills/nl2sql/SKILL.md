---
name: nl2sql
description: >
  将自然语言转为查询（ES IR / OpenGauss SQL / HBase scan）并只读执行。
  通过本机 NL2SQL Web API（默认 http://127.0.0.1:8199）完成澄清、召回规则、生成与执行。
  也可在规则中心用自然语言生成 F1 规则并增量导入 rag-core。
  Triggers: 自然语言查库、NL2SQL、查人员、购票、进站、生成 ES 查询、规则导入。
---

# NL2SQL Skill

## 硬规则

- 默认只读，禁止对业务库写删。
- 调用本机 API，不要另写一套查询逻辑。
- 规则存 rag-core（默认 http://127.0.0.1:19988）；业务库按数据源切换：ES / OpenGauss / HBase。
- Web 与 OpenCode 行为一致：默认先澄清（最多 3 轮），澄清完成后用 `resolved_query` 自动跑查询。
- 可关交互澄清：`interactive_clarify=false` 时模型静默改写问句，不再追问。

## 推荐工作流

1. `GET /api/health?datasource_id=<当前源>` 确认当前库 + RAG；切源后用 `POST /api/datasources/test` 只测这一个。
2. 用户问题不清晰时：`POST /api/clarify/start` → 多轮 `POST /api/clarify/reply`（`max_rounds` 默认 3）。
3. 查询：`POST /api/query`（非流式）或 `POST /api/query/stream`（步骤级 SSE）。
   - 可把澄清会话带入：`clarify_session_id` + `clarify_message`。
   - 一致性/回归可设 `skip_clarify: true`。
4. 补规则（F1）：`POST /api/rules/generate_from_nl` → 人工改 → `POST /api/rules/import`（增量 upsert 到现有 KB）。
5. **冷启动规则（用户库有数据、rag 为空）**：
   - 优先 CLI（不必开页面）：`python3 scripts/init_rules_from_db.py --database-id <id>` 得到 JSON 规则包 → 给用户看/改 → `--commit --from-file <json>`。
   - 或 HTTP：`POST /api/rules/init/preview` → 把返回的 `rules` / `bundle_path` 给用户确认 → `POST /api/rules/init/commit`。
   - 规则 LLM 仍走 NL2SQL 配置的模型，不用 OpenCode 会话模型。
6. 一致性：`POST /api/consistency/run`（同问句×3，比结果集）。

```bash
curl -s http://127.0.0.1:8199/api/health
curl -s -X POST http://127.0.0.1:8199/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询人员索引中性别为男的记录","datasource_id":"local-es","mode":"auto","use_llm":true}'
```

完整契约见 `references/api.md`。
