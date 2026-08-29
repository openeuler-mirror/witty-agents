# merge-wiki

## 触发条件

当满足以下任一条件时触发本能力：

- `create-wiki` 查重阶段发现高度相似 Wiki，用户选择合并而非重复新建。
- 用户明确提出"合并这些 Wiki"、"整合重复知识文档"等意图。
- 存量 Wiki 体量较大时，主动提醒用户合并同质化内容。
- `eval-wiki` 评估发现多处内容重叠，建议合并精简。

## 执行流程

### 第一步：检索相似 Wiki

使用 `find-wiki` 能力检索与目标 Wiki 相似的存量资源：

```bash
cd scripts
uv run experience-skill search-experiences \
    --query "<待合并 Wiki 的核心关键词>" \
    --type WIKI \
    --top-k 10
```

从结果中筛选出名称相近、关键词重叠、描述雷同的 Wiki，作为合并候选列表。

### 第二步：确定合并策略

将候选 Wiki 列表呈现给用户，商定合并方向：

1. **指定 base（保留目标）**：从候选中选出一个作为合并基底，其余作为被合并源。
2. **确认合并范围**：明确哪些 Wiki ID 将并入 base，哪些保留不动。
3. **确认元数据合并规则**：
   - **名称**：base 名称后追加 `（合并自：name1, name2, ...）` 标记。
   - **描述**：所有 Wiki 的描述用 `---` 分隔线拼接合并。
   - **关键词**：所有 Wiki 的关键词取并集去重。
   - **参考资料**：所有 Wiki 的 references 取并集去重。

### 第三步：执行 DB 层合并

调用 Service 层 `merge_experiences()` 方法：

```python
from ENUM.exprience import ExperienceType
from service.experience_service import ExperienceService

merged = ExperienceService.merge_experiences(
    experience_type=ExperienceType.WIKI,
    base_id="<保留的 Wiki ID>",
    merge_ids=["<被合并 Wiki ID 1>", "<被合并 Wiki ID 2>", ...],
)
```

此方法会自动：

- 校验所有 ID 存在且类型一致。
- 合并 name / description / keywords 到 base。
- 更新 base 的 DB 记录和 FTS 索引。
- 将被合并的 Wiki 软删除（status → deleted）。

### 第四步：整合源文件内容

合并仅影响 DB 中的元信息，**不会自动修改 `data/wiki_hub/` 下的 `.md` 源文件**。合并完成后需手动或由智能体：

1. **整合正文**：读取所有被合并 Wiki 的 `.md` 文件，将其 Markdown 正文内容整合到 base 的 `.md` 文件中：
   - 按主题重新组织内容结构，用标题区分不同来源。
   - 去除重复段落，保留互补信息。
   - 统一格式风格。

2. **更新 YAML front matter**：更新 base `.md` 文件的 YAML header 中的 `name`、`description`、`keywords`、`references`，反映合并结果。

3. **添加合并记录**：在 base `.md` 文件的 YAML front matter 中添加合并记录：

   ```yaml
   ---
   name: "<合并后的名称>"
   description: "<合并后的描述>"
   keywords: [...]
   # 合并记录
   # 合并时间：<YYYY-MM-DD>
   # 合并自：<source1.md>, <source2.md>
   ---
   ```

4. **归档或删除**：将被合并的 `.md` 文件移动到归档目录或直接删除。

### 第五步：验证

```bash
# 确认 base Wiki 信息已更新
uv run experience-skill list-experiences --type WIKI --name "<合并后的名称>"

# 确认被合并 Wiki 已软删除（不再出现在正常列表）
uv run experience-skill search-experiences --query "<被合并 Wiki 名>" --type WIKI

# 确认合并后的 Wiki 可正常检索
uv run experience-skill search-experiences \
    --query "<合并后 Wiki 的关键词>" \
    --type WIKI \
    --top-k 5
```

## 合并规则细节

| 字段 | 合并行为 |
| ---- | ------- |
| name | `{base.name}（合并自：{src1.name}, {src2.name}）` |
| description | 各 Wiki 描述以 `\n---\n` 分隔拼接，经特殊字符清洗后入库 |
| keywords | 所有 Wiki 关键词取并集去重 |
| references | 所有 Wiki 参考资料取并集去重 |
| 正文 | 按主题整合，去除重复，保留互补内容 |
| source | 保持 base 的 source 不变 |
| is_hot | 保持 base 的 is_hot 不变 |
| status | base 不变；被合并 Wiki 标记为 deleted |

## 内容整合原则

1. **主题聚合**：将相同子主题的内容归并到同一段落/章节下。
2. **去重优先**：完全相同的信息只保留一份；高度相似的信息保留表述更清晰的那份。
3. **互补保留**：不同 Wiki 提供不同角度的信息时，两者都保留并用标题区分。
4. **冲突处理**：内容存在矛盾时，优先信任有参考资料溯源的一方；无法裁决时保留多方观点并标注。
5. **篇幅控制**：合并后正文过长时，考虑拆分而非强行塞入单一 Wiki。

## 错误处理

- 若 base_id 不在 merge_ids 中且不存在于 DB，抛出 `ValueError`。
- 若任何 merge_ids 不存在或已删除，抛出 `ValueError`。
- 若 base 或 merge 目标的 type 不是 WIKI，抛出 `ValueError`。
- 合并失败时所有 DB 操作自动回滚（SQLite 事务保证）。
- 文件整合操作需人工确认，不在 Service 层自动执行。
