# NL2SQL 测试数据包（demo-es）

老 demo 场景：约 1000 人 / 3000 购票 / 981 标签，配套 **100 条** NL 测试问句。

---

## 目录

```
test-data/
├── README.md
├── data/                          ← 业务 JSON，自行导入 ES
│   ├── resident_population.json   （1000 行 → 索引 resident_population）
│   ├── ticket_sales.json          （3000 行 → 索引 ticket_sales）
│   └── tag_person.json            （981 行 → 索引 tag_person）
├── queries/
│   └── test_queries.json          ← 100 条测试问句
├── rules_bundle/
│   └── demo-es.json               ← 完整规则 66 条（schema + ES 方言 + domain）
├── configs/
│   └── datasource-demo-es.yaml.example
└── scripts/
    └── sync_rules_to_rag.py       ← 规则写入 rag-core
```

---

## 一、业务数据 → Elasticsearch

| JSON 文件 | ES 索引名 | 行数 |
|-----------|-----------|------|
| `data/resident_population.json` | `resident_population` | 1000 |
| `data/ticket_sales.json` | `ticket_sales` | 3000 |
| `data/tag_person.json` | `tag_person` | 981 |

关联键：

- `ticket_sales.id_no` = `resident_population.idcardno`
- `tag_person.idcardno` = `resident_population.idcardno`

每个文件是 **JSON 数组**（一行一条文档）。索引名必须与上表一致。

字符串字段建议 ES mapping 用 `keyword`。核心字段：

| 索引 | 常用字段 |
|------|----------|
| resident_population | idcardno, xm, xb, csrq, mz, zz |
| ticket_sales | id_no, train_date, board_train_code, from_station_name, to_station_name |
| tag_person | idcardno, tag_name |

导入方式自定（bulk / OpenCode 等）。验收：三索引 `_count` 分别为 **1000 / 3000 / 981**。

```bash
curl 'http://127.0.0.1:9200/_cat/indices?v'
curl 'http://127.0.0.1:9200/resident_population/_count'
```

---

## 二、规则 → rag-core

`rules_bundle/demo-es.json` 已包含全部规则（66 条）：

| scope | 条数 | 说明 |
|-------|------|------|
| schema | 34 | 三索引字段 ddl + mapping |
| dialect | 5 | Elasticsearch SQL/DSL 方言 |
| domain | 27 | 业务常识、标签/省份别名 |

```bash
cd test-data
pip install httpx

export RAG_BASE_URL=http://127.0.0.1:19988
export RAG_ACCESS_KEY=nl2sql-local-key

python3 scripts/sync_rules_to_rag.py
```

成功后记下 `kb_id`，写入 NL2SQL `configs/datasources.yaml` 中 `demo-es.rules_kb_id`（参考 `configs/datasource-demo-es.yaml.example`）。

---

## 三、测试问句

`queries/test_queries.json`：100 条，基准日期 **2026-07-20**。

- 功能测试：Web「智能问答」或 `POST /api/query`
- 一致性测试：`POST /api/consistency/run`（推荐 id：1, 21, 24, 74, 82, 83, 87）

NL2SQL 数据源选 **`demo-es`**，不要用 `local-es`。

---

## 四、检查清单

- [ ] ES 三索引已导入，文档数 1000 / 3000 / 981
- [ ] `sync_rules_to_rag.py` 成功，`kb_id` 已配置
- [ ] Web `/api/health` 正常，LLM 可用
- [ ] 抽样问句有合理 SQL 与结果

---

## 五、交付清单

| 交付物 | 路径 |
|--------|------|
| 业务数据 | `data/*.json` |
| 测试问句 | `queries/test_queries.json` |
| rag 规则包 | `rules_bundle/demo-es.json` |
| 规则入库脚本 | `scripts/sync_rules_to_rag.py` |
| 数据源配置示例 | `configs/datasource-demo-es.yaml.example` |
| 本说明 | `README.md` |
