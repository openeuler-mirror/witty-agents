# optimize-skill

## 触发条件

当满足以下任一条件时触发本能力：

- `eval-skill` 质量评估发现 Skill 存在缺陷（内容过时、描述不清、代码有误、评测用例不足等）。
- 用户明确提出"优化这个 Skill"、"更新技能"、"改进 XX 技能"等意图。
- 定期维护存量 Skill，检查并修复过期流程、补充缺失内容。

## 执行流程

### 第一步：定位目标 Skill

通过 `find-skill` 或 `list-experiences` 定位待优化的 Skill：

```bash
# 按名称搜索
cd scripts
uv run experience-skill search-experiences \
    --query "<Skill 名称或关键词>" \
    --type SKILL \
    --top-k 5

# 或浏览全量列表
uv run experience-skill list-experiences --type SKILL
```

记录目标 Skill 的 ID（如 `a1b2c3d4-...`）和 source 路径。

### 第二步：读取现状 & 分析问题

读取 Skill 源文件及所有高级内容，梳理优化点：

```bash
# 读取主文件
cat data/skill_hub/<skill-name>/skill_def.md

# 检查高级内容目录
ls -la data/skill_hub/<skill-name>/scripts/
ls -la data/skill_hub/<skill-name>/references/
ls -la data/skill_hub/<skill-name>/assets/

# 读取评测用例
cat data/skill_hub/<skill-name>/database.yaml  # 如果存在
```

常见优化维度：

| 维度 | 典型问题 | 优化方向 |
| ---- | ------- | ------- |
| **准确性** | 流程步骤有误、API 已变更 | 修正为当前正确做法 |
| **完整性** | 缺少关键步骤、边界条件未覆盖 | 补充遗漏内容 |
| **可读性** | 描述不清、术语混乱、格式不规范 | 重写模糊段落，统一格式 |
| **时效性** | 引用的工具/库版本过时 | 更新为当前版本 |
| **评测覆盖** | database.yaml 缺失或用例不足 | 补充高质量评测用例 |
| **关键词** | 标签不准确、遗漏核心关键词 | 更新 metadata.keywords |
| **高级内容** | scripts/ database.yaml 存在空壳或无效内容 | **优先删除无用内容**，确有需求时再补充 |
| **命名规范** | name 字段不合规（含大写、特殊字符等） | 修正 name 字段 |

### 第三步：执行优化

根据问题分析结果，逐项改进。

> **核心原则：删除优先于新增。** 无用的 scripts/ 和 database.yaml 比缺失它们更糟糕——它们占用空间、误导使用者、还可能在 YAML 解析时报错。

#### 3a. 更新 skill_def.md 内容

直接编辑 `data/skill_hub/<Skill 目录>/skill_def.md`：

- 修正 YAML front matter 中的 `name`、`description`、`license`、`compatibility`、`metadata`（含 `keywords`）、`allowed-tools`（如有变更）。
- 更新正文各章节内容，遵循渐进式披露原则。
- 确保文件引用使用相对路径。

#### 3b. 优化 scripts/ 目录

**第一步：判断是否该删除。**

以下情况应**直接删除 scripts/ 目录或其中的脚本**：
- 脚本是"模板空壳"——参数解析框架写了，但实际逻辑为空或永远不可达（如变量赋值在 `echo "完成"` 之后）。
- 脚本内容只是把 skill_def.md 中的命令摘抄进一个文件——Agent 可以直接执行那些命令，脚本无增量价值。
- Skill 是纯诊断/排查/决策类的人工指导，不涉及可自动化操作。

**第二步：确认有必要保留后，再做以下优化：**

- 修正脚本中的逻辑错误，更新过时的依赖版本。
- 补充错误处理和 `--help` 用法说明。
- 添加或更新脚本注释，说明依赖和用法。

#### 3c. 优化 references/ 目录

检查并优化参考文档：

- 若 `skill_def.md` 超过 500 行，将详细的技术参考内容拆分到 `references/` 目录。
- 为每个领域创建独立文件（如 `references/api.md`、`references/config.md`）。
- 确保 `skill_def.md` 中有明确的文件引用链接。
- 若 references/ 中的内容在 skill_def.md 正文中已充分覆盖，删除重复文件。

#### 3d. 优化 assets/ 目录

检查并优化静态资源：

- 补充缺失的模板文件（如配置模板、文档模板）。
- 更新过时的模板内容。
- 在 `skill_def.md` 中说明模板的使用方式。
- 若模板与 Skill 无关或数据已过时，直接删除。

#### 3e. 优化 database.yaml

**第一步：判断是否该删除。**

以下情况应**直接删除 database.yaml**：
- 用例内容就是把 skill_def.md 中的 Q&A 改写格式塞进去——这只是格式转换，无独立测试价值。
- 用例的 answer 是模糊描述（如"成功完成"、"正常输出"），无法自动化判断通过/失败。
- YAML 格式错误且修复后用例仍然无价值。

**第二步：确认有必要保留后，再做以下优化：**

- 确保 YAML 格式正确：用例名称后必须有冒号，question/answer 缩进对齐（参见 create-skill 中的格式错误示例）。
- 补充覆盖边界条件和异常路径的用例。
- 确保 answer 描述预期结果的关键特征，便于判断实际输出是否达标。

#### 3f. 同步 DB 元信息

调用 Service 层 `optimize_experience()` 方法，将修改后的元信息同步到 SQLite：

```python
from service.experience_service import ExperienceService

updated = ExperienceService.optimize_experience(
    experience_id="<Skill ID>",
    name="<新名称，不需要改则传 None>",
    description="<新描述，不需要改则传 None>",
    keywords=["<新关键词列表>"],
)
```

此方法会自动：

- 更新 `experience_table` 中对应记录的 name / description（触发 FTS 索引更新）。
- 若传入 keywords，全量替换 `keyword_table` 中该 Skill 的关键词（先删后插）。
- 更新 `updated_at` 时间戳。

### 第四步：验证

```bash
# 确认 DB 记录已更新
uv run experience-skill list-experiences --type SKILL --name "<Skill 名称>"

# 确认优化后的 Skill 可被检索召回
uv run experience-skill search-experiences \
    --query "<优化后的核心关键词>" \
    --type SKILL \
    --top-k 5
```

## 优化原则

1. **删除优先于新增**：无用的 scripts/ 和 database.yaml 比缺失它们更糟糕。优先删除空壳脚本、无效用例，再考虑补充有价值的内容。
2. **增量改进**：只修改有问题的部分，不推翻重写已验证正确的内容。
3. **保持一致性**：skill_def.md 与 DB 记录的 name / description / keywords 必须一致。
4. **评测驱动**：仅在 database.yaml 有独立测试价值时才补充或保留评测用例。无价值的用例宁可删除。
5. **记录变更**：复杂优化建议在 skill_def.md 中添加变更日志，方便回溯。
6. **渐进式披露**：主文件超过 500 行时，将详细内容拆分到 references/ 目录。
7. **规范合规**：确保 skill_def.md 格式规范（命名、front matter 字段、目录结构遵循 Agent Skills 规范）。

## 高级内容优化检查清单

| 目录 | 第一检查：是否该删除？ | 第二检查：如何改进？ |
|------|----------------------|---------------------|
| `scripts/` | 是空壳模板？是 skill_def.md 命令摘抄？Skill 无自动化操作？→ **删除** | 逻辑错误？缺错误处理？无 `--help`？→ 修正 |
| `references/` | 内容已在 skill_def.md 中充分覆盖？→ **删除重复文件** | 主文件 > 500 行？→ 拆分冗长内容到此 |
| `assets/` | 模板与 Skill 无关？数据已过时？→ **删除** | 缺失必要模板？→ 创建 |
| `database.yaml` | 用例只是正文改写？answer 模糊不可验证？YAML 格式错误？→ **删除** | 有独立测试价值？→ 补充边界用例 |

## 错误处理

- 若 experience_id 不存在或已删除，抛出 `ValueError`。
- 若 skill_def.md 文件被外部修改但 DB 未同步，先手动确认文件内容，再调用 optimize 同步。
- keywords 传入 `None` 表示不修改关键词；传入空列表 `[]` 会清空所有关键词。
