---
name: crash-feature-matcher
description: |
  Extracts crash features (bug_type, RIP, CallTrace, related modules) from Linux kernel crash logs
  (dmesg/kern/vmcore-dmesg) or vmcore files and matches against a known-issue knowledge base via
  euler-copilot-rag using L1 fingerprint matching and L2 RAG-driven search.
  Also supports community case retrieval from Linux/openEuler community KBs with
  kernel-version logical filtering and content fuzzy search.
  Applicable to kernel panic, oops, NULL pointer dereference, general protection fault,
  soft lockup, hard lockup, double fault, kernel BUG at, invalid opcode, KASAN/KFENCE,
  RCU stall, hung task, memory corruption, stack overflow, NX/SMEP violation scenarios.
tools: [Bash, Read]
mcp:
  crash-feature-matcher:
    type: stdio
    command: "/root/.config/opencode/skills/crash-feature-matcher/run_mcp.sh"
    args: []
allowed-tools: Bash(python3:*) Bash(pip:*) Bash(curl:*) Bash(crash:*) Bash(cat:*) Bash(ls:*) Bash(rg:*) Bash(bash:*)
---

# crash-feature-matcher

`crash-feature-matcher` is a Linux kernel crash analysis tool with two core capabilities:

1. **Crash Feature Matching**: Extracts RIP, call trace, modules, and other features from `dmesg` / `vmcore` and matches them against a known-issue knowledge base.
2. **Community Case Retrieval**: Retrieves community cases from Linux/openEuler community KBs based on query text and kernel version.

---

## Dependencies

**Python packages:** `fastmcp>=2.0.0`, `pydantic>=2.0.0`, `httpx>=0.27.0`, `click>=8.0.0`, `jieba>=0.42.0`, `synonyms>=3.23.0` (see `requirements.txt` or `pyproject.toml`)

**External tools:** `crash` (required for vmcore analysis, plus matching vmlinux)

**Services:** euler-copilot-rag (default `http://localhost:9988`)

---

## Configuration

Configuration is loaded from a TOML file and validated by Pydantic models. The default
file is `src/crash_matcher/settings.toml`. Override the path with:

```bash
export CRASH_MATCHER_CONFIG=/path/to/custom.toml
```

### TOML Structure

```toml
[rag]
base_url = "http://localhost:9988"
knowledge_kb_id = "c3a9bc93-9244-432e-9d9e-5355ed8d0fb7"
cases_kb_id = ""
openeuler_community_kb_id = "534ffa02-3575-4995-bf16-6e5c51191d46"
linux_community_kb_id = ""
access_key = ""
timeout = 30.0

[matcher]
stack_similarity_threshold = 0.75
dmesg_analysis_window_seconds = 180
max_log_line_in_db = 300
rip_fuzzy_offset = 8

[community]
score_threshold = 80
top_k_final = 3
l1_top_k = 3
l3_top_k = 5

[[l2_search_rules]]
bug_key_patterns = ["NULL pointer dereference", "kernel paging request", ...]
query_from = "rip_function"
search_mode = "like"
ratio = 0.3
semantic_keys = []
filter_bug_type = true
strategy = "exact_rip_with_bugkey"
```

### Environment Variable Overrides

For secrets or quick ad-hoc overrides, the following environment variables are still
supported and take precedence over the TOML file:

| Environment Variable | Maps to TOML key | Description |
|----------------------|------------------|-------------|
| `RAG_BASE_URL` | `rag.base_url` | euler-copilot-rag service endpoint |
| `CRASH_KNOWLEDGE_KB_ID` | `rag.knowledge_kb_id` | Known-issue KB (populated from OSClinic) |
| `CRASH_CASES_KB_ID` | `rag.cases_kb_id` | Per-crash case records |
| `LINUX_COMMUNITY_KB_ID` | `rag.linux_community_kb_id` | Linux community cases |
| `OPENEULER_COMMUNITY_KB_ID` | `rag.openeuler_community_kb_id` | openEuler community cases |
| `RAG_ACCESS_KEY` | `rag.access_key` | RAG access key |
| `CRASH_MATCHER_CONFIG` | — | Path to custom TOML config file |

### Pydantic Models

All configuration is defined in `src/crash_matcher/config_models.py`:

- `RagConfig`: RAG endpoint and KB IDs
- `MatcherConfig`: thresholds and analysis windows
- `CommunityConfig`: retrieval top-k and score threshold
- `L2SearchRule`: bug_key-driven search strategies
- `SkillConfig`: top-level container

Runtime code should access configuration through `Config().get()`:

```python
from crash_matcher.config import Config

cfg = Config().get()
print(cfg.rag.base_url)
print(cfg.community.score_threshold)
```

> **Note**: There are no module-level constants (e.g. `RAG_BASE_URL`, `CRASH_KNOWLEDGE_KB_ID`) anymore. All code should use `Config().get()` so that defaults are defined in Pydantic models and can be overridden via TOML or environment variables.

RAG search payloads are also modeled with Pydantic:

- `Expression`: logical expression leaf
- `LogicalExpression`: AND/OR expression node
- `SearchConfig`: `/json/search` request item

> **Note**: There are no module-level constants (e.g. `RAG_BASE_URL`, `CRASH_KNOWLEDGE_KB_ID`) anymore. All code should use `Config().get()` so that defaults are defined in Pydantic models and can be overridden via TOML or environment variables. Production known-issue data is typically imported from the OSClinic platform into `rag.knowledge_kb_id` via `scripts/import_from_osclinic.py`.

---

## Unified Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Input Sources                               │
│   dmesg_text / dmesg_file / vmcore_file + vmlinux_file              │
│   OR                                                                 │
│   query_text + kernel_version (community retrieval)                 │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Phase 1: Feature Extraction                       │
│  For dmesg/vmcore:                                                   │
│    - Parse dmesg → CrashFeatures + HostFeatures                     │
│    - Compute signature fingerprint                                  │
│  For community query:                                                │
│    - Extract / normalize query terms and kernel_version             │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Phase 2: Knowledge Base Matching                  │
│                                                                      │
│  Two parallel retrieval paths depending on input type:              │
│                                                                      │
│  Path A: Crash Analysis (known-issue matching)                      │
│    ├─ L1 Fingerprint Match                                          │
│    │     Search by fingerprint keyword, exact match → matched=true  │
│    ├─ L2 RAG-driven Search (only on L1 miss)                        │
│    │     Build search config from bug_key                           │
│    │     Local validation (rip_function, bug_type, etc.)            │
│    │     Score ≥ 60 → matched=true                                  │
│    └─ All miss → create new issue (matched=false)                   │
│                                                                      │
│  Path B: Community Case Retrieval (query + kernel_version)          │
│    ├─ L1 Linux + openEuler Community                                │
│    │     kernel_version logical filter, top3 each                   │
│    │     score > 80 → stop, return top3                             │
│    ├─ L2 Secondary Confirmation on L1 results                         │
│    │     score >= 80 or kernel exact + content overlap               │
│    │               → stop, return top3                             │
│    └─ L3 Broader Recall                                             │
│          Linux + openEuler top5 each, rerank, return top3            │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Phase 3: Output                                   │
│  Crash analysis: MatchResult (knowledge, similar_cases, suggestions) │
│  Community retrieval: CommunityMatchResult (cases, stop_reason)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Core MCP Tools

All tools are exposed via the `CrashFeatureMatcher` FastMCP server.

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `analyze_crash` | Parse dmesg text/file → extract features + match known issues | `dmesg_text`, `dmesg_file` |
| `analyze_vmcore` | Analyze vmcore+vmlinux via crash command (local only, no RAG) | `vmcore`, `vmlinux` |
| `query_knowledge` | Search known-issue KB | `bug_type`, `rip_function`, `keyword` |
| `CrashFeatureMatcher:query_cases` | Search historical crash cases | `knowledge_id`, `host_name` |
| `CrashFeatureMatcher:query_community_cases` | L1/L2/L3 community case retrieval (Linux → openEuler). See Query Text Guidelines below for query_text construction rules. | `query_text`, `kernel_version` |
| `CrashFeatureMatcher:add_knowledge` | Add a new known-issue entry | `bug_summary`, `bug_type`, `bug_key`, `fingerprints`, `rip`, `rip_function`, `rip_offset`, `related_modules`, `call_trace_text`, `call_trace_signature`, `root_cause`, `solution`, `hotpatch` |
| `CrashFeatureMatcher:merge_knowledge` | Merge multiple similar issues into one | `source_ids`, `target_bug_summary`, `target_root_cause`, `target_solution`, `target_hotpatch` |
| `CrashFeatureMatcher:query_upstream_online` | Explicit online retrieval when local KBs (internal/community/history) yield no high-confidence match (no match_score ≥ 0.7, or no confirmed verdict). Searches upstream fix commits (REST API + first-hand diff verdict: only confirmed/same_area returned) and openEuler mailing-list patch discussions (`patch_mails`: analysis rationale, stable-inclusion notes). Does NOT require RAG configuration. | `crash_features` (required, from analyze_crash), `query_text`, `max_mails` |
| `CrashFeatureMatcher:get_stats` | Crash statistics overview | *(not yet implemented)* |

---

## Data Models

The skill operates on two primary data shapes: **CrashIssue** (for known-issue matching, often populated from OSClinic) and **CommunityCase** (for openEuler/Linux community cases).

### CrashIssue (Known-Issue Format)

Used by `analyze_crash` and `query_knowledge`. Typically populated from the OSClinic platform via `scripts/import_from_osclinic.py`.

```json
{
  "source": "issue",
  "knowledge_id": "issue-general-protection-__inet_lookup_est-001",
  "fingerprints": [
    "general_protection::mlx5_core::__inet_lookup_established::0x16d"
  ],
  "bug_type": "general_protection",
  "bug_key": "general protection fault:",
  "bug_summary": "GPF in __inet_lookup_established via mlx5_core",
  "rip": "__inet_lookup_established+0x16d",
  "rip_function": "__inet_lookup_established",
  "rip_offset": "0x16d",
  "related_modules": ["mlx5_core"],
  "call_trace_signature": ["__inet_lookup_established", "__inet_lookup"],
  "call_trace_text": "raw call trace text...",
  "kernel_versions": ["5.10.0-136.71.0"],
  "affected_components": [],
  "root_cause": "root cause analysis",
  "solution": "solution description",
  "hotpatch": "hotpatch name",
  "history_wiki": "wiki link",
  "match_score": 0.95,
  "phenomenon": "",
  "source_url": "",
  "case_count": 47,
  "first_seen": "2024-01-01T00:00:00Z",
  "last_seen": "2024-06-01T00:00:00Z"
}
```

**Key fields for matching:**
- `fingerprints`: Unique crash signatures used for L1 exact matching.
- `bug_key`: Raw kernel output string (e.g., `general protection fault:`).
- `bug_type`: Normalized bug category.
- `rip_function`: Function at RIP, used for LIKE filtering in L2.
- `call_trace_signature`: Core functions in the call trace, used for semantic search.
- `kernel_versions`: Affected kernel versions (list).
- `root_cause` / `solution` / `hotpatch`: Human-readable repair guidance.

### CommunityCase (openEuler / Linux Community Format)

Used by `query_community_cases`. The raw JSON format from openEuler/Linux community ingestion is:

```json
{
  "id": "commit_0010b79d56cb1d7717bf146ee59df5a625b0330b",
  "source": "openEuler社区",
  "type": "commit",
  "title": "修复 ozwpan 驱动空指针解引用导致的内核崩溃",
  "kernel_version": "",
  "phenomenon": "When net_dev is NULL...",
  "root_cause": "Missing NULL check...",
  "solution": "Add NULL check before memcpy...",
  "source_file": "https://gitcode.com/openeuler/kernel/commits/detail/...",
  "content": "Summary of the commit...",
  "creattime": "2014-01-25T17:54:39+08:00"
}
```

**Key fields for retrieval:**
- `source`: Case origin (`openEuler社区` or `Linux社区`).
- `title`: Short description of the case.
- `kernel_version`: Affected kernel version (string). Used for logical filtering.
- `content`: Main body text. Used for fuzzy/semantic search.
- `phenomenon` / `root_cause` / `solution`: Structured details, also used for scoring.
- `source_file`: Link to the original issue/commit.

---

## Matching Engine

### CrashIssue Matching Flow

```
Input: CrashFeatures + HostFeatures
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ L1: Fingerprint Match                                 │
│   - Compute deterministic signature                   │
│   - Search crash_knowledge by fingerprint keyword     │
│   - Exact match → matched=true, score 0-100           │
└─────────────────────────────────────────────────────┘
         │ miss
         ▼
┌─────────────────────────────────────────────────────┐
│ L2: RAG-Driven Search                                 │
│   - Select strategy by bug_key pattern                │
│   - Query crash_knowledge with RAG                    │
│   - Local validation (rip_function, bug_type, etc.)   │
│   - Comprehensive score 0-100                           │
│   - score >= 60 → matched=true                          │
└─────────────────────────────────────────────────────┘
         │ miss
         ▼
┌─────────────────────────────────────────────────────┐
│ New Issue                                             │
│   - Build new CrashIssue from current crash           │
│   - matched=false                                     │
└─────────────────────────────────────────────────────┘
```

### L1 Fingerprint Match

For crash analysis, the skill first computes a deterministic fingerprint from `bug_type`, related modules, `rip_function`, and `rip_offset`:

```python
signature = f"{bug_type}::{related_module}::{rip_function}::{rip_offset}"
```

The L1 search config uses `fingerprints LIKE %signature%`. If a record's `fingerprints` list contains the exact signature, the crash is matched immediately (`fingerprint_match=True`). The matched issue is then scored with the same 0-100 algorithm used in L2 to provide a quality estimate.

### L2 RAG-Driven Search

If L1 fails, the skill builds a search config based on the `bug_key` pattern. Strategy selection is implemented in `l2_configs.py`:

| Bug Key Pattern | Strategy | Search Mode |
|-----------------|----------|-------------|
| NULL pointer / page fault / GPF / stack guard / NX / SMEP | `exact_rip_with_bugkey` | `rip_function LIKE` |
| hard LOCKUP / soft lockup | `fuzzy_rip_offset` | `rip_function LIKE` |
| invalid opcode | `exact_rip_with_bugkey` | `rip_function LIKE` |
| kernel BUG at | `match_bug_function` | `call_trace_top LIKE` |
| list_add/list_del corruption | `exact_rip_with_bugkey` | `rip_function LIKE` |
| Bad page / KASAN / KFENCE / RCU / hung task / double fault | `stack_similarity` | semantic search |
| fallback | `stack_similarity` | semantic search |

Local validation filters out false positives (e.g., `rip_function` must match for LIKE strategies). A final score ≥ 60 indicates a match.

### CrashIssue Matching Score (0-100)

The L2 (and L1 post-match) scoring uses the same **jieba + Jaccard + synonyms** approach as community retrieval:

| Factor | Score | Description |
|--------|-------|-------------|
| `bug_type` exact match | +20 | Same normalized bug category |
| `bug_key` Jaccard overlap | up to +10 | Overlap between raw bug_key strings |
| `rip_function` exact match | +20 | Function at RIP matches |
| `call_trace` Jaccard overlap | up to +15 | Overlap between call-trace function lists |
| `related_modules` overlap | up to +10 | Overlap between module lists |
| Content overlap (bug_summary + root_cause + solution + call_trace_text) | up to +15 | Jaccard overlap with extracted feature text |
| `kernel_version` match | up to +10 | Exact / prefix / major-version match |

**Stop threshold:** `score >= 60` is considered a match for L2. As with community retrieval, review the candidate content to confirm relevance.

### BugKey → BugType Mapping

| BugKey (kernel output) | BugType |
|------------------------|---------|
| `BUG: kernel NULL pointer dereference` | `null_pointer` |
| `BUG: unable to handle page fault for` | `page_fault` |
| `general protection fault:` | `general_protection` |
| `invalid opcode` | `invalid_opcode` |
| `kernel BUG at` | `kernel_bug` |
| `Watchdog detected hard LOCKUP` | `hard_lockup` |
| `watchdog: BUG: soft lockup` | `soft_lockup` |
| `BUG: stack guard page was hit` | `stack_overflow` |
| `double fault` | `double_fault` |
| `Kernel panic - not syncing:` | `panic` |
| `BUG: KASAN:` | `kasan` |
| `INFO: rcu_sched` | `rcu_stall` |
| `blocked for more than` | `hung_task` |
| `list_add corruption` / `list_del corruption` | `list_corruption` |

<details>
<summary>Full BugKey → BugType mapping</summary>

See `src/crash_matcher/bug_types.py:BUG_KEY_TO_TYPE` for the complete mapping.

</details>

---

## Community Retrieval Channels (rag_core / local grep)

社区案例有两条获取通道，可互为兜底，结果需合并去重：

1. **rag_core 语义检索（默认）**：`query_community_cases` 依赖 euler-copilot-rag（`[rag] base_url`）。按 `query_text` + `kernel_version` 走 L1/L2/L3 语义召回 + kernel_version 逻辑过滤 + 一手 diff verdict；RAG 未配置或无高置信命中时自动触发在线兜底（REST commits API + 邮件档案）。

2. **本地源文件 grep（RAG 不可用 / 命中不足时）**：社区邮件、会议纪要、上游 commit 在本机保留一份本地副本，目录由环境变量 `SHENNONG_COMMUNITY_DIR` 指定（默认 `/data/shennong/community/`，子目录 `mails/`、`meetings/`、`commits/`）。用 `rg`/`grep` 以 `rip_function`、`bug_key`、调用栈顶层函数、模块名、内核版本等关键词在本地源文件中检索，摘取「关键片段 + 原文网址 + commit 号」作为社区案例。

无论走哪条通道，每条社区案例 / 上游 commit 在报告里都需附：**原文网址（url）、关联 commit、关键片段（解释 + 原文）**。

## Community Retrieval Engine

### Retrieval Flow

```
Input: query_text + kernel_version
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ L1: Linux Community + openEuler Community             │
│   - kernel_version logical filter (like)              │
│   - top3 each                                         │
│   - score > 80 → stop, return top3                    │
└─────────────────────────────────────────────────────┘
         │ miss
         ▼
┌─────────────────────────────────────────────────────┐
│ L2: Secondary Confirmation                          │
│   - Re-score L1 results                             │
│   - score >= 80 or kernel exact + content overlap    │
│     → stop, return top3                              │
└─────────────────────────────────────────────────────┘
         │ miss
         ▼
┌─────────────────────────────────────────────────────┐
│ L3: Broader Recall (weak-match pool, l3_top_k > l1)  │
│   - Recall is a superset of L1; cases already scored │
│     in L1 reuse their score (no LLM re-scoring → no  │
│     non-deterministic score drift)                   │
│   - Newly recalled cases reaching the L2 confirm     │
│     threshold are PROMOTED to L2; only the rest stay │
│     L3 (weak matches, manual review required)        │
│   - A first-hand diff verdict of "confirmed" also    │
│     promotes an L3 case to L2                        │
│   - Rerank by score, return top_k_final              │
└─────────────────────────────────────────────────────┘
```

> **L3 confidence contract:** L3 is a *broader-recall candidate pool*, not a high-confidence verdict. An L3 case that is not confirmed by first-hand evidence (`verdict` = `unverified`/empty) is a weak lead: the report renders it as **"待核验 / 弱匹配"** regardless of its numeric score, and it must not be treated as a diagnosed root cause. Strong evidence (score reaching the L2 threshold, or `verdict=confirmed`) always promotes the case to L2 — so a genuine L3 card by definition carries no high-confidence label.

### Scoring Rules (0-100)

The scoring function uses **jieba** for Chinese tokenization, **Jaccard similarity** for overlap measurement, and **synonyms** for query-term expansion. English alphanumeric tokens are preserved as-is.

| Factor | Score | Description |
|--------|-------|-------------|
| Exact `kernel_version` match | +30 | Query kernel version exactly equals case kernel version |
| `kernel_version` prefix match | +20 | One version is a prefix of the other (e.g., `4.19` vs `4.19.90`) |
| `kernel_version` major-version match | +15 | Same major version (e.g., `4.19.x` vs `4.19.y`) |
| Title Jaccard overlap | up to +25 | Jaccard similarity between query terms and title terms × 25 |
| Content/phenomenon/root_cause Jaccard overlap | up to +25 | Jaccard similarity between query terms and body terms × 25 |
| Exact English/technical token matches | up to +25 | Function/module names matched exactly (e.g., `boomerang_start_xmit`, `3c59x`) |
| Case has solution | +10 | A solution is present |

**Stop thresholds (guidelines):**
- L1: `score > 80` stops automatically.
- Secondary confirmation: `score >= 60` AND (kernel exact match OR title/content overlap OR multiple exact English tokens match).

> **Important**: The returned score is a retrieval guideline, not a definitive verdict. Always review the top candidates and verify that the content (title, phenomenon, root cause, solution) actually matches the query. If a high-scoring candidate's content is clearly relevant, adopt it even if the score is slightly below the 80 threshold.

### Term Extraction

To support both Chinese and English queries, the scoring function extracts:
- **Chinese tokens** using `jieba` segmentation.
- **English/technical tokens** (e.g., `boomerang_start_xmit`, `3c59x`, `pci_map_single`) preserved as-is.
- **Synonym expansion** for Chinese terms using the `synonyms` package, with a high threshold to avoid noise.

This supports mixed-language queries such as `KVM e500 find_linux_pte 中断 主机挂起` against both English-dominant Linux records and Chinese-dominant openEuler records.

### Query Text Guidelines

社区知识库以中文内容为主，但 RAG 语义检索引擎（`text-embedding-v4`）和
`exact_token_score` 评分均对英文技术词更友好。为避免中英文不匹配导致的低分问题，
**`query_text` 必须遵循以下构造规则**：

#### 1. 词汇构成

最优模板：
```
{bug_type_en} {function_or_module} {key_en_terms} {key_cn_terms}
```

| 成分 | 示例 | 必要程度 | 作用 |
|---|---|---|---|
| `bug_type_en` | `NULL pointer dereference`, `page_fault`, `use-after-free` | **必选** | RAG 语义锚点 + exact_token_score (25分) |
| `function_or_module` | `shrink_folio_list`, `ext4`, `vmxnet3` | **强烈建议** | exact_token_score + 精度锚点 |
| `key_en_terms` | `kasan`, `lru`, `unevictable`, `jbd2` | 建议 | RAG 补充信号 + exact_token_score |
| `key_cn_terms` | `空指针解引用`, `缺页异常`, `内存回收` | 可选 | Title Jaccard (25分) |

#### 2. 正确 vs 错误示例

| 场景 | ✅ 好的 query | ❌ 差的 query | 说明 |
|---|---|---|---|
| 空指针崩溃 | `NULL pointer dereference ext4` | `内核空指针解引用错误导致系统崩溃` | 中文自然句 jieba 分词后停用词过多 |
| 缺页崩溃 | `page_fault shrink_folio_list 缺页异常 lru` | `shrink_folio_list` | 单个函数名过于稀疏 |
| UAF 漏洞 | `use-after-free kasan freed 释放后使用` | `释放后使用 已释放内存 访问 导致 内核崩溃` | `导致`/`访问` 为停用词，白白消耗 token |
| 死锁 | `deadlock 死锁 softlockup` | `系统发生死锁导致CPU软锁死系统无响应` | 超过 10 词，稀释 RAG 向量 |
| ext4 故障 | `ext4 inode bug_on crash journal` | `ext4文件系统inode日志损坏导致内核BUG_ON崩溃` | 完整句子不如关键词堆叠 |

#### 3. 长度与密度

- **4-8 词最佳**，超过 10 词会稀释 RAG 向量精度和 Jaccard 分数
- 自然语言描述句（如 `内核在处理页错误时发生空指针解引用`）的 Jaccard 得分显著低于关键词堆叠
- **英文技术词占 60% 以上**，中文关键词用作辅助而非主力

#### 4. 无效词（已过滤，加了无效）

以下词在 jieba 停用词表中，加入 query 不产生任何效果：

`修复` `导致` `触发` `发生` `系统` `进程` `内核` `模块` `驱动` `文件` `设备` `信息` `数据` `代码` `调用` `函数` `指针` `地址` `内存` `错误` `失败` `异常` `崩溃` `挂起` `死机` `重启`

### Inspecting Upstream Evidence Manually

**Do NOT `git clone`, `git ls-remote`, or download kernel repositories** when looking for upstream fixes. A kernel repository is hundreds of MB to GB; the REST CLI below fetches only the needed JSON/text over HTTPS and is orders of magnitude faster. This prohibition applies to delegated subagents/General Tasks as well.

`query_community_cases` automatically fetches first-hand upstream evidence (diff / commit message / issue body) for top cases and computes a code-level verdict. When a case is `unverified` (the original text could not be fetched) or `same_area` (needs confirmation that it is the same subsystem but a different bug), re-inspect the concrete commit/issue with the bundled CLI (it reuses `git_commit_fetcher`'s anonymous-first fetch strategy):

```bash
# Search upstream fix commits WITHOUT cloning: list commits touching a file
# whose message contains the keyword(s), newest first (per_page=100 per page).
bash run_python.sh scripts/fetch_commit.py search openeuler/kernel \
  net/netfilter/nf_tables_api.c verdict nf_tables
#   -> JSON array of {sha, html_url, date, author, message}; then verify a hit:

# Raw commit diff
bash run_python.sh scripts/fetch_commit.py diff "https://gitcode.com/openeuler/kernel/commit/<sha>"

# Commit metadata (message / author / additions / deletions)
bash run_python.sh scripts/fetch_commit.py detail "https://gitcode.com/openeuler/kernel/commit/<sha>"

# Issue / PR body
bash run_python.sh scripts/fetch_commit.py issue "https://gitcode.com/openeuler/kernel/issues/<number>"
```

Typical flow when `query_community_cases` returns nothing: derive the crashing file path from the RIP function's subsystem (e.g. `nft_verdict_init` → `net/netfilter/nf_tables_api.c`), run `search <repo> <path> <bug keywords>` to find candidate fix commits, then `diff <html_url>` to confirm the patch modifies the crashing function. All over HTTPS, no clone.

The output is the same upstream source that the automatic verdict analysis consumes, so it can confirm or exclude a candidate before it is written into the root-cause conclusion.
---

## Knowledge Base

Uses the euler-copilot-rag service.

| KB | kb_id | Content |
|----|-------|---------|
| `crash_knowledge` | `c3a9bc93-9244-432e-9d9e-5355ed8d0fb7` | Known crash patterns (`source="issue"`), typically imported from OSClinic |
| `crash_cases` | *(same as crash_knowledge)* | Per-crash case records (`source="case"`) |
| `openeuler_community_cases` | `534ffa02-3575-4995-bf16-6e5c51191d46` | openEuler community cases (`source="openEuler社区"`) |
| `linux_community_cases` | *(not configured)* | Linux community cases (`source="Linux社区"`) |

### Populating OSClinic Data

Production OSClinic data is imported into `crash_knowledge` via `scripts/import_from_osclinic.py`:

```bash
export OSCLINIC_TOKEN="your_token"
export RAG_BASE_URL="http://localhost:9988"
# Run from the project root directory
PYTHONPATH=src python3 scripts/import_from_osclinic.py
```

---

## Examples

### Example 1: Community L1 High-Score Match

```bash
python3 -m crash_matcher.cli query-community \
  -q "3c59x 网卡 boomerang_start_xmit page_address pci_map_single" \
  -k "2.6.32-491.el6"
```

Expected output:
```
matched: True
stop_reason: L1 社区案例命中高分(>80)
top cases:
  1. [L1] score=83.6 source=openEuler社区
     title: 3c59x网卡驱动修复boomerang_start_xmit中的内核崩溃
```

### Example 2: Community L3 Fallback Without Kernel Version

```bash
python3 -m crash_matcher.cli query-community \
  -q "空指针解引用 内核崩溃"
```

Expected output: community cases from Linux/openEuler with stop reason `L3 Linux社区 + openEuler社区 扩大召回（弱匹配，需人工核验）`. These cases carry `match_level=L3` and are weak leads — the report renders them as "待核验" unless a new case reached the L2 threshold (promoted, stop reason mentions `提升为 L2`) or first-hand verification returned `confirmed`.

### Example 3: No Community Match

If the query only matches OSClinic-known issues (now stored in `crash_knowledge`), community retrieval may return no candidates. In that case, use `analyze_crash` or `query_knowledge` to search the known-issue KB.

---

## Testing

### Automated Test Script

```bash
# Run from the project root directory
python3 scripts/test_community_retrieval.py
```

### CLI Test

```bash
export PYTHONPATH=src
python3 -m crash_matcher.cli query-community \
  -q "空指针解引用 内核崩溃"
```

### MCP Test

Ensure euler-copilot-rag is running on `http://localhost:9988` and call:

```json
{
  "tool": "CrashFeatureMatcher:query_community_cases",
  "arguments": {
    "query_text": "空指针解引用 内核崩溃",
    "kernel_version": ""
  }
}
```

---

## Notes

1. MCP mode requires euler-copilot-rag running on port 9988. If RAG is not configured, `analyze_crash` returns `{"error": "RAG knowledge base not configured"}`. Shennong should fall back to log analysis when this occurs.
2. vmcore analysis requires the `crash` tool and a matching `vmlinux`.
3. OSClinic data import populates `crash_knowledge` via `scripts/import_from_osclinic.py` and is used by `analyze_crash` / `query_knowledge`, not by community retrieval.
4. L1 fingerprint matching is tried first; L2 bug_key-driven search runs only on L1 miss.
5. Case association only triggers when `matched=true` and the known issue has no solution yet.
6. Community retrieval uses custom scoring (0-100) because the current RAG API does not return raw similarity scores.
7. Chinese queries are tokenized using jieba; English/technical tokens are preserved as-is. This supports mixed-language retrieval.

