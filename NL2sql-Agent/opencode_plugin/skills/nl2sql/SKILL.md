---
name: nl2sql
description: >
  自然语言转只读查询并执行（ES IR / OpenGauss SQL / HBase scan）。
  用本 skill 的 scripts/nl2sql_skill_cli.py 本地调用仓库 nl2sql_core，不要启动任何 Web 端口。
  生成查询可用：① Agent 框架自身模型；② 若已配置则走 NL2SQL 的 LLM（ask 全链路）。
  执行必须走 CLI（只读引擎）。支持设置、测库、澄清、问答、规则导入/冷启动、一致性。
  Triggers: NL2SQL、自然语言查库、查人员、购票、进站、生成 SQL、执行查询、导入规则、规则冷启动、一致性。
---

# NL2SQL Skill

你通过 **Bash（或等价工具）执行本 skill 下的 Python CLI** 完成任务。所有子命令把结果打到 **stdout，且为 JSON**。根据 JSON 向用户解释，不要假装自己直连了数据库。

## 0. 环境与入口（每次任务先确定）

1. **仓库根** `REPO`：含 `nl2sql_core/`、`configs/`、`.env`（或随后用 settings 写入）的目录。  
2. **本 skill 目录** `SKILL`：本文件所在目录（其下有 `scripts/`、`references/`）。  
3. 入口命令（推荐始终用绝对路径）：

```bash
CLI="python3 $SKILL/scripts/nl2sql_skill_cli.py"
# 等价快捷（参数同对应子命令）：
#   python3 $SKILL/scripts/ask.py ...
#   python3 $SKILL/scripts/health.py ...
#   python3 $SKILL/scripts/rules_import.py ...
```

脚本会自动把 `REPO` 加入 `sys.path`，一般**不必**再 export `PYTHONPATH`，但工作目录建议在 `REPO`。

4. **详细参数与返回字段**：必读 `references/api.md`。  
5. **禁止**：启动/依赖 `http://127.0.0.1:8199` 或任何 NL2SQL Web；禁止对业务库做写删；禁止编造未在规则/schema 中的字段映射。

依赖（由用户环境提供，不是本 skill 启动的服务）：本机 Python≥3.10、已部署的 **rag-core**、目标业务库（如 ES）。  
**LLM：** 生成查询时优先可用 **Agent 框架当前会话模型**；若 NL2SQL 已配置 Key，也可用全链路 `ask`（见 §2.1）。

---

## 1. 硬规则

| 规则 | 说明 |
|------|------|
| 执行必须走 CLI | 在业务库上跑查询只用 `$CLI ask ... --execute-query/--execute-file` 或全链路 `ask`；禁止自己拼 JDBC/curl 写库 |
| 生成可用两种模型 | **Agent 会话模型** 或 **NL2SQL 已配置的 LLM**（见 §2.1）；不要在未配置时强行全链路 `ask` 却不说明失败原因 |
| 只读 | 禁止 INSERT/UPDATE/DELETE/DROP 等；用户要求写库时拒绝 |
| 数据源 | `--datasource-id` / `--database-id` 与用户当前库一致（常见 `local-es`） |
| 配置来源 | `.env` + `data/runtime_settings.json`（`settings-set` 写后者） |
| 失败时 | 把 JSON 里的 `error` / `steps` 摘要告诉用户，再决定是否改配置、补规则、换问法或改用另一生成路径 |

---

## 2. 生成用谁的模型？（重要）

| 路径 | 何时用 | 怎么做 |
|------|--------|--------|
| **A. Agent 框架模型生成**（推荐默认） | 会话里已有可用模型；或不想依赖 NL2SQL 的 `llm_api_key` | 你（Agent）根据 `schema` / `rules-search` / `rules-list` 结果**自己写出**只读 SQL 或 ES IR JSON → 再 `$CLI ask ... --execute-query/--execute-file --no-llm --skip-clarify` **只执行** |
| **B. NL2SQL 配置的 LLM 生成** | `settings-get` 显示已有有效 `llm_api_key`（或 `.env` 已配），且希望走完整 Pipeline（静默澄清+召回+生成+执行+重试） | `$CLI ask -q "..." --datasource-id <源>`（不要加 `--no-llm`） |

原则：

1. **执行、引擎、只读校验、结果表** → 始终用 CLI / `nl2sql_core`，不要跳过。  
2. **写查询文本** → 可用你自己的模型；写完必须交给 CLI 执行并依据返回 JSON 回答。  
3. 若路径 B 因未配 Key 失败，**自动改走路径 A**，不要停在空报错上。  
4. 澄清也可在对话里由你完成；不必强制 `clarify-*`（那些子命令仍会调 NL2SQL 侧 LLM）。

路径 A 最小步骤示例：

```bash
$CLI schema --datasource-id local-es
$CLI rules-search --database-id local-es -q "<用户问句关键词>" --top-k 20
# （你用会话模型根据 schema+规则写出只读查询）
$CLI ask -q "(exec)" --datasource-id local-es --no-llm --skip-clarify \
  --execute-query '<你生成的 SQL 或 IR JSON>'
```

IR 较大时写入临时文件再用 `--execute-file /tmp/plan.json`。

---

## 3. 按用户意图选命令（决策）

| 用户意图 | 你应执行 |
|----------|----------|
| 查一句自然语言 / 要结果表 | **优先路径 A**（自研生成 + execute）；或路径 B 全链路 `ask`（已配 NL2SQL LLM 时） |
| 问句很含糊、要追问 | 对话内澄清，或 `ask --interactive-clarify` / `clarify-start`→`clarify-reply`（后两者依赖 NL2SQL LLM） |
| 已有 SQL 或 IR JSON，只要执行 | `ask -q "(exec)" --execute-query '...' --no-llm --skip-clarify`（或 `--execute-file`） |
| 改 LLM / rag / 连接 | `settings-get` → `settings-set` |
| 库通不通 | `health` / `datasources-test` |
| 有哪些库 | `datasources` |
| 看表结构 | `schema` |
| 补/导入规则 | `rules-generate`（需 NL2SQL LLM）或你起草 JSON 后 `rules-import`；冷启动用 `rules-init-*` |
| 同句多次稳不稳 | `consistency`（内部多次全链路生成，依赖 NL2SQL LLM） |

---

## 4. 主路径：用户给一句 query（最常用）

目标：给出**生成的查询** + **执行结果**。

### 4.1 可选体检

```bash
$CLI health --datasource-id local-es
$CLI datasources-test --datasource-id local-es
```

关注：`rag_core.ok`、`current.ok`。不通则先修连接/`settings-set`。

### 4.2 路径 A — Agent 模型生成 + CLI 执行（默认推荐）

1. 拉取上下文：`schema`、`rules-search`（和/或 `rules-list`）  
2. 用**当前 Agent 会话模型**生成只读查询（遵守方言/规则；ES 可为 IR JSON 或引擎接受的 SQL 计划形态）  
3. 执行：

```bash
$CLI ask -q "(exec)" --datasource-id local-es --no-llm --skip-clarify \
  --execute-query '<生成结果>'
```

4. 向用户展示：你生成的查询原文 + JSON 里的 `result` / `error`

### 4.3 路径 B — 全链路 ask（NL2SQL 已配置 LLM 时）

```bash
$CLI ask -q "<用户原话>" --datasource-id local-es
```

行为：静默理解 → 召回规则 → **NL2SQL 所配 LLM** 生成 → 执行。

汇报时说明：

- `resolved_query`、`generated_query`、`result.row_count` 与行要点  
- 若有 `error`：看 `steps`；若是缺 API Key，改走 §4.2

### 4.4 需要多轮澄清时

优先在**对话里**由你追问（用会话模型）。若走 NL2SQL 澄清 CLI：

```bash
$CLI ask -q "<问句>" --datasource-id local-es --interactive-clarify
```

若返回 `"need_clarify": true`：

1. 从 `clarify_session` 取出助手问题，**原样问用户**  
2. 用户回答后：

```bash
$CLI clarify-reply --session-id "<clarify_session.id>" -m "<用户回答>"
# 若 session.done==true，用 resolved_query 再 ask；或：
$CLI ask -q "<原问句>" --datasource-id local-es \
  --clarify-session-id "<id>" --clarify-message "<用户回答>"
```

也可先 `clarify-start -q "..."` 再循环 `clarify-reply`。

### 4.5 只执行、不生成（路径 A 的执行步 / 用户已给 SQL）

```bash
$CLI ask -q "(exec)" --datasource-id local-es --no-llm --skip-clarify \
  --execute-query 'SELECT ... LIMIT 100'
# IR/DSL JSON：
$CLI ask -q "(exec)" --datasource-id local-es --no-llm --skip-clarify \
  --execute-file /tmp/plan.json
```

---

## 5. 设置

```bash
$CLI settings-get
$CLI settings-set --set llm_base_url=https://api.openai.com/v1 \
  --set llm_api_key=sk-xxx --set llm_model=gpt-4o-mini \
  --set rag_base_url=http://127.0.0.1:19988 --set rag_access_key=debug-access-key
```

`es_hosts` 等复杂值可用 JSON：`--set 'es_hosts=["http://127.0.0.1:9200"]'` 或 `--file settings.json`。键名完整列表见 `references/api.md`。  
配置 NL2SQL LLM 后路径 B 才稳定；**不配也可以**只用路径 A。

---

## 6. 规则相关

```bash
# 自然语言 → 草稿（不入库；此命令走 NL2SQL LLM。也可用会话模型起草 JSON 后直接 import）
$CLI rules-generate --database-id local-es -t "标签上访=信访人员；去过X用 to_station_name"

# 导入（本地 + rag upsert）；文件为规则数组或 {"rules":[...]}
$CLI rules-import --database-id local-es --file /tmp/rules.json

# 列表 / 检索 / 单条
$CLI rules-list --database-id local-es
$CLI rules-search --database-id local-es -q "飞机忽略"
$CLI rules-upsert --database-id local-es --file /tmp/one_rule.json

# 演示用 FIELD-GUIDE → 本地缓存（不自动进 rag）
$CLI rules-bootstrap --database-id local-es

# 冷启动：预览包 → 确认后入库
$CLI rules-init-preview --database-id local-es
$CLI rules-init-commit --from-file <返回的 bundle_path>
```

全链路 `ask`（路径 B）前请确保该数据源已配置 `rules_kb_id`；路径 A 也强烈建议先 `rules-search` 再生成。

---

## 7. 一致性

```bash
$CLI consistency -q "<完整问句>" --datasource-id local-es --repeats 3
```

看 `result_consistency`（0~1）与各轮 `generated_query`。此命令内部多次调用 NL2SQL LLM，需已配置。一致性高≠业务正确。

---

## 8. 向用户表述结果的模板

1. **查询**：路径 A 展示你生成的查询；路径 B 展示 `generated_query`  
2. **结果**：行数 + 关键列（来自 CLI JSON 的 `result`）；0 行说明可能是条件无数据或规则/标签未对齐  
3. **异常**：引用 `error`，给出下一步（改走另一生成路径、补 Key、测库、导入规则、改问句）

不要编造未出现在 JSON 中的行数据。
