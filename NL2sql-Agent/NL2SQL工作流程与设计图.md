# NL2SQL 工作流程与设计图

> 基于当前可运行实现（`apps/web` + `nl2sql_core` + OpenCode Skill）  
> 更新：2026-08-26

**说明：** 本文使用 **ASCII 文本图**，任意 Markdown 编辑器/预览都能直接看到。  
（若文档里写的是 ` ```mermaid ` 代码块，那不是图片，需要 GitHub、Typora、VS Code 插件等才渲染成图。）

---

## 1. 一句话

用户用自然语言提问 →（可选澄清）→ 从 **rag-core** 召回规则 → **LLM** 生成只读 SQL/DSL → 在 **Elasticsearch** 执行 → 返回表格；失败或 0 行可带反馈重试。

**规则在 rag-core，业务明细在 ES，Core 不写死业务 SQL。**

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│ 接入层                                                           │
│  ┌──────────────────────┐    ┌──────────────────────────────┐  │
│  │ Web UI  :8199         │    │ OpenCode Skill                │  │
│  │ 智能问答 / 规则中心    │    │ HTTP 调同一套 API             │  │
│  │ 一致性测试            │    │                               │  │
│  └──────────┬───────────┘    └──────────────┬───────────────┘  │
└─────────────┼────────────────────────────────┼──────────────────┘
              │                                │
              └────────────────┬───────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 编排层  apps/web/main.py                                         │
│  澄清（交互 / 静默 / 跳过） → resolved_query                      │
│  /api/query  ·  /api/query/stream（步骤级 SSE）                   │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ nl2sql_core                                                      │
│  NL2SQLPipeline → 召回规则 → LLM 生成 → 只读检查 → QueryEngine 执行 │
└───────┬───────────────────────────────┬─────────────────────────┘
        │                               │
        ▼                               ▼
┌───────────────┐               ┌───────────────────┐
│ rag-core      │               │ Elasticsearch     │
│ :19988        │               │ :9200             │
│ JSON 规则 KB  │               │ 业务索引（明细）   │
└───────────────┘               └───────────────────┘
        ▲
        │ 生成时另调
┌───────┴───────┐
│ LLM API      │
│（OpenAI 兼容）│
└───────────────┘
```

| 层次 | 职责 |
|------|------|
| **接入层** | Web 页面或 OpenCode；不重复实现查询逻辑 |
| **编排层** | 澄清问句、SSE 流式、规则运维 API |
| **Core** | 召回 → 生成 → 执行 → 重试 |
| **rag-core** | 方言 / 领域 / Schema 规则（运行时权威） |
| **ES** | 业务数据 |

---

## 3. 智能问答主流程

```
  用户                    Web / OpenCode              澄清              Pipeline           rag-core    LLM      ES
   │                            │                      │                   │                │         │        │
   │  自然语言问句               │                      │                   │                │         │        │
   ├───────────────────────────►│                      │                   │                │         │        │
   │                            │                      │                   │                │         │        │
   │         ┌──────────────────┴── 澄清=开：多轮 start/reply（≤3 轮）    │                │         │        │
   │         │                  ├── 澄清=关：auto_resolve 静默改写          │                │         │        │
   │         │                  └── skip / 手写 SQL：跳过澄清               │                │         │        │
   │                            │                      │                   │                │         │        │
   │                            │  resolved_query      │                   │                │         │        │
   │                            ├──────────────────────►                   │                │         │        │
   │                            │                      │  run(query)       │                │         │        │
   │                            ├─────────────────────────────────────────►│                │         │        │
   │                            │                      │                   │  召回规则       │         │        │
   │                            │                      │                   ├───────────────►│         │        │
   │                            │                      │                   │◄───────────────┤ ≤50 条  │        │
   │                            │                      │                   │                │         │        │
   │                            │                      │         ┌─────────┴──────── 重试环（≤3 次）────────┐
   │                            │                      │         │  规则+问句 → 生成 SQL/DSL                 │
   │                            │                      │         ├──────────────────────────────────────────►│
   │                            │                      │         │◄──────────────────────────────────────────┤
   │                            │                      │         │  只读检查 → 执行 ────────────────────────►│ ES
   │                            │                      │         │◄───────────────────────────────────────────┤ 行数据
   │                            │                      │         │  失败/0 行 → retry_feedback → 再生成       │
   │                            │                      │         └──────────────────────────────────────────┘
   │                            │                      │                   │                │         │        │
   │  结果表 + 步骤（SSE）       │◄─────────────────────────────────────────┤                │         │        │
   │◄───────────────────────────┤                      │                   │                │         │        │
```

### 3.1 澄清三种模式

| 模式 | 参数 | 行为 |
|------|------|------|
| 多轮头脑风暴 | `interactive_clarify=true` | 一次一问，够清晰则立刻结束，最多 3 轮 |
| 自动理解 | `interactive_clarify=false` | 模型单次改写，不弹追问 |
| 跳过 | `skip_clarify=true` 或手写 `execute_query` | 直接进 Pipeline |

澄清在 **编排层**完成，不塞进 `Pipeline.run` 内部。

### 3.2 Pipeline 内部步骤

```
resolve_engine          读 datasources → 选择引擎 / dialect
    ↓
retrieve_rules          rag-core 召回（见 §4）
    ↓
generate                LLM 生成查询：
                          · ES → mode=ir（Query IR + semi_joins）
                          · 其它方言 → mode=sql/dsl（以召回 dialect 为准）
    ↓
safety                  只读检查（SQL 路径）；IR 路径在编译后单表 SQL 上校验
    ↓
execute                 · IR：多步半连接（查从表键 → 交集 → 回表主索引）
                          · SQL/DSL：引擎执行（含历史 IN(SELECT) 兜底等）
    ↓
（可选）kg_verify       占位，未启用
    ↓
result / retry          失败或 0 行 → 反馈 → 再 generate
```

业务别名、标签标准值、可忽略条件等一律放在 **rag-core 规则**（domain/schema），不在引擎代码写死。

---

## 4. 规则召回流程

```
  用户问句 (resolved_query) ──┐
  当前 dialect (elasticsearch)┘
              │
              ▼
      RuleStore.search
              │
    ┌─────────┼─────────┐
    │         │         │
    ▼         ▼         ▼
 固定 pin   语义检索   分路补召
 scope=    问句 +      scope=
 dialect   [dialect=   domain /
           ...] 标签    schema
    │         │         │
    └─────────┼─────────┘
              ▼
    rag-core  POST /json/search
    过滤: database_id, dialect ∈ {引擎, shared}
              │
              ▼
    合并去重 · 方言规则置顶 · 最多 rules_top_k 条（默认 50）
              │
              ▼
         送入 LLM 生成 prompt
```

**语义 query 示例：**

- `去过西安的限高人员`
- `[dialect=elasticsearch] 去过西安的限高人员`

---

## 5. 规则生命周期（运维）

```
  FIELD-GUIDE.md + fixtures/rules/*.json
              │
              ▼
    bootstrap / sync_rules_to_rag.py
         ┌────┴────┐
         ▼         ▼
  data/rules/*.json   rag-core JSON KB (rules_kb_id)
  （本地缓存）              │
                          ▼
                    运行时召回

  规则中心 NL 描述
         │
         ▼
  generate_from_nl（F1: domain/dialect/别名）
         │
         ▼
  人工编辑 / 勾选
         │
         ▼
  import 增量 upsert ──► rag-core KB
```

| 规则层 | scope | 来源 | 召回 |
|--------|-------|------|------|
| 方言 | dialect | `fixtures/rules/dialects/` | **固定注入** |
| 领域 | domain | domain.json、station_aliases | 语义 |
| Schema | schema | FIELD-GUIDE → ddl/mapping | 语义 |

业务约定（限高怎么查、站点别名、字段名）**只写在规则里**，不在 Core Python 硬编码。

---

## 6. 其他能力

### 6.1 一致性测试

```
同一问句 × N（默认 3）
  → skip_clarify
  → 多次 Pipeline
  → 报错轮次不计
  → 结果集 Jaccard 比一致性
```

入口：Web「一致性测试」或 `POST /api/consistency/run`。

### 6.2 OpenCode

```
OpenCode Agent + Skill
  → GET /api/health
  →（可选）澄清 API
  → POST /api/query 或 /api/query/stream
  →（可选）规则 generate/import
```

**Web/API 进程（8199）必须运行**；Skill 本身不内嵌引擎。

---

## 7. 部署关系（简图）

```
                    ┌─────────────────────────────┐
                    │         测试机               │
                    │                             │
                    │  NL2SQL (start_all.sh)      │
                    │       :8199                 │
                    │         │                   │
                    │    ┌────┼────┐              │
                    │    ▼    ▼    ▼              │
                    │   ES  rag   LLM 云服务       │
                    │  :9200 :19988               │
                    │  Docker  已有实例            │
                    └─────────────────────────────┘
```

详见 [docs/DEPLOY.md](./docs/DEPLOY.md)、[docs/TEST.md](./docs/TEST.md)。

---

## 8. 关键配置

| 文件 | 作用 |
|------|------|
| `configs/app.yaml` | 端口、重试次数、`rules_top_k` |
| `configs/datasources.yaml` | ES 连接、`rules_kb_id` |
| `configs/rag_core.yaml` | rag 地址、access_key |
| `.env` / Web 设置 | LLM Key、运行时覆盖 |

---

## 9. 设计原则（当前）

1. **一套 Core**：Web 与 OpenCode 共用 Pipeline 与 HTTP 契约  
2. **澄清在编排层**：Pipeline 只处理「已清晰的问句」  
3. **规则与数据分离**：rag 存规则，ES 存明细  
4. **方言可插拔**：`dialect` 字段 + 引擎实现；业务不进代码  
5. **默认全字段**：生成侧倾向 `SELECT *`，避免错列名空列  
