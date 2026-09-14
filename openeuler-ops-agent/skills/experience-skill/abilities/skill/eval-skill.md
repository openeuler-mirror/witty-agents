# eval-skill

## 触发条件

当满足以下任一条件时触发本能力：

- 用户明确提出"评估 Skill"、"检查技能质量"、"验证 XX 技能"等意图。
- Skill 创建完成后，自动触发质量核验。
- Skill 优化后，需要验证优化效果。
- 定期维护存量 Skill，批量评估时效性和准确性。
- Agent 在执行任务时发现 Skill 存在疑似错误或过时内容。

## 评估维度

从以下维度对 Skill 进行综合质量评估，每个维度给出 **A（优秀）/ B（合格）/ C（需改进）/ D（不合格）** 四级评分：

| 维度 | 权重 | 评估要点 |
|------|------|----------|
| **准确性** | 30% | 流程步骤正确、API 调用有效、命令可成功执行、技术信息准确 |
| **完整性** | 25% | 覆盖核心场景和边界条件、前置约束清晰、错误处理完备 |
| **可读性** | 20% | 描述清晰、术语一致、格式规范、符合 Agent Skills 标准 |
| **时效性** | 15% | 引用的工具/库版本最新、流程符合当前最佳实践 |
| **可执行性** | 10% | 脚本可运行、命令可复现、示例可验证 |

## 执行流程

### 第一步：定位目标 Skill

通过 `find-skill` 或 `list-experiences` 定位待评估的 Skill：

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

记录目标 Skill 的 ID 和 source 路径。

### 第二步：全面读取 Skill 内容

读取 Skill 目录下所有文件，建立完整的内容视图：

```bash
# 读取主文件
cat data/skill_hub/<skill-name>/skill_def.md

# 检查高级内容目录（若存在）
ls -la data/skill_hub/<skill-name>/scripts/
ls -la data/skill_hub/<skill-name>/references/
ls -la data/skill_hub/<skill-name>/assets/

# 读取评测用例（若存在）
cat data/skill_hub/<skill-name>/database.yaml
```

### 第三步：分维度评估

#### 3a. 准确性评估（权重 30%）

**检查清单**：

- [ ] `skill_def.md` 中的命令/脚本是否可成功执行？
- [ ] 引用的 API、工具版本是否与当前环境匹配？
- [ ] 流程步骤逻辑是否正确？关键步骤是否有遗漏？
- [ ] 技术术语和概念是否准确？
- [ ] 代码示例是否存在语法错误或逻辑缺陷？

**评估方法**：

1. 逐条阅读流程步骤，验证每个步骤的可执行性。
2. 若有 `scripts/` 目录，检查脚本逻辑是否正确，错误处理是否完备。
3. 若有 `references/` 目录，交叉验证参考资料中的技术信息。
4. 对关键命令进行空跑或 dry-run 验证。

**评分标准**：

| 等级 | 标准 |
|------|------|
| A | 所有步骤准确无误，代码可执行，技术信息正确 |
| B | 核心步骤准确，存在少量非关键疏漏 |
| C | 存在明显错误或过时信息，影响可用性 |
| D | 严重错误，Skill 无法正常使用 |

#### 3b. 完整性评估（权重 25%）

**检查清单**：

- [ ] 是否覆盖了描述声明的所有功能场景？
- [ ] 前置约束是否完整（环境依赖、权限要求、前置条件）？
- [ ] 边界条件和异常场景是否有处理说明？
- [ ] 是否有完整的错误处理指导？
- [ ] `database.yaml` 评测用例是否覆盖核心场景和边界条件？
- [ ] 高级内容目录（`scripts/`、`references/`、`assets/`）是否充分利用？

**评估方法**：

1. 对照 `description` 字段，检查正文是否覆盖所有声明的功能。
2. 检查是否存在「未定义的行为」——流程中跳过的步骤或模糊地带。
3. 查看 `database.yaml` 评测用例数量和覆盖度。
4. 评估高级内容目录的利用程度：是否有应该脚本化但未脚本化的操作？是否有应当提取到 `references/` 的冗长内容？

**评分标准**：

| 等级 | 标准 |
|------|------|
| A | 覆盖全面，边界条件完善，评测用例充分，高级内容利用得当 |
| B | 核心场景覆盖完整，部分边界条件或错误处理可加强 |
| C | 存在明显缺失（缺关键步骤、缺约束说明、缺评测用例） |
| D | 内容严重残缺，无法指导任务完成 |

#### 3c. 可读性评估（权重 20%）

**检查清单**：

- [ ] `skill_def.md` 格式是否符合规范（YAML front matter + Markdown 正文）？
- [ ] YAML front matter 字段是否完整、格式是否正确？
- [ ] Markdown 排版是否规范（标题层级、代码块、表格、列表）？
- [ ] 术语使用是否一致？描述是否清晰无歧义？
- [ ] 是否遵循渐进式披露原则（主文件 < 500 行，详细内容在 references/）？
- [ ] 文件引用是否使用相对路径？

**评分标准**：

| 等级 | 标准 |
|------|------|
| A | 格式规范，描述清晰，术语一致，完美遵循渐进式披露 |
| B | 格式基本规范，存在少量可改进的表述 |
| C | 格式混乱、术语不一致、描述有歧义 |
| D | 难以阅读和理解，格式严重不符合规范 |

#### 3d. 时效性评估（权重 15%）

**检查清单**：

- [ ] 引用的工具、库版本是否为当前推荐版本？
- [ ] 流程是否反映当前最佳实践？
- [ ] 是否存在已废弃的 API 或命令？
- [ ] 外部链接是否有效（若有）？
- [ ] `compatibility` 字段描述的环境是否与当前一致？

**评分标准**：

| 等级 | 标准 |
|------|------|
| A | 完全时效，所有引用均为当前版本 |
| B | 核心内容时效，存在少量版本号可更新 |
| C | 存在过时内容（已废弃 API、旧版本命令） |
| D | 严重过时，Skill 在新环境中无法使用 |

#### 3e. 可执行性评估（权重 10%）

**检查清单**：

- [ ] `scripts/` 中的脚本是否可直接运行？
- [ ] 脚本是否有清晰的依赖声明和错误处理？
- [ ] 示例命令是否可直接复制执行？
- [ ] 是否有 `--help` 或等效的用法说明？
- [ ] 输入输出格式是否明确？

**评分标准**：

| 等级 | 标准 |
|------|------|
| A | 脚本可运行，命令可复现，错误处理完善 |
| B | 核心脚本可运行，部分辅助脚本有依赖问题 |
| C | 脚本存在运行错误，命令不可直接复现 |
| D | 无脚本或脚本完全无法运行 |

### 第四步：综合评分

根据各维度权重计算综合得分：

```
综合得分 = 准确性×0.30 + 完整性×0.25 + 可读性×0.20 + 时效性×0.15 + 可执行性×0.10
```

等级换算：A=4, B=3, C=2, D=1

| 综合得分 | 综合等级 | 建议动作 |
|----------|----------|----------|
| ≥ 3.5 | A | 无需优化，可正常使用 |
| 2.5 ~ 3.4 | B | 建议小幅优化（optimize-skill） |
| 1.5 ~ 2.4 | C | 需要显著优化（optimize-skill） |
| < 1.5 | D | 建议重写或归档 |

### 第五步：输出评估报告

生成结构化的评估报告：

```markdown
# Skill 评估报告

## 基本信息
- **Skill 名称**: <name>
- **Skill ID**: <id>
- **评估日期**: <YYYY-MM-DD>
- **评估人**: Agent / User

## 各维度评分
| 维度 | 等级 | 得分 | 主要问题 |
|------|------|------|----------|
| 准确性 | B | 3 | 步骤3的API版本需要更新 |
| 完整性 | A | 4 | - |
| 可读性 | B | 3 | references目录缺失，主文件过长 |
| 时效性 | B | 3 | Python版本要求需更新 |
| 可执行性 | A | 4 | - |

## 综合评分
- **综合得分**: 3.3
- **综合等级**: B
- **建议动作**: 小幅优化

## 优化建议
1. 更新步骤3的API版本至v2.0
2. 将详细API参考拆分至 references/REFERENCE.md
3. 更新 compatibility 字段的Python版本要求

## 评测用例验证（若有 database.yaml）
| 用例 | 状态 | 备注 |
|------|------|------|
| testcase1 | ✅ 通过 | - |
| testcase2 | ❌ 失败 | 预期答案与实际不符 |
```

### 第六步：跟进动作

根据评估结果执行相应动作：

- **综合等级 A**：记录评估结果，无需额外操作。
- **综合等级 B**：提示用户存在改进空间，询问是否执行 `optimize-skill`。
- **综合等级 C**：明确建议优化，列出优化清单。
- **综合等级 D**：建议重写 Skill 或标记为废弃（软删除）。

## 批量评估

对存量 Skill 进行批量健康检查：

```bash
# 列出所有 Skill
uv run experience-skill list-experiences --type SKILL

# 逐个评估
# 可使用脚本批量读取 database.yaml 并执行自动化评测
```

**批量评估优先级**：

1. 更新时间超过 6 个月的 Skill
2. 评测用例失败率 > 30% 的 Skill
3. 被标记为「热门」但从未评估过的 Skill

## 自动化评测

对于包含 `database.yaml` 的 Skill，可进行自动化评测：

```python
import yaml
from pathlib import Path

def auto_eval_skill(skill_path: str) -> dict:
    """基于 database.yaml 自动评测 Skill。"""
    db_path = Path(skill_path) / "database.yaml"
    if not db_path.exists():
        return {"status": "skipped", "reason": "database.yaml 不存在"}

    with open(db_path, encoding="utf-8") as f:
        testcases = yaml.safe_load(f) or []

    results = []
    for tc in testcases:
        for name, case in tc.items():
            # 使用 Skill 流程处理 testcase 的 question
            # 对比实际输出与预期 answer
            # 此处为伪代码，实际实现需调用 LLM 或脚本
            results.append({
                "name": name,
                "question": case.get("question"),
                "expected": case.get("answer"),
                "actual": None,  # 实际执行结果
                "passed": False,
            })

    passed = sum(1 for r in results if r["passed"])
    return {
        "status": "completed",
        "total": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "results": results,
    }
```

## 与 Agent Skills 规范的合规性检查

除功能性评估外，还应检查 Skill 是否符合规范格式：

- [ ] 主文件名为 `skill_def.md`（YAML front matter + Markdown 正文）
- [ ] `name` 字段仅包含小写字母、数字、连字符
- [ ] `name` 与父目录名称一致
- [ ] `description` 非空且 ≤ 1024 字符
- [ ] `license`、`compatibility`、`metadata`、`allowed-tools` 字段格式正确（若存在）
- [ ] 可选目录使用规范名称（`scripts/`、`references/`、`assets/`）
- [ ] 文件引用使用相对路径
- [ ] 主文件 ≤ 500 行（渐进式披露建议）

## 错误处理

- 若 Skill 目录不存在，确认 source 路径是否正确。
- 若 `skill_def.md` 不存在，确认 Skill 目录是否正确。
- 若 `database.yaml` 格式错误（非合法 YAML），提示修正后重新评估。
- 评测过程中发现严重错误时，即时中断并输出已评估部分的结果。
