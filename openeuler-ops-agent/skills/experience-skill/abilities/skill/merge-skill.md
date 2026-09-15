# merge-skill

## 触发条件

当满足以下任一条件时触发本能力：

- `create-skill` 查重阶段发现高度相似 Skill，用户选择合并而非重复新建。
- 用户明确提出"合并这些 Skill"、"整合重复技能"等意图。
- 存量 Skill 体量较大时，主动提醒用户合并同质化内容。

## 执行流程

### 第一步：检索相似 Skill

使用 `find-skill` 能力检索与目标 Skill 相似的存量资源：

```bash
cd scripts
uv run experience-skill search-experiences \
    --query "<待合并 Skill 的核心关键词>" \
    --type SKILL \
    --top-k 10
```

从结果中筛选出名称相近、关键词重叠、描述雷同的 Skill，作为合并候选列表。

### 第二步：确定合并策略

将候选 Skill 列表呈现给用户，商定合并方向：

1. **指定 base（保留目标）**：从候选中选出一个作为合并基底，其余作为被合并源。
2. **确认合并范围**：明确哪些 Skill ID 将并入 base，哪些保留不动。
3. **确认元数据合并规则**：
   - **名称**：base 名称后追加 `（合并自：name1, name2, ...）` 标记。
   - **描述**：所有 Skill 的描述用 `---` 分隔线拼接合并。
   - **关键词**：所有 Skill 的关键词取并集去重。

### 第三步：执行合并

调用 Service 层 `merge_experiences()` 方法：

```python
from ENUM.exprience import ExperienceType
from service.experience_service import ExperienceService

merged = ExperienceService.merge_experiences(
    experience_type=ExperienceType.SKILL,
    base_id="<保留的 Skill ID>",
    merge_ids=["<被合并 Skill ID 1>", "<被合并 Skill ID 2>", ...],
)
```

此方法会自动：

- 校验所有 ID 存在且类型一致。
- 合并 name / description / keywords 到 base。
- 更新 base 的 DB 记录和 FTS 索引。
- 将被合并的 Skill 软删除（status → deleted）。

### 第四步：更新源文件

合并仅影响 DB 中的元信息，**不会自动修改 `data/skill_hub/` 下的 skill_def.md 源文件**。合并完成后需手动或由智能体：

1. 更新 base Skill 目录下的 `skill_def.md`，反映合并后的 name、description、keywords。
2. 可选：合并 `scripts/`、`references/`、`assets/` 等高级内容目录中的资源。
3. 可选：删除或归档被合并 Skill 的目录。
4. 可选：更新 `database.yaml`，整合各 Skill 的评测用例。

### 第五步：验证

```bash
# 确认 base Skill 信息已更新
uv run experience-skill list-experiences --type SKILL --name "<合并后的名称>"

# 确认被合并 Skill 已软删除（不再出现在正常列表）
uv run experience-skill search-experiences --query "<被合并 Skill 名>" --type SKILL
```

## 合并规则细节

| 字段 | 合并行为 |
| ---- | ------- |
| name | `{base.name}（合并自：{src1.name}, {src2.name}）` |
| description | 各 Skill 描述以 `\n---\n` 分隔拼接，经特殊字符清洗后入库 |
| keywords | 所有 Skill 关键词取并集去重 |
| source | 保持 base 的 source 不变 |
| is_hot | 保持 base 的 is_hot 不变 |
| status | base 不变；被合并 Skill 标记为 deleted |

## 错误处理

- 若 base_id 不在 merge_ids 中且不存在于 DB，抛出 `ValueError`。
- 若任何 merge_ids 不存在或已删除，抛出 `ValueError`。
- 若 base 或 merge 目标的 type 不是 SKILL，抛出 `ValueError`。
- 合并失败时所有操作自动回滚（SQLite 事务保证）。
