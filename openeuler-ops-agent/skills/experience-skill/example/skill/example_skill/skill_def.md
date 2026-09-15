---
name: example-skill
description: >
  这是一个技能示例，展示了如何按照 Agent Skills 规范编写技能的文档结构和内容。
  当用户需要参考 Skill 编写规范或了解 Skill 目录结构时，可使用此示例。
  该 Skill 展示了完整的目录结构，包括 skill_def.md、scripts/、references/、assets/ 和 database.yaml。
license: MIT
compatibility: Requires Python 3.10+ and uv
metadata:
  author: experience-skill
  version: "1.0"
  keywords: [示例, 技能, 文档, 模板]
allowed-tools: Bash(cat:*) Bash(ls:*)
---

# Example Skill

## 概述

这是一个标准 Skill 模板，展示了完整的 Skill 目录结构（格式遵循 Agent Skills 规范，主文件使用 `skill_def.md` 命名以隔离 OpenCode 自动发现）。
可参考此模板创建新的 Skill。

## 约束

- Skill 主文件命名为 `skill_def.md`（YAML front matter + Markdown 正文），存放于以 Skill 名称命名的目录下。
- `name` 字段必须与父目录名称一致，仅含小写字母、数字和连字符。
- `description` 字段必须非空且不超过 1024 字符。
- 可选目录 `scripts/`、`references/`、`assets/` 按需创建。

## 流程

1. 确定 Skill 名称，在 `data/skill_hub/` 下创建同名目录。
2. 编写 `skill_def.md`，包含完整的 YAML front matter 和 Markdown 正文。
3. 按需创建 `scripts/`（可执行脚本）、`references/`（参考文档）、`assets/`（静态资源）。
4. 创建 `database.yaml` 评测用例。
5. 通过 CLI 注册入库并验证。

## 能力

- 提供格式规范的 Skill 模板。
- 展示完整的目录结构和文件组织方式。
- 作为 create-skill 流程的参考示例。

## 结构

详见 [参考指南](references/REFERENCE.md) 获取完整的目录结构说明。

```
example_skill/
├── skill_def.md      # 必需：元数据 + 指令
├── scripts/          # 可选：可执行脚本
├── references/       # 可选：参考文档
├── assets/           # 可选：静态资源
└── database.yaml     # 可选：评测用例
```

## 规则

- 遵循渐进式披露原则，主文件控制在 500 行以内。
- 引用其他文件时使用相对路径。
- 脚本应包含清晰的依赖声明和错误处理。
