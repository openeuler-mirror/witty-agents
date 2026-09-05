# NL2SQL 规则 fixtures（同步进 rag-core，不要写进 Python 问句板子）

## 目录

| 路径 | 用途 |
|------|------|
| `dialects/<engine>.json` | 引擎方言硬约束（`scope=dialect`），查询时**固定召回** |
| `datasources/<database_id>/domain.json` | 该数据源业务常识（`scope=domain`），按问句语义召回 |
| `datasources/<database_id>/station_aliases.json` | 城市/标签别名（多条 mapping，类似老 demo 的 mappings） |

## 字段

每条规则建议包含：

- `rule_type`: 通常 `experience`
- `scope`: `dialect` | `domain`
- `dialect`: `elasticsearch` | `opengauss` | `hbase` | `shared`
- `description`: 可泛化的约束/常识（**不要**写「问句 X → SQL Y」）

Schema（ddl/mapping）可由 `bootstrap.py` 从 FIELD-GUIDE 生成，或由 `scripts/init_rules_from_db.py` **从真实库**生成规则包后再 commit。

冷启动（推荐）：

```bash
PYTHONPATH=. python3 scripts/init_rules_from_db.py --database-id local-es
PYTHONPATH=. python3 scripts/init_rules_from_db.py --commit --from-file data/rules/init_bundles/init_local-es_xxx.json
```

## 同步

```bash
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es
```

会写入 `datasources.yaml` 中该源的 `rules_kb_id`。换引擎时使用对应 `--database-id` 与 `dialects/{elasticsearch,opengauss,hbase}.json`。
