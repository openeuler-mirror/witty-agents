# create-wiki

## 触发条件

当用户明确提出"沉淀为 Wiki"、"保存为知识文档"、"记录参考资料"等意图，或智能体完成资料查阅、文档学习等任务后主动询问是否沉淀时，触发本能力。

## 前置约束

- 所有新建 Wiki 必须存放至 `data/wiki_hub/` 目录下，以 `.md` 文件形式组织，文件名使用 Wiki 名称的英文/拼音缩写。
- Wiki 文件采用 **YAML front matter + Markdown 正文** 格式（与 Skill 的 skill_def.md 格式一致），YAML 头部包含 `name`、`description`、`keywords` 等元信息，正文为 Markdown 内容。
- Wiki 内容仅限提炼、整合工作场景内查阅的网页、文档等资料，禁止混入无关冗余信息。
- 禁止在 Wiki 内容中包含敏感数据、隐私信息及违规内容。

## 执行流程

### 第一步：检索查重

在创建新 Wiki 之前，必须先执行检索查重，避免重复建设。

1. 使用 CLI 搜索现有 Wiki：

   ```bash
   cd scripts
   uv run experience-skill search-experiences \
       --query "<待创建 Wiki 的核心关键词>" \
       --type WIKI \
       --top-k 5
   ```

2. 若搜索结果中存在高度相似（名称相近、关键词重叠、描述雷同）的 Wiki，应：
   - **优先推荐合并（merge-wiki）**：告知用户存量资源情况，建议执行合并而非新建。
   - **其次推荐优化（optimize-wiki）**：若存量 Wiki 内容过时或质量不佳，建议以优化方式更新。
   - 仅当用户明确坚持新建且存量不构成冗余时，才继续创建流程。

### 第二步：生成 Wiki Markdown 文件

若查重通过（无相似 Wiki 或用户确认新建），按以下规范生成 `.md` 文件（YAML front matter + Markdown 正文，与 skill_def.md 格式一致）：

1. **YAML front matter**（必须包含，仅 header 中的字段会存入数据库用于检索）：

   ```yaml
   ---
   name: "<Wiki 名称>"
   description: "<一句话描述 Wiki 涵盖的知识领域、来源和用途>"
   keywords:
     - 关键词1
     - 关键词2
     - 关键词3
   references:
     - name: "<资料名称>"
       type: online          # online 或 offline
       source: "<URL 或文档 ID>"
   ---
   ```

2. **Markdown 正文**（正文不存入数据库，仅供检索命中后按 source 路径读取使用）：

   ```markdown
   # <Wiki 标题>

   ## 简介
   <Wiki 内容的简要概述>

   ## 核心内容
   <提炼精简后的核心知识，使用标题、列表、表格等格式组织>

   ## 参考资料
   - [《资料名称》](URL)（在线/离线）
   ```

3. **编写规范**：
   - `name`：用中文简明扼要命名，体现核心主题。
   - `description`：说明 Wiki 覆盖的知识领域、原始资料来源和适用场景，用中文撰写。**此字段会被 FTS5 全文索引，是检索命中的关键**。
   - `keywords`：选取 3-8 个最能代表 Wiki 内容的关键词，用于关键字过滤检索。
   - `references`：记录所有参考资料的来源信息（名称、类型、URL/ID），便于溯源。
   - 正文：对原始资料进行提炼精简后的核心内容，使用 Markdown 格式编写。正文不被索引，仅在检索命中后供阅读使用。

### 第三步：保存到 wiki_hub

将生成的 Markdown 文件保存到 `data/wiki_hub/` 目录下：

```bash
# 文件命名示例：{主题英文缩写}.md
# 如：python-async-guide.md、k8s-deploy-best-practice.md
```

### 第四步：注册入库

将 Wiki 文件注册到 SQLite 经验库：

```bash
cd scripts
uv run experience-skill add-experiences \
    --type WIKI \
    --source "<wiki_hub 下的 .md 文件绝对路径>"
```

此命令会：

- 读取 `.md` 文件的 YAML front matter，提取 `name`、`description`、`keywords`、`references` 写入 `experience_table`。
- Markdown 正文**不会**存入数据库，检索命中后通过 source 路径读取完整文件。
- 检索时仅基于 `name`、`description`（FTS5 全文索引）、`keywords`（keyword_table）进行匹配。
- 检查 source 路径是否已存在（防重复）。

### 第五步：验证

注册成功后，执行一次检索验证 Wiki 可被召回：

```bash
uv run experience-skill search-experiences \
    --query "<Wiki 核心关键词>" \
    --type WIKI \
    --top-k 3
```

确认新创建的 Wiki 出现在搜索结果中。

## 内容提炼原则

1. **去粗取精**：从原始资料中提取核心观点、关键数据和可操作结论，舍弃背景铺垫和无关细节。
2. **结构重组**：按逻辑层次重新组织内容，使用标题、列表、表格等格式增强可读性。
3. **标注来源**：关键数据、引用观点须在 `references` 中标注出处，确保可溯源。
4. **保持中立**：客观记录资料内容，区分"资料观点"与"个人理解"。
5. **控制篇幅**：单个 Wiki 内容建议控制在 500-3000 字，过长考虑拆分，过短考虑合并。

## 错误处理

- 若 `.md` 文件不存在于 source 路径，CLI 会报 `FileNotFoundError`，需检查路径。
- 若 source 路径已注册过，CLI 会报 `ValueError`，需更换路径或先删除旧记录。
- 若 `.md` 文件的 YAML front matter 格式不符合规范（缺少必填字段），注册仍会成功但元信息可能为空。
- 若 simple tokenizer 扩展未编译，需先执行 `bash scripts/src/experience_skill_cli/tokenizer/build.sh`。
