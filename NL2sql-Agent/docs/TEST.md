# NL2SQL 测试指南

面向功能/一致性验收。假设已按 [DEPLOY.md](./DEPLOY.md) 完成部署，ES 与 rag-core 可用。  
**本仓库不含业务明细数据**，请使用你们环境中的索引（字段需与规则/FIELD-GUIDE 对齐）。

## 1. 测试前准备

```bash
cd NL2sql-Agent
source .venv/bin/activate   # 若使用 venv
curl -s http://127.0.0.1:8199/api/health
```

在 Web「设置」确认：LLM、rag `base_url` / `access_key`。  
各数据源的 ES 地址优先写在 `configs/datasources.yaml`（运行时设置不会覆盖已配置的 hosts）。

## 2. 导入规则（必做）

规则原料在 `fixtures/rules/`（方言 / 领域 / 别名示例），Schema 说明在 `fixtures/field_guide/`。  
运行时权威源是 **rag-core JSON KB**：

```bash
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es
# 已有 KB 时：
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es --reuse-kb
```

成功后会回写 `local-es.rules_kb_id`。也可用 Web「规则中心」NL 生成或 JSON 导入增量规则。

标签别名、城市映射等**业务口径请用规则表达**（domain/mapping），不要改引擎代码做特例。

## 3. 导入业务数据（自备）

将业务数据导入 Elasticsearch，索引名/字段与规则一致。本包**不提供** dump。

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices?v'
```

Schema 不同时：拉取 Schema → 用规则中心补 domain/mapping → 再问答。

新增数据源：在 `datasources.yaml` 增加条目（hosts、`rules_kb_id`/`rules_kb_name`），刷新页面后下拉框会自动出现（读 `/api/datasources`）。

## 4. 功能测试（智能问答）

1. 打开 `http://127.0.0.1:8199` →「智能问答」  
2. 选择数据源；澄清开/关按需  
3. 观察步骤：召回规则 → **ES 为 IR 多步计划**（或其它引擎的 SQL）→ 结果  

`max_size` 会限制单次查询返回行数，也会影响半连接中间键数量；跨表场景建议按数据规模调大该值。

## 5. 一致性测试

```bash
curl -s -X POST http://127.0.0.1:8199/api/consistency/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"你的清晰问句","datasource_id":"local-es","repeats":3,"mode":"auto"}'
```

- 跳过澄清，同一问句跑 N 次  
- 报错轮次不计入；真 0 行可互相比  
- 指标：`result_consistency`（结果集 Jaccard）  

## 6. 验收清单

- [ ] `/api/health`：ES、rag 可用  
- [ ] 规则已 sync，步骤中能看到 dialect/domain 召回  
- [ ] ES 问句展示为半连接执行计划，结果合理  
- [ ] 一致性：关键问句多次稳定或可解释  
- [ ] 新增数据源只需改 yaml，无需改前端  

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 召回为空 | 检查 `rules_kb_id`、rag access_key、是否已 sync |
| 标签/别名查空 | 核对 domain 规则中的标准值是否与库内原文一致 |
| 字段整列为空 | 勿用错索引字段名；补 mapping；优先 `SELECT *` / `select=["*"]` |
| ES 连错实例 | 看该数据源 yaml 的 hosts；设置页全局 hosts 不会覆盖已配置项 |
| OpenCode 调不通 | 确认 Web 在 8199 |

API 细节见 `opencode_plugin/skills/nl2sql/references/api.md`。
