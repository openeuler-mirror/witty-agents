# NL2SQL Skill CLI 参考

本文件供 Agent 查阅：**命令、参数、返回 JSON 含义**。  
入口脚本：`scripts/nl2sql_skill_cli.py`（快捷：`ask.py` / `health.py` / `rules_import.py`）。

```bash
python3 $SKILL/scripts/nl2sql_skill_cli.py <command> [options]
```

## 仓库根如何定位

CLI 通过 `_common.py` 解析 **NL2SQL 仓库根**（须含 `nl2sql_core/` + `configs/`）：

| 优先级 | 来源 |
|--------|------|
| 1 | 环境变量 `NL2SQL_ROOT` |
| 2 | `$SKILL/scripts/config.json` 字段 `nl2sql_root`（绝对路径；可参考 `config.example.json`） |
| 3 | 默认：假定 skill 在 `<repo>/opencode_plugin/skills/nl2sql/scripts`，上溯 4 级到 `<repo>` |

skill 放在 `~/.config/opencode/skills/nl2sql` 时，**必须**配置 1 或 2，否则无法 import `nl2sql_core`。  
`config.json` 仅本机使用，仓库 `.gitignore` 已忽略；请提交 `config.example.json` 作模板。

- **stdout = JSON**。失败时常见：`{"ok": false, "error": "..."}` 且 exit ≠ 0。  
- **不要**调用本机 Web HTTP；本 CLI 即全部能力面。
- 解析到仓库根后，进程会 `chdir` 到该根，以便读取 `.env` / `configs/` / `data/`。

---

## 通用约定

| 项 | 说明 |
|----|------|
| 数据源 id | 问答/测库用 `--datasource-id`（默认多数字段为 `local-es`） |
| 规则库 id | 规则命令用 `--database-id`（通常与 datasource id 相同，如 `local-es`） |
| mode | `auto` / `sql` / `dsl` / `scan`（ask、consistency）；`auto` 按引擎选择生成形态 |
| 配置文件 | `settings-set` 写入 `data/runtime_settings.json`；亦可读仓库根 `.env` |

---

## health

```bash
... health [--datasource-id local-es]
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `--datasource-id` | 空 | 非空则额外探测该业务库 |

**返回要点：** `ok`、`rag_core.ok`、`current.ok`（若测了库）、`engines`、`note`。

---

## settings-get

```bash
... settings-get
```

无参数。返回当前生效的 LLM / rag / ES / OpenGauss / HBase 相关字段，以及 `settings_file` 路径。

---

## settings-set

```bash
... settings-set [--file FILE] [--set key=value]...
```

| 参数 | 含义 |
|------|------|
| `--file` | JSON 对象文件，或 `-` 表示 stdin |
| `--set` | 可重复；`key=value`。value 以 `[`/`{` 开头则按 JSON 解析；纯数字则转 int |

与 `--file` 合并时：先读已有 runtime，再覆盖。至少提供 `--file` 或一次 `--set`。

**常用 key：**

| key | 含义 |
|-----|------|
| `llm_base_url` / `llm_api_key` / `llm_model` | LLM（OpenAI 兼容） |
| `rag_base_url` / `rag_access_key` / `rag_kb_id` | rag-core |
| `es_hosts` | 数组，如 `["http://127.0.0.1:9200"]` |
| `es_username` / `es_password` / `es_default_index` | ES |
| `og_host` / `og_port` / `og_database` / `og_username` / `og_password` | OpenGauss |
| `hbase_host` / `hbase_rest_port` / `hbase_thrift_port` / `hbase_rest_url` | HBase |

**返回：** `{"ok": true, "saved_keys": [...]}`

---

## datasources

```bash
... datasources
```

**返回：** `datasources`（来自 `configs/datasources.yaml`）、`engines`。

---

## datasources-test

```bash
... datasources-test [--datasource-id local-es]
```

测**一个**源。**返回：** `ok`、`type`，失败时有 `error`。

---

## ask（核心：生成 + 执行，或仅执行）

```bash
... ask --query|-q TEXT
    [--datasource-id local-es] [--mode auto]
    [--no-llm] [--skip-clarify] [--interactive-clarify]
    [--clarify-session-id ID] [--clarify-message TEXT]
    [--execute-query TEXT] [--execute-file PATH]
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `-q / --query` | **必填** | 自然语言；仅执行时可写占位如 `(exec)` |
| `--datasource-id` | `local-es` | 当前库 |
| `--mode` | `auto` | 生成模式（全链路生成时有意义） |
| `--no-llm` | off | 不调用 NL2SQL 配置的 LLM 生成（**Agent 自研查询后执行时必开**） |
| `--skip-clarify` | off | 完全跳过问句理解/澄清（仅执行时建议开） |
| `--interactive-clarify` | **off** | 打开则可能多轮追问（走 NL2SQL LLM）；默认关=静默改写 |
| `--clarify-session-id` + `--clarify-message` | — | 澄清续答并继续跑 pipeline |
| `--execute-query` | — | 直接执行：SQL 字符串，或以 `{` 开头的 JSON（IR/DSL） |
| `--execute-file` | — | 从文件读执行体（JSON 或文本） |

### 两种用法

**1）Agent 会话模型已生成查询 — 只执行（推荐与框架模型配合）**

```bash
... ask -q "(exec)" --datasource-id local-es --no-llm --skip-clarify \
  --execute-query 'SELECT ...'
# 或 --execute-file /tmp/plan.json
```

此前应用 `schema` / `rules-search` 给会话模型当上下文。执行与只读校验仍由 `nl2sql_core` 完成。

**2）NL2SQL 已配置 LLM — 全链路**

不加 `--no-llm`、不传 `--execute-query`：静默理解 → 召回规则 → **NL2SQL 所配模型**生成 → 执行。

### 返回 JSON（成功跑完 pipeline）

| 字段 | 含义 |
|------|------|
| `generated_query` | 全链路时为模型生成的查询/计划；仅执行时也可能回显执行体 |
| `result` | `{ columns, rows, row_count, mode, warnings? }` |
| `resolved_query` | 实际用于生成的问句 |
| `steps` | 流水线步骤列表（`name` / `status` / `message`） |
| `error` | 非空表示失败 |
| `rules` | 召回规则摘要（全链路时） |
| `need_clarify` | 一般为 false |

### 返回 JSON（需要澄清）

```json
{
  "need_clarify": true,
  "clarify_session": { "id": "...", "done": false, "messages": [...], ... },
  "query": "<原问句>",
  "hint": "..."
}
```

此时**不要**声称已查出数据；把澄清问题发给用户，再用 `clarify-reply` 或带 session 的 `ask` 继续。也可改为在对话内澄清后走「只执行」路径。

---

## clarify-start

```bash
... clarify-start --query|-q TEXT [--max-rounds 3]
```

**返回：** 澄清会话对象（含 `id`、`messages`、`done`、`resolved_query` 等）。`done==false` 时最后一条助手消息即待回答问题。

---

## clarify-reply

```bash
... clarify-reply --session-id ID --message|-m TEXT
```

**返回：** 更新后的会话。若 `done==true`，用 `resolved_query` 调用 `ask -q "<resolved>" --skip-clarify` 或带 session 的续跑。

---

## schema

```bash
... schema [--datasource-id local-es]
```

**返回：** 引擎 schema 摘要（indexes/fields 等），用于解释库结构或辅助写规则。

---

## rules-list

```bash
... rules-list [--database-id local-es] [--rule-type TYPE]
```

**返回：** `count`、`rules`（最多约 500 条预览）。

---

## rules-upsert

```bash
... rules-upsert [--database-id local-es] --file PATH
```

`--file` 为**单条**规则 JSON 对象。

---

## rules-search

```bash
... rules-search [--database-id local-es] [--query|-q TEXT] [--rule-type TYPE] [--top-k 20]
```

**返回：** `count`、`rules`。

---

## rules-bootstrap

```bash
... rules-bootstrap [--database-id local-es]
```

用仓内 FIELD-GUIDE/fixtures **灌本地规则缓存**；不自动等于 rag 已就绪。问答仍需有效 `rules_kb_id` / 后续 sync 或 init-commit。

---

## rules-init-preview

```bash
... rules-init-preview [--database-id local-es] [--no-llm-domain]
```

从真实库抽样生成规则包，**写入** `data/rules/init_bundles/init_*.json`，**不写 rag**。

**返回要点：** `ok`、`bundle_path`、`counts`、`warnings`、`rules`。

---

## rules-init-commit

```bash
... rules-init-commit --from-file PATH
    [--bundle PATH] [--database-id ID] [--kb-name NAME]
    [--no-recreate-kb] [--no-persist-kb]
```

| 参数 | 含义 |
|------|------|
| `--from-file` | preview 得到的 bundle 路径（常用） |
| `--bundle` | 或直接给 bundle JSON 文件 |
| `--no-recreate-kb` | 不新建 KB（慎用） |
| `--no-persist-kb` | 不把 kb_id 写回配置 |

**返回：** 含 rag KB 信息等（以实际 JSON 为准）。成功后该源应具备可召回的规则库，再 `ask`。

---

## rules-generate

```bash
... rules-generate --text|-t TEXT [--database-id local-es] [--no-schema]
```

自然语言 → **规则草稿**，**不入库**。默认附带 schema 摘要给模型。

**返回：** `ok`、`count`、`rules`。给人确认后写入文件再 `rules-import`。

---

## rules-import

```bash
... rules-import --file PATH [--database-id local-es] [--no-sync-rag]
```

| 参数 | 含义 |
|------|------|
| `--file` | JSON：**数组**，或 `{"rules":[...]}` |
| `--no-sync-rag` | 只写本地，不 upsert rag |

**返回：** `ok`、`imported_local`、`rag`、`rules`。

快捷：`python3 $SKILL/scripts/rules_import.py --file ...`（参数同本命令）。

---

## consistency

```bash
... consistency --query|-q TEXT
    [--datasource-id local-es] [--repeats 3] [--mode auto]
```

同一问句跳过澄清连跑 N 次，比较结果集。

**返回要点：** `result_consistency`（0~1）、`valid_runs` / `invalid_runs`、`runs[]`（每轮 `row_count`、`generated_query`、`error`）。

注意：三轮同样错成空结果时一致性也可能很高；需结合 `generated_query` 判断对错。

---

## Agent 读结果时的优先级

1. 若有顶层 `error` 或 `ok: false` → 先处理错误。  
2. 若 `need_clarify` → 只做澄清交互。  
3. 否则展示 `generated_query` + `result`。  
4. `steps` 用于排障，不必整段贴给用户 unless 用户要细节。
