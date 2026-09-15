# create-skill

## 触发条件

当用户明确提出"沉淀为 Skill"、"保存为技能"、"记录工作流程"等意图，或智能体完成一项复杂任务后主动询问是否沉淀时，触发本能力。

## 前置约束

- 所有新建 Skill 必须存放至 `data/skill_hub/` 目录下，以独立子目录形式组织。
- Skill 目录内必须包含 `skill_def.md` 文件（YAML front matter + Markdown，格式遵循 Agent Skills 规范）。`database.yaml`（评测用例）、`scripts/`（可执行脚本）、`references/`（参考文档）、`assets/`（静态资源）均为可选——**仅在确实需要时创建，默认不生成**。
- 目录名称必须与 `skill_def.md` 中的 `name` 字段一致。
- 禁止在 skill_def.md 内容中包含恶意代码、敏感数据、隐私信息。

> **关于文件命名**：本项目中 `data/skill_hub/` 下的 Skill 使用 `skill_def.md` 而非标准 `SKILL.md`。原因是 `SKILL.md` 会被 OpenCode 自动发现并全量注入会话上下文（通过 `~/.agents/skills/` 递归扫描），而 skill_hub 中的 Skill 应通过 CLI 按需检索加载。`skill_def.md` 的格式（YAML front matter + Markdown 正文）完全遵循 Agent Skills 规范，仅文件名不同。

## Skill 目录结构

一个完整的 Skill 目录结构如下（格式遵循 [Agent Skills 规范](https://agentskills.io/specification)）：

```
skill-name/
├── skill_def.md      # 必需：元数据 + 指令（YAML front matter + Markdown）
├── scripts/          # 可选：可执行代码（Python、Bash、JavaScript 等）
├── references/       # 可选：补充文档（REFERENCE.md、FORMS.md 等）
├── assets/           # 可选：模板、图片、数据文件等静态资源
├── database.yaml     # 可选：评测用例
└── ...               # 其他自定义文件或目录
```

## 执行流程

### 第一步：检索查重

在创建新 Skill 之前，必须先执行检索查重，避免重复建设。

1. 使用 CLI 搜索现有 Skill：

```bash
cd scripts
uv run experience-skill search-experiences \
    --query "<待创建Skill的核心关键词>" \
    --type SKILL \
    --top-k 5
```

2. 若搜索结果中存在高度相似（名称相近、关键词重叠、描述雷同）的 Skill，应：
   - **优先推荐合并（merge-skill）**：告知用户存量资源情况，建议执行合并而非新建。
   - **其次推荐优化（optimize-skill）**：若存量 Skill 内容过时或质量不佳，建议以优化方式更新。
   - 仅当用户明确坚持新建且存量不构成冗余时，才继续创建流程。

### 第二步：确定 Skill 名称和目录

1. **命名规则**（符合 Agent Skills 规范）：
   - 仅允许小写字母（a-z）、数字（0-9）和连字符（`-`）。
   - 长度 1-64 个字符。
   - 不得以连字符开头或结尾。
   - 不得包含连续连字符（如 `a--b`）。
   - 必须与父目录名称完全一致。

   **合法示例**：`pdf-processing`、`data-analysis`、`code-review`
   **非法示例**：`PDF-Processing`（大写）、`-pdf`（以连字符开头）、`pdf--processing`（连续连字符）

2. 在 `data/skill_hub/` 下创建以 Skill 名称命名的子目录：

```bash
mkdir -p data/skill_hub/<skill-name>
```

### 第三步：生成 skill_def.md

若查重通过（无相似 Skill 或用户确认新建），按以下规范生成 `skill_def.md`（YAML front matter + Markdown 正文，格式遵循 Agent Skills 规范）。

#### 3a. YAML front matter

必须包含 `name` 和 `description` 字段，可选包含 `license`、`compatibility`、`metadata`、`allowed-tools` 字段：

```yaml
---
name: <skill-name>
description: >
  <描述 Skill 的功能、触发场景和使用方式。>
  <说明何时应使用此 Skill、关键触发词是什么。>
  <描述输入输出要求。>
license: <可选：许可证名称或 bundled license 文件>
compatibility: <可选：环境要求（如 "Requires git, docker, jq"）>
metadata:
  author: <可选：作者>
  version: <可选：版本号>
  keywords: [关键词1, 关键词2, 关键词3]
allowed-tools: <可选：预批准的工具列表>
---
```

**字段说明**：

| 字段 | 必需 | 约束 |
|------|------|------|
| `name` | 是 | 最大 64 字符，仅小写字母、数字、连字符，与目录名一致 |
| `description` | 是 | 最大 1024 字符，非空。描述 Skill 的功能和触发场景 |
| `license` | 否 | 许可证名称或引用 bundled license 文件 |
| `compatibility` | 否 | 最大 500 字符。环境要求说明 |
| `metadata` | 否 | 任意键值对映射。推荐将 `keywords` 放入此字段 |
| `allowed-tools` | 否 | 空格分隔的预批准工具列表（实验性） |

**description 撰写规范**：
- 用中文撰写，清晰说明三点：Skill 的功能、触发语境、使用方式。
- 最大 1024 字符（约 300 个中文字）。
- 包含具体关键词，帮助 Agent 在检索时准确匹配。

**好的示例**：
```yaml
description: >
  从 PDF 文件中提取文本和表格，填写 PDF 表单，合并多个 PDF 文件。
  当处理 PDF 文档或用户提及 PDF、表单、文档提取时使用此 Skill。
```

**差的示例**：
```yaml
description: 帮助处理 PDF。
```

#### 3b. 正文结构

遵循 Agent Skills 规范的**渐进式披露**原则组织正文：

```markdown
# <Skill 标题>

## 概述
- 简要说明 Skill 的用途和适用范围（2-3 句话即可）。

## 约束
- 描述 Skill 执行的约束条件、适用范围、环境要求等。

## 流程
- 列出清晰的执行步骤，每步可操作、可验证。
- 涉及脚本时使用相对路径引用：`scripts/extract.py`

## 能力
- 描述 Skill 提供的核心能力 / 功能点。

## 结构
- 说明 Skill 目录结构、依赖文件等。

## 规则
- 补充执行规则、注意事项、边界条件。
```

**正文撰写原则**：
- 主 `skill_def.md` 控制在 **500 行以内**。详细参考资料移入 `references/` 目录。
- 引用其他文件时使用**相对路径**，从 Skill 根目录出发：
  - 参考文档：`[参考指南](references/REFERENCE.md)`
  - 运行脚本：`scripts/extract.py`
  - 使用模板：`assets/template.yaml`
- 保持文件引用**一级深度**，避免深层嵌套引用链。

### 第四步：按需创建高级内容

根据 Skill 的实际需求，**按需**创建以下可选目录和文件。

> **核心原则：宁可缺失，不可滥生成。** 一个没有 scripts/ 和 database.yaml 但 skill_def.md 内容扎实的 Skill，远好过一个塞满空壳脚本和无效评测用例的 Skill。**默认不创建任何可选内容**——仅在明确存在对应需求时才生成。

#### 4a. scripts/ — 可执行脚本

**默认不创建。** 仅在同时满足以下三项条件时才生成：

1. Skill 流程中存在**可自动化执行的确定性操作**（如格式转换、日志解析），且脚本确实能显著简化 Agent 的操作。
2. 脚本**真实可运行**——依赖声明完整、错误处理到位、有 `--help` 用法说明。
3. 脚本逻辑**不是**从 skill_def.md 中摘抄命令——那毫无增量价值，Agent 可以直接执行那些命令。

**禁止生成的典型场景**：

- Skill 内容是纯诊断/排查/决策类的人工指导（不涉及可自动化操作）。
- 只能产出"模板空壳"——参数解析框架写了，但实际逻辑为空、或者变量赋值在 `echo "完成"` 之后永远不可达。
- 无法保证脚本在目标环境中正确执行（不确定依赖是否存在）。

当确定需要脚本时：

```bash
mkdir -p data/skill_hub/<skill-name>/scripts
```

**脚本编写规范**：
- 自包含或清晰声明依赖（在 skill_def.md 中说明环境要求）。
- 包含有帮助的错误信息和用法说明（`--help`）。
- 妥善处理边界条件和异常情况。
- 支持的语言取决于 Agent 实现，常见选择：Python、Bash、JavaScript。

**示例** `scripts/extract.py`：

```python
#!/usr/bin/env python3
"""PDF 文本提取脚本。

用法:
    python scripts/extract.py <input.pdf> [--output result.txt]

依赖:
    pip install PyPDF2
"""

import argparse
import sys
from pathlib import Path

def extract_text(pdf_path: str) -> str:
    """从 PDF 提取文本。"""
    # 实现略
    ...

def main():
    parser = argparse.ArgumentParser(description="PDF 文本提取")
    parser.add_argument("input", help="输入 PDF 文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    args = parser.parse_args()

    text = extract_text(args.input)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"已输出至 {args.output}")
    else:
        print(text)

if __name__ == "__main__":
    main()
```

#### 4b. references/ — 参考文档

当 Skill 包含**详细的技术参考、表单模板、领域知识**等内容时，创建 `references/` 目录：

```bash
mkdir -p data/skill_hub/<skill-name>/references
```

**参考文档组织原则**：
- `REFERENCES.md` — 详细技术参考、API 说明、配置参数。
- `FORMS.md` — 表单模板、结构化数据格式。
- 领域专属文件：`finance.md`、`legal.md`、`network.md` 等。
- 每个文件聚焦单一主题，避免内容膨胀。
- Agent 按需加载这些文件，小文件意味着更少的上下文消耗。

**示例** `references/REFERENCE.md`：

```markdown
# PDF 处理参考

## 支持的 PDF 版本
- PDF 1.0 - 2.0
- PDF/A-1, PDF/A-2, PDF/A-3

## API 参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--pages` | string | `all` | 页码范围，如 `1-5,8,11-13` |
| `--dpi` | int | `300` | 输出图片分辨率 |

## 常见错误
- `EncryptedPDFError`：PDF 已加密，需先解密。
```

#### 4c. assets/ — 静态资源

当 Skill 需要**模板文件、配置样例、图片、数据查找表**等静态资源时，创建 `assets/` 目录：

```bash
mkdir -p data/skill_hub/<skill-name>/assets
```

**适合放入 assets/ 的内容**：
- **模板文件**：文档模板、配置文件模板、代码脚手架。
- **图片**：架构图、流程图、截图示例。
- **数据文件**：查找表、Schema 定义、静态数据集。

**示例** `assets/template.yaml`：

```yaml
# PDF 处理配置模板
input:
  path: /path/to/input.pdf
  password: ""  # 若 PDF 加密则填写
output:
  format: txt    # txt | json | html
  path: /path/to/output/
options:
  pages: all     # all | 1-5 | 1,3,5
  dpi: 300
```

#### 4d. database.yaml — 评测用例

**默认不创建。** database.yaml 是为 `eval-skill` 自动化评测服务的——如果 Skill 没有自动化评测需求，或者评测用例只是把 skill_def.md 中的 Q&A 改写格式塞进去，就不要生成。

**仅在以下情况创建**：
- Skill 有明确的、可自动化验证的输入→输出断言。
- 评测用例覆盖了 skill_def.md 正文中**未充分体现**的边界条件或异常路径。
- 用例不是从正文内容的简单改写——必须有独立的测试价值。

**禁止生成的典型场景**：
- 用例内容就是"skill_def.md 中某个步骤的问答对"——这只是格式转换，无增量价值。
- 用例的 answer 是模糊描述（如"成功完成"、"正常输出"），无法自动化判断通过/失败。
- YAML 格式错误（参见下方常见格式错误）。

**文件结构**：YAML 数组，每个元素是以用例名称为 key 的映射，包含 `question` 和 `answer` 字段。

```yaml
- <用例名称>:
    question: <测试问题——描述一个具体任务>
    answer: <预期答案——描述预期结果的关键特征>
```

**实际示例**：

```yaml
- basic_extract:
    question: 使用该 Skill 提取 sample.pdf 中的文本。
    answer: 文本提取成功，输出包含 PDF 中全部文字内容。
- merge_files:
    question: 将 a.pdf 和 b.pdf 合并为一个文件。
    answer: 合并成功，生成包含两文件全部页面的 merged.pdf。
- edge_empty:
    question: 对空文件 empty.pdf 执行提取操作。
    answer: 提示"文件无内容"或返回空文本，不应崩溃。
```

**用例设计原则**：

- **覆盖核心场景**：至少 2-3 个用例覆盖 Skill 的主要功能路径。
- **覆盖边界条件**：包含空输入、异常输入、超大规模输入等边界场景。
- **问题具体可执行**：question 应描述一个具体任务，而非抽象提问。
- **答案可验证**：answer 描述预期结果的关键特征，便于判断实际输出是否达标。

**常见格式错误**（容易导致 YAML 解析失败）：

```yaml
# ❌ 错误：用例名称后缺少冒号 → Implicit keys need to be on a single line
- basic_extract
  - question: ...
  - answer: ...

# ❌ 错误：question 和 answer 前不应有 "- "（它们是映射值，不是列表元素）
- basic_extract:
  - question: ...
  - answer: ...

# ✅ 正确：用例名称带冒号，question/answer 缩进对齐
- basic_extract:
    question: 使用该 Skill 提取 sample.pdf 中的文本。
    answer: 文本提取成功，输出包含 PDF 中全部文字内容。
```

### 第五步：注册入库

将 Skill 目录注册到 SQLite 经验库：

```bash
cd scripts
uv run experience-skill add-experiences \
    --type SKILL \
    --source "<skill_hub下的子目录路径>"
```

此命令会：

- 读取 `skill_def.md` 的 YAML front matter，提取 name、description、keywords（从 metadata 中读取）。
- 检查 source 路径是否已存在（防重复）。
- 将 Skill 元信息写入 `experience_table`，启用 FTS5 全文索引。
- 将 keywords 写入 `keyword_table`，支持关键字过滤检索。

### 第六步：验证

注册成功后，执行一次检索验证 Skill 可被召回：

```bash
uv run experience-skill search-experiences \
    --query "<Skill核心关键词>" \
    --type SKILL \
    --top-k 3
```

确认新创建的 Skill 出现在搜索结果中。

## 渐进式披露设计

遵循 Agent Skills 规范的渐进式披露模式，Skill 按三个层次组织内容：

| 层次 | 内容 | 大小建议 | 加载时机 |
|------|------|----------|----------|
| **元数据** | `name` + `description` | ~100 tokens | DB 检索时匹配 |
| **指令** | `skill_def.md` 正文 | < 5000 tokens（约 500 行） | 通过 CLI 按需检索后加载 |
| **资源** | `scripts/`、`references/`、`assets/` | 按需 | 任务需要时加载 |

**设计建议**：
- 主 `skill_def.md` 控制在 500 行以内，超出部分拆分到 `references/`。
- `references/` 下每个文件聚焦单一主题，方便 Agent 按需精准加载。
- `scripts/` 中的代码应有清晰的注释和错误处理，Agent 可以直接执行。
- `assets/` 中的模板和数据文件应格式规范、便于解析。

## 错误处理

- 若 `skill_def.md` 不存在于 source 目录，CLI 会报 `FileNotFoundError`，需检查路径。
- 若 source 路径已注册过，CLI 会报 `ValueError`，需更换路径或先删除旧记录。
- 若 simple tokenizer 扩展未编译，需先执行 `bash scripts/src/experience_skill_cli/tokenizer/build.sh`。
- 若 `name` 不符合规范（含大写、特殊字符等），注册可能成功但不符合命名规范，建议在创建时严格校验。
