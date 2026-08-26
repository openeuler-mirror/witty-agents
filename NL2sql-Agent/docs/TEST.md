# NL2SQL 测试指南

面向功能/一致性测试。假设已按 [DEPLOY.md](./DEPLOY.md) 完成部署，ES 与 rag-core 可用。

## 1. 测试前准备

```bash
cd NL2sql-Agent
source .venv/bin/activate   # 若使用 venv
curl -s http://127.0.0.1:8199/api/health
```

在 Web「设置」确认：LLM、ES hosts、rag `base_url` / `access_key`。

## 2. 导入规则（必做）

规则原料在 `fixtures/rules/`（方言 / 领域 / 站点别名），Schema 说明在 `fixtures/field_guide/`。  
运行时权威源是 **rag-core JSON KB**，需同步一次：

```bash
# 从 FIELD-GUIDE + fixtures/rules 生成本地缓存，并写入 rag-core
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es

# 若 KB 已存在、只想复用并覆盖同步：
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es --reuse-kb
```

成功后 `configs/datasources.yaml` 中 `local-es.rules_kb_id` 会被回写（或写在运行时配置里）。

### 可选：Web / OpenCode 增量导入

- Web「规则中心」：自然语言生成 → 勾选编辑 → 导入；或上传 JSON  
- API：`POST /api/rules/generate_from_nl`、`POST /api/rules/import`  
- OpenCode：按 `opencode_plugin/skills/nl2sql/SKILL.md` 调用上述 API  

**说明**：NL 生成默认只产 domain/dialect/别名（F1），全量字段 mapping 仍建议走 FIELD-GUIDE bootstrap。

## 3. 导入业务数据（测试方自备）

本仓库**不含**业务明细 dump。请将测试数据导入 Elasticsearch，索引与字段需与规则/FIELD-GUIDE 对齐（或自行改规则）。

示例（用 ES bulk / 自有工具即可）：

```bash
# 确认索引存在
curl -s http://127.0.0.1:9200/_cat/indices?v

# 按你们现有流程导入；索引名需与规则中的表名一致，例如：
# person_info_es / ticket_record_es_2026 / checkin_record_es_2026 /
# resign_record_es_2026 / return_record_es_2026 / crew_record_es_2026 / zdry_info_es
```

若测试库 schema 不同：

1. 用 Web「拉取 Schema」核对字段  
2. 用规则中心 NL 生成或 JSON 导入新的 domain/mapping  
3. 再跑问答与一致性  

## 4. 功能测试（智能问答）

1. 打开 `http://127.0.0.1:8199` →「智能问答」  
2. 「头脑风暴澄清」：  
   - **开**：多轮追问后再查  
   - **关**：模型静默改写问句后直接查  
3. 输入自然语言，观察步骤（召回规则 → SQL → 结果）  
4. 建议默认返回全字段（`SELECT *`）；列名以 Schema/规则为准  

OpenCode：先保证 `8199` 已启动，再让 Agent 按 Skill 调 `/api/query` 或 `/api/query/stream`。

## 5. 一致性测试（重点）

Web「一致性测试」或：

```bash
curl -s -X POST http://127.0.0.1:8199/api/consistency/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"你的清晰问句","datasource_id":"local-es","repeats":3,"mode":"auto"}'
```

约定：

- **跳过澄清**，同一问句跑 N 次（默认 3）  
- **报错轮次不计入**一致性  
- **真 0 行**可互相比（都空算一致）  
- 指标：`result_consistency`（结果集 Jaccard）  

建议准备一批固定问句，记录每次 `result_consistency`、有效轮次、生成 SQL。

## 6. 建议验收清单

- [ ] `/api/health`：ES、rag 按环境可用  
- [ ] 规则已 sync，问答步骤中能看到 dialect/domain 召回  
- [ ] 抽样问句有合理 SQL/结果（字段非错名空列）  
- [ ] 一致性：关键问句多次结果稳定或可解释  
- [ ] OpenCode（若测）：能完成查询与规则导入工作流  

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 召回为空 | 检查 `rules_kb_id`、rag access_key、是否已 sync |
| SQL 字段空列 | 勿用错索引字段名；优先 `SELECT *`；补 domain/mapping 规则 |
| ES 连接失败 | 查 hosts、Docker 是否启动、防火墙 |
| rag 代理失败 | 安装 `ncat`，或把 `rag_core.yaml` 的 `base_url` 改成实际上游 |
| OpenCode 调不通 | 确认本机 Web 在 8199 监听 |

更完整的 API 见 `opencode_plugin/skills/nl2sql/references/api.md`。
