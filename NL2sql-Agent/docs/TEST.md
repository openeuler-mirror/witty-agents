# NL2SQL 测试指南

给**功能测试 / 一致性测试**同学用。假设已按 [DEPLOY.md](./DEPLOY.md) 起好 Web（`http://127.0.0.1:8199`）和 rag-core。  
本仓库**不含业务明细数据**；问句与索引/表结构需与规则对齐。

一次只测**当前选中的数据源**。顶栏徽章是 `数据源id（引擎）✓ · RAG✓`，不会同时扫 ES、OpenGauss、HBase。

---

## 0. 你要测哪条链路

在 `configs/datasources.yaml` 里改连接（**不要把密码提交进 git**），然后刷新页面，下拉框选对应 id：

| 数据源 id | 引擎 | 默认连接 | 生成物 |
|-----------|------|----------|--------|
| `local-es` | Elasticsearch | `http://127.0.0.1:9200` | IR 半连接 |
| `local-opengauss` | OpenGauss | `127.0.0.1:5434`，用户 `gaussdb` | SQL |
| `local-hbase` | 原生 HBase REST | `http://127.0.0.1:16080` | JSON scan |
| `mock` | 演示 | 无真实库 | 固定样例行 |

本机没有 OG / HBase 时，可用仓库脚本（可选）：

```bash
./scripts/start_opengauss.sh   # 若 5434 已占用则跳过；新容器密码见脚本提示，填进 yaml
./scripts/start_hbase.sh       # 下载官方二进制到 .opt/，REST → 16080（需 Java 11+）
```

改完 yaml 后**重启 Web 或等 reload**，再点「测试当前数据源」。

---

## 1. 测试前准备

```bash
cd NL2sql-Agent
source .venv/bin/activate   # 若使用 venv
curl -s 'http://127.0.0.1:8199/api/health?datasource_id=local-es'
```

Web「设置」：

1. 选**当前数据源**（与问答页同一个下拉）  
2. 填 LLM、rag `base_url` / `access_key`  
3. 只会出现**当前引擎**的连接表单；点「测试当前数据源」

yaml 里已写的 hosts/port **不会**被设置页覆盖。换 ES 集群、换 OG 库，优先改 yaml。

---

## 2. 规则从哪来（必做其一）

运行时权威源是 **rag-core JSON KB**。每个数据源有自己的 `rules_kb_id`，**切源后必须对该 id 做过入库**，否则问答召回为空。

### 2.1 已有 fixtures（ES 示例域）

```bash
PYTHONPATH=. python3 scripts/sync_rules_to_rag.py --database-id local-es
# 已有 KB 时加 --reuse-kb
```

OpenGauss / HBase 目前 fixtures 主要是方言（`fixtures/rules/dialects/`），业务 mapping 请用冷启动或规则中心补。

### 2.2 冷启动（现场有库、rag 为空）

**不要**把未确认的规则直接写进已有精修 KB。默认会新建 KB。

```bash
# 1）抽样 + 生成 JSON（可不开浏览器；会调 LLM 写 domain，可加 --no-llm）
PYTHONPATH=. python3 scripts/init_rules_from_db.py --database-id local-es
#    OpenGauss / HBase 把 id 换成 local-opengauss / local-hbase

# 2）打开生成的 data/rules/init_bundles/init_<id>_*.json 看一遍

# 3）确认后再入库
PYTHONPATH=. python3 scripts/init_rules_from_db.py --commit --from-file data/rules/init_bundles/init_local-es_xxx.json
```

Web：规则中心 → 选同一数据源 →「从数据源生成规则包」→ 勾选/编辑 →「确认入库规则包」。

也可 NL 生成 domain/别名后「导入勾选到本地+RAG」（增量，不覆盖整库）。

---

## 3. 导入业务数据（自备）

- **ES**：索引名/字段与规则一致。本包不提供 dump。可用上级 `test/data-synth` 造数后只导规则三索引：`resident_population`、`ticket_sales`、`tag_person`（见 `test/README.md`）。  
- **OpenGauss**：自行建表导入；规则认的是 `information_schema` 里的表。  
- **HBase**：原生表（namespace:table + column family），走 REST；不是 Phoenix SQL。  

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices?v'
```

新增数据源：在 `datasources.yaml` 加一条（`type`、连接、`rules_kb_name`），刷新页面即可，不必改前端。

---

## 4. 功能测试（智能问答）

1. 打开 `http://127.0.0.1:8199` →「智能问答」  
2. **先选数据源**，点「测试当前数据源」，确认顶栏变成该源的 ✓  
3. 澄清：默认开（多轮追问）；可关掉让模型自行理解  
4. 输入问句发送，观察步骤：召回规则 → 生成查询 → 执行  
   - ES：应看到 **IR**（`from` / `where` / `semi_joins`），不是一条跨索引 SQL  
   - OpenGauss：应看到 **SELECT**  
   - HBase：应看到 **scan JSON**（`table` / `filters` / `limit`）  
5. `max_size` 限制返回行数；ES 半连接中间键数量也会受它影响，跨表场景可把 yaml 里该值调大  

手写执行：问答页下方「直接执行查询」可跳过 LLM（ES 用 SQL/DSL JSON，OG 用 SELECT，HBase 用 scan JSON）。

---

## 5. 一致性测试（重点）

含义：**同一条已经清晰的问句**，跳过澄清，连跑 N 次（默认 3），只比**结果集**是否稳定。  
报错的那一轮不计入；真的 0 行可以互相比。指标：`result_consistency`（结果集 Jaccard，1.0 表示每次行集合一样）。

### 5.1 Web

1. 打开「一致性测试」页  
2. 数据源选**与问答相同的当前库**  
3. 模式一般用 `auto`  
4. 贴一条**完整清晰**的问句（不要含糊到需要澄清）  
5. 点「开始测试」，看有效轮次、每次行数、生成的查询是否漂移  

### 5.2 HTTP（便于批量）

```bash
curl -s -X POST http://127.0.0.1:8199/api/consistency/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"40-60岁 去过成都的重点关注人员","datasource_id":"local-es","repeats":3,"mode":"auto"}'
```

换源只改 `datasource_id`：`local-opengauss` / `local-hbase`。

`test/test-data/queries/test_queries.json` 里是 100 条 demo 问句（按 ES 三索引写的）。抽几条在 Web 跑通后，再批量：

```bash
python3 - <<'PY'
import json, urllib.request

src = json.load(open("test/test-data/queries/test_queries.json", encoding="utf-8"))
ds = "local-es"  # 改成当前在测的源
for item in src["queries"][:5]:  # 先跑 5 条；全量去掉切片
    body = json.dumps({
        "query": item["query"],
        "datasource_id": ds,
        "repeats": 3,
        "mode": "auto",
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8199/api/consistency/run",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    out = json.loads(urllib.request.urlopen(req, timeout=180).read())
    print(item["id"], "jaccard=", out.get("result_consistency"),
          "valid=", out.get("valid_runs"), "invalid=", out.get("invalid_runs"))
PY
```

建议先在 Web 上跑通 3～5 条，再脚本化。LLM 有随机性，生成的 IR/SQL 文本可能不同，**验收看结果集 Jaccard**，不要强行要求语句逐字相同。

### 5.3 怎么判

| 结果 | 含义 |
|------|------|
| `result_consistency` 接近 1，有效轮次 = repeats | 稳定，可过 |
| 有效轮次少、步骤报错 | 先看规则 KB、字段名、库是否连对，别先调一致性次数 |
| 有时有行有时 0 行 | 查召回是否漂（规则不足）或 LIMIT/半连接键被截断 |

---

## 6. 建议验收顺序

1. 健康：选中源「测试当前数据源」成功；RAG✓  
2. 规则：对该 `database_id` 已 sync 或冷启动 commit；问答步骤里能看到 dialect/domain  
3. 问答：ES 至少 3～5 条跨表问句有合理行；切到 OG/HBase 时只要求**能连上并生成对应方言**（无业务数据则允许 0 行）  
4. 一致性：关键问句 ×3，Jaccard 可解释  
5. 切源：问答下拉换成另一条，顶栏与设置页只跟当前源走，不会把三种库一起测  

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 召回为空 | 检查当前源的 `rules_kb_id`、rag access_key、是否已对该 id sync/commit |
| 顶栏一直 ✗ | 只说明**当前**这条连不上；看 yaml 端口/密码；OG 填 `password`，HBase 看 `16080/version` |
| 设置页没有 OG 表单 | 先把下拉切到 `local-opengauss` |
| 标签/别名查空 | domain 规则里的标准值要与库内原文一致 |
| ES 连错实例 | 看该源 yaml 的 `hosts`；设置页不会覆盖已写项 |
| 切到 OG 仍想跑 IR | IR 只支持 ES；OG 必须是 SQL |
| HBase 生成了 SELECT | 检查是否选了 `local-hbase`，以及 dialect 规则是否入库 |
| OpenCode 调不通 | Web 必须在 8199；Skill 用的是 NL2SQL 自己的 LLM 配置，不是 OpenCode 会话模型 |

API 见 `opencode_plugin/skills/nl2sql/references/api.md`。
