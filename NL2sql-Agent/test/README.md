# NL2SQL 测试资产包

与主仓库分离：**不含业务 JSON 大文件**，提供造数脚本 + demo-es 规则/问句，用于功能与一致性验收。

```
test/
├── README.md                 ← 本说明
├── data-synth/               ← 五表造数、校验、导入 ES（合并为规则三索引）
└── test-data/                ← demo-es 规则包、100 条问句、配置示例（无 data/）
    ├── rules_bundle/
    ├── queries/
    ├── configs/
    └── scripts/
```

主程序仍在上级目录（`NL2SQL-Agent-publish/`）；本目录只放测试侧工具与配置原料。

## 推荐流程

```bash
# 1. 造数（试跑 10 万/表；全量改 rows_per_table）
cd test/data-synth
pip install pyyaml
python3 generate.py --rows-per-table 100000
python3 validate.py

# 2. 导入 ES（只导规则三表）
python3 import_es.py --indices resident_population,ticket_sales,tag_person

# 3. 规则入库 rag-core
cd ../test-data
pip install httpx
export RAG_BASE_URL=http://127.0.0.1:19988
export RAG_ACCESS_KEY=nl2sql-local-key
python3 scripts/sync_rules_to_rag.py

# 4. 将返回的 kb_id 写入上级 configs/datasources.yaml（demo-es 条目，见 configs 示例）

# 5. 用 queries/test_queries.json 做 Web 或一致性测试
```

## 与主仓库 scripts 的区别

| 路径 | 用途 |
|------|------|
| `../scripts/sync_rules_to_rag.py` | 从 `fixtures/rules/` bootstrap → **local-es** KB |
| `test-data/scripts/sync_rules_to_rag.py` | 整包写入 **demo-es**（`rules_bundle/demo-es.json`） |

两套脚本并存：交付默认 `local-es`；完整 demo 场景用 `test/test-data`。

## 说明

- 造数生成五张基表 JSON；导入时合并为 `resident_population` / `ticket_sales` / `tag_person` 三个 ES 索引，与 `rules_bundle/demo-es.json` 一致。
- 若仍使用旧版静态数据，可自行准备 `test-data/data/*.json`（本包 intentionally 不包含）。
