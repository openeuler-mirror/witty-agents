# optimize-wiki

## 触发条件

当满足以下任一条件时触发本能力：

- `eval-wiki` 质量评估发现 Wiki 存在缺陷（内容过时、描述不清、关键词不准确、召回失败等）。
- 用户明确提出"优化这个 Wiki"、"更新知识文档"、"改进 XX Wiki"等意图。
- 定期维护存量 Wiki，检查并修复过时内容、补充缺失信息。
- 参考资料有更新，需要同步更新对应 Wiki 的内容。

## 执行流程

### 第一步：定位目标 Wiki

通过 `find-wiki` 或 `list-experiences` 定位待优化的 Wiki：

```bash
# 按名称搜索
cd scripts
uv run experience-skill search-experiences \
    --query "<Wiki 名称或关键词>" \
    --type WIKI \
    --top-k 5

# 或浏览全量列表
uv run experience-skill list-experiences --type WIKI
```

记录目标 Wiki 的 ID（如 `a1b2c3d4-...`）和 source 路径。

### 第二步：读取现状 & 分析问题

读取 Wiki 源文件，梳理优化点：

```bash
cat <data/wiki_hub/目标Wiki.md>
```

常见优化维度：

| 维度 | 典型问题 | 优化方向 |
| ---- | ------- | ------- |
| **准确性** | 内容与实际不符、关键数据有误 | 交叉验证后修正为正确信息 |
| **完整性** | 缺少关键知识点、覆盖范围不足 | 补充遗漏内容，扩展覆盖范围 |
| **可读性** | 描述不清、结构混乱、格式不规范 | 重写模糊段落，统一格式，优化标题层级 |
| **时效性** | 引用的版本/API/命令已过时 | 更新为当前有效版本和做法 |
| **关键词** | 标签不准确、遗漏核心关键词导致召回失败 | 补充精准关键词 |
| **召回** | 查询无法召回该 Wiki | 优化 description 和 keywords，提升 FTS5 匹配度 |
| **参考资料** | YAML header 中 references 缺失或不完整 | 补充原始资料来源信息 |

### 第三步：执行优化

根据问题分析结果，逐项改进：

#### 3a. 更新 Wiki Markdown 文件

直接编辑 `data/wiki_hub/<Wiki 文件名>.md`：

- 修正 YAML front matter 中的 `name`、`description`（如有变更）。
- 更新 `keywords` 列表，补充遗漏、删除无关标签。
- 更新 `references`，补充或修正资料来源信息。
- 修正、补充、重写 Markdown 正文内容。

#### 3b. 添加变更记录（推荐）

在 YAML front matter 中添加变更日志注释：

```yaml
---
name: "<Wiki 名称>"
description: "..."
keywords: [...]
# 变更记录
# v1.1 (2024-01-15): 修正 API 版本号，补充错误处理示例
# v1.0 (2024-01-01): 初始版本
---
```

#### 3c. 同步 DB 元信息

调用 Service 层 `optimize_experience()` 方法，将修改后的元信息同步到 SQLite：

```python
from service.experience_service import ExperienceService

updated = ExperienceService.optimize_experience(
    experience_id="<Wiki ID>",
    name="<新名称，不需要改则传 None>",
    description="<新描述，不需要改则传 None>",
    keywords=["<新关键词列表>"],
)
```

此方法会自动：

- 更新 `experience_table` 中对应记录的 name / description（触发 FTS 索引更新）。
- 若传入 keywords，全量替换 `keyword_table` 中该 Wiki 的关键词（先删后插）。
- 更新 `updated_at` 时间戳。

**注意**：`optimize_experience()` 仅同步 DB 元信息，不修改 `data/wiki_hub/` 下的源 `.md` 文件。因此应先修改源文件，再调用此方法同步 DB。

### 第四步：验证

```bash
# 确认 DB 记录已更新
uv run experience-skill list-experiences --type WIKI --name "<Wiki 名称>"

# 确认优化后的 Wiki 可被检索召回
uv run experience-skill search-experiences \
    --query "<优化后的核心关键词>" \
    --type WIKI \
    --top-k 5

# 确认源文件内容已更新
cat <data/wiki_hub/优化后的Wiki.md>
```

## 优化原则

1. **增量改进**：只修改有问题的部分，不推翻重写已验证正确的内容。
2. **源文件优先**：先修改 `data/wiki_hub/` 下的 `.md` 源文件，再同步 DB 元信息，确保两者一致。
3. **测评闭环**：优化后应在评估环节重新验证（eval-wiki），形成"评估 → 优化 → 再评估"的闭环。
4. **记录变更**：复杂优化建议在 YAML front matter 中添加变更日志注释，方便回溯。
5. **保留来源**：内容修改后务必检查正文末尾参考资料是否仍准确对应，必要时更新来源信息。

## 针对召回失败的专项优化

若 `eval-wiki` 发现 Wiki 召回失败，按以下优先级优化：

1. **优化 description**：确保 description 包含核心关键词和典型查询语句，增强 FTS5 全文匹配度。
2. **补充 keywords**：添加高频查询词、领域术语、中英文同义词。
3. **优化 name**：名称应包含最核心的领域关键词，避免过于抽象。
4. **重新入库**：若修改了源文件，需重新调用 `optimize_experience()` 同步 DB 以触发 FTS 索引更新。

## 错误处理

- 若 experience_id 不存在或已删除，抛出 `ValueError`。
- 若 `.md` 文件被外部修改但 DB 未同步，先手动确认文件内容，再调用 optimize 同步。
- keywords 传入 `None` 表示不修改关键词；传入空列表 `[]` 会清空所有关键词。
- 修改 `.md` 文件时注意保留 YAML front matter 语法正确性，避免缩进混乱导致解析失败。
