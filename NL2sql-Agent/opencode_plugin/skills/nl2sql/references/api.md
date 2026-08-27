# NL2SQL Web API（摘要）

默认端口：**8199**

## 健康与配置

- `GET /api/health`
- `GET|POST /api/settings`
- `GET /api/datasources`
- `POST /api/datasources/test` body: `{ "datasource_id": "local-es" }`
- `GET /api/schema/{datasource_id}`

## 查询

- `POST /api/query`（非流式，OpenCode/脚本优先）

```json
{
  "query": "...",
  "datasource_id": "local-es",
  "execute_query": null,
  "mode": "auto",
  "use_llm": true,
  "skip_clarify": false,
  "interactive_clarify": true,
  "clarify_session_id": null,
  "clarify_message": null
}
```

- `interactive_clarify=true`：多轮追问（最多 3 轮），未完成时返回 `need_clarify`
- `interactive_clarify=false`：静默单次改写 query，不向用户提问
- `skip_clarify=true`：完全跳过澄清（一致性测试等）

若需澄清且未完成，返回 `{ "need_clarify": true, "clarify_session": {...} }`。

- `POST /api/query/stream`（步骤级 SSE）  
  事件：`status` / `need_clarify` / `resolved_query` / `step` / `rules` / `sql` / `retry` / `result` / `error` / `done`

## 澄清

- `POST /api/clarify/start` `{ "query", "max_rounds": 3 }`
- `POST /api/clarify/reply` `{ "session_id", "message" }`
- `GET /api/clarify/{session_id}`

## 规则（F1）

- `GET /api/rules?database_id=local-es`
- `POST /api/rules` 单条 upsert
- `POST /api/rules/search` `{ database_id, query, rule_type?, top_k }`
- `POST /api/rules/bootstrap`
- `POST /api/rules/generate_from_nl` `{ database_id, user_text, include_schema? }`  
  → 仅 domain/dialect/别名，不做海量字段 mapping
- `POST /api/rules/import` `{ database_id, rules, sync_rag? }`  
  → 本地 + 增量 upsert 现有 rag KB（无 KB 才创建）

## 一致性

- `POST /api/consistency/run` `{ query, datasource_id, repeats: 3, mode }`  
  → 跳过澄清；报错轮次不计；比结果集 Jaccard
