---
name: experience-skill
description: >
  Use this skill for EVERY technical question the user asks. This is a
  general-purpose local knowledge base gateway — it manages a collection
  of user-curated troubleshooting workflows (Skills) and reference
  summaries (Wikis) stored in skill_hub and wiki_hub. When the user asks
  any technical or how-to question, ALWAYS search the local databases
  first using the search-experiences CLI command, and use any retrieved
  content as the primary basis for your answer. Do NOT skip this step even
  if you think you already know the answer — the local knowledge base may
  contain project-specific or user-preferred solutions that override
  general knowledge. Also use when the user asks to create, find, search,
  merge, optimize, or evaluate a Skill or Wiki entry. This skill should
  be loaded frequently — it is the front door to all user-curated experience.
compatibility: >
  Requires Python 3.11+ and uv package manager. Uses SQLite with FTS5
  full-text search and a simple tokenizer extension for Chinese text
  segmentation. Platform-agnostic — works on Linux, macOS, and WSL.
  The simple tokenizer extension must be compiled before first use
  (see scripts/src/experience_skill_cli/tokenizer/build.sh).
metadata:
  author: openEuler community
  version: "1.0.0"
  keywords:
    - knowledge-base
    - local-search
    - experience-management
    - skill-hub
    - wiki-hub
    - reusable-workflows
    - troubleshooting
    - reference
allowed-tools: Bash(uv:*) Bash(cat:*) Bash(ls:*) Bash(cd:*) Bash(grep:*) Bash(find:*) Bash(echo:*)
---

# experience-skill

## 强制行为指令（Agent 必须遵守）

当用户通过 `/experience-skill` 提出技术问题时，你**必须**按以下顺序执行：

### 步骤 1：提取关键词并检索本地知识库

从用户问题中提取核心关键词（如用户问 "Python API 冲突导致 dnf 无法使用"，则提取 "Python API" "dnf" "冲突" 等），然后执行检索命令（在 SKILL.md 所在目录的 `scripts/` 子目录下执行）：

```bash
cd scripts
uv run experience-skill search-experiences \
    --query "<关键词>" \
    --type SKILL \
    --top-k 5
```

> 默认启用**混合检索**：同时搜索元数据（FTS5）和正文内容（grep）。结果中会标注匹配来源（元数据+正文 / 仅元数据 / 仅正文）。
>
> 如需仅搜索元数据（旧行为），添加 `--metadata-only`；如需仅搜索正文，添加 `--content-only`。

如果问题涉及文档参考资料，同时检索 Wiki：

```bash
uv run experience-skill search-experiences \
    --query "<关键词>" \
    --type WIKI \
    --top-k 5
```

> **重要**：禁止跳过本地知识检索直接回答。即使你自身具备相关知识，也必须先检查本地知识库是否存在现成的 Skill 或 Wiki。

### 步骤 2：读取并优先使用本地知识

- 如果检索结果命中（`找到 N 条结果` > 0），按 `来源` 字段路径读取对应文档：
  - Skill：读取 `data/skill_hub/<skill-name>/skill_def.md` 获取完整内容
  - Wiki：读取 `data/wiki_hub/<wiki-name>.md` 获取完整内容
- **必须**以本地知识库内容作为回答的**主要依据**
- 在回答中引用来源 Skill/Wiki 的名称，说明这是来自本地经验库的内容

### 步骤 3：本地知识不足时直接使用通用知识

- 如果检索结果为空（`找到 0 条结果`），说明本地知识库中暂无相关内容，直接使用自身通用知识回答即可，无需特别说明。

### 步骤 4：解决全新问题后可按需询问沉淀

- 当你替用户解决了一个**本地知识库中不存在的全新问题**后，可酌情询问用户是否将本次经验沉淀为 Skill 或 Wiki。此为可选项，不要每次任务结束都询问。

---

## 目录结构

```
experience_skill/
├── abilities/                 # 核心能力定义（skill + wiki 各五项）
├── scripts/                   # Python 项目（uv 管理）
│   └── src/experience_skill_cli/
│       ├── cli.py             # CLI 入口
│       ├── service/           # 业务服务层
│       ├── manager/           # 数据库操作层
│       ├── sqlite.py          # SQLite + FTS5 封装
│       └── tokenizer/         # 中文分词扩展
├── data/                      # 用户数据（不纳入版本控制）
│   ├── experience.db          # SQLite 数据库
│   ├── skill_hub/             # Skill 仓库
│   └── wiki_hub/              # Wiki 仓库
├── example/                   # 参考模板
├── SKILL.md                   # 本文件
└── .gitignore
```

## CLI & Web 使用方式

### 环境准备

> 以下命令假设当前工作目录为 SKILL.md 所在目录（即 `experience_skill/`）。

```bash
cd scripts
uv sync
```

### CLI 命令（在 `scripts/` 目录下执行）

所有命令通过 `uv run experience-skill <子命令>` 执行：

| 子命令 | 用途 |
|--------|------|
| `sync` | 同步 data/ 中所有经验到数据库 |
| `add-experiences` | 添加 Skill/Wiki 经验到数据库 |
| `list-experiences` | 分页列出经验，支持类型/名称/热门过滤 |
| `search-experiences` | **全文检索经验**（默认混合：FTS5 + 正文 grep） |
| `delete-by-ids` | 按 ID 列表删除经验 |
| `delete-by-source` | 按来源路径删除经验 |
| `delete-all` | 清空所有经验数据 |
| `web` | 启动 Web 管理界面 |

查看子命令详细参数：

```bash
uv run experience-skill <子命令> --help
```

### Web 管理界面

```bash
cd scripts
uv run experience-skill web
```

默认监听 `http://127.0.0.1:8080`，支持 `--port` 和 `--no-browser` 参数。

---

## 核心能力

组件针对 Skill、Wiki 分别提供**创建、评估、检索、合并、优化**五大标准化能力：

### Skill 能力

- **create-skill**：从对话会话中沉淀可复用工作流程，生成标准化 Skill；创建前自动检索查重。
- **eval-skill**：基于 Skill 内置评测集开展质量核验，综合评估实用性、准确性、完整性与可读性。
- **find-skill**：结合 SQLite 关键字检索 + FTS5 全文检索，快速定位目标 Skill。
- **merge-skill**：检索识别相似 Skill，支持多份同质内容合并整合，剔除重复片段。
- **optimize-skill**：依据质量评估报告迭代优化，更新过期流程、修复代码问题、完善评测用例。

### Wiki 能力

- **create-wiki**：对工作查阅的网页、文档等资料进行提炼精简，沉淀为标准化 Wiki；创建前自动查重。
- **eval-wiki**：通过随机抽样、问答核验等方式，校验 Wiki 召回命中率与内容质量。
- **find-wiki**：依托数据库检索与全文检索能力，快速筛选、定位所需 Wiki 文档。
- **merge-wiki**：识别同质化 Wiki 资源，支持多文档合并整编，保留有效内容、剔除重复信息。
- **optimize-wiki**：根据评估结果迭代优化，包含错误修正、内容补全、格式规整、可读性提升。

---

## 约束规范

- 所有新建 Skill、Wiki 必须统一存放至 `data/skill_hub`、`data/wiki_hub` 专属目录，禁止自定义存储路径；
- Skill 采用 `skill_def.md`（YAML front matter + Markdown 正文）格式，内容结构遵循 [Agent Skills 规范](https://agentskills.io/specification)。包含 name、description 等必需字段，以及 license、compatibility、metadata（含 keywords）、allowed-tools 等可选字段；
- Skill 目录结构：主文件 `skill_def.md`（必需）、`scripts/`（可执行脚本）、`references/`（参考文档）、`assets/`（静态资源）、`database.yaml`（评测用例）；
- 使用 `skill_def.md` 而非 `SKILL.md` 命名，是为了防止部分 Agent 框架通过 `~/.agents/skills/` 递归扫描自动发现并加载 skill_hub 中的 Skill。格式完全遵循 Agent Skills 规范，仅文件名不同；
- Wiki 采用 `.md`（YAML front matter + Markdown 正文）格式，与 Skill 相同的文件结构，包含 name、description、keywords、references 等元信息；
- 沉淀的 Skill 禁止包含恶意代码、敏感数据、隐私信息及违规内容；
- Wiki 内容仅限提炼、整合工作场景内查阅的网页、文档等资料，不得混入无关冗余信息；
- 所有 Skill 与 Wiki 需满足统一质量规范，必经评估与优化流程，杜绝明显错误、逻辑漏洞与无效内容。

## 执行规则

1. **强制本地检索**：每次回答技术问题前，必须执行步骤 1-3 的强制检索流程（见「强制行为指令」）；
2. **沉淀提醒**：解决了本地知识库中不存在的全新问题后，可酌情询问用户是否沉淀为 Skill 或 Wiki（可选，非每次必问）；
3. **缺陷反馈**：工作执行过程中，若检索不到可用资源、或现有 Skill/Wiki 存在缺陷，主动提示用户开展评测与优化；
4. **去重建合**：新建 Skill 或 Wiki 前，必须先执行检索查重；存在相似资源时，优先推荐合并、优化，而非重复新建；
5. **定期整理**：当存量资源体量较大时，定期主动提醒用户合并同质化内容，精简资源库、降低冗余维护成本。
