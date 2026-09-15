# experience-skill

经验技能管理组件，用于统一管理用户工作经验的能力沉淀。支持 **Skill**（标准化工作流程）与 **Wiki**（资料文档提炼）两类资源的全生命周期管理，为智能体能力持续迭代升级提供底层支撑。

## 功能特性

- **双模经验管理**：支持 Skill（工作流程技能）与 Wiki（资料知识库）两类经验资源
- **全生命周期覆盖**：创建、评估、检索、合并、优化五大标准化能力
- **混合全文检索**：默认融合 FTS5 元数据检索 + ripgrep/grep 正文搜索，支持中英文混合查询，结果标注匹配来源
- **正文内容召回**：元数据中未覆盖的关键词也能命中（如正文中"rpm 数据库损坏"可被"数据库"检索召回）
- **高性能后端降级**：正文搜索优先使用 ripgrep（`rg --json --fixed-strings`），不可用时自动降级为 Python 原生扫描
- **热门经验追踪**：自动标记高频使用经验（同类型 Top 20），支持 LRU 淘汰与按热门度筛选
- **CLI 命令行工具**：提供完整的命令行接口，便于集成到自动化流水线
- **Web 管理界面**：基于 FastAPI 的图形化管理前端，支持类型筛选、关键词过滤、分页浏览、检索模式切换

## 目录结构

```
experience_skill/
├── abilities/                 # 核心能力定义（skill + wiki 各五项）
├── scripts/                   # Python 项目（uv 管理）
│   └── src/experience_skill_cli/
│       ├── cli.py             # CLI 入口
│       ├── console.py         # 控制台输出
│       ├── sqlite.py          # SQLite + FTS5 封装
│       ├── web_server.py      # FastAPI Web 服务
│       ├── service/           # 业务服务层（含混合检索融合）
│       ├── manager/           # 数据库操作层 + 正文搜索器
│       ├── schema/            # 数据模型
│       ├── common/            # 公共常量
│       └── tokenizer/         # 中文分词扩展
├── data/                      # 用户数据（不纳入版本控制）
│   ├── skill_hub/             # Skill 仓库
│   └── wiki_hub/              # Wiki 仓库
├── example/                   # 参考模板
├── SKILL.md                   # 组件自描述文档
└── README.md
```

## 快速开始

### 1. 编译 simple 分词器扩展

全文检索依赖 `simple` 分词器（支持中文与拼音分词），首次使用前需编译：

```bash
bash scripts/src/experience_skill_cli/tokenizer/build.sh
```

脚本会自动查询 GitHub 最新 Release 版本并下载源码编译。若本地已存在对应版本的 `.tar.gz` 包则直接解压编译，无需重复下载。

### 2. 安装依赖

本项目使用 `uv` 管理 Python 依赖，在 `scripts/` 目录下执行：

```bash
cd scripts
uv sync
```

### 3. 使用 CLI

所有 CLI 命令在 `scripts/` 目录下通过 `uv run experience-skill` 执行：

```bash
cd scripts

# 同步 data/ 中所有经验到数据库
uv run experience-skill sync

# 添加 Skill 经验
uv run experience-skill add-experiences --type SKILL --source data/skill_hub/example-skill

# 添加 Wiki 经验
uv run experience-skill add-experiences --type WIKI --source data/wiki_hub/example.md

# 列出所有经验（分页）
uv run experience-skill list-experiences

# 按类型与名称过滤
uv run experience-skill list-experiences --type SKILL --name example

# 按热门筛选
uv run experience-skill list-experiences --is-hot true

# 混合检索（默认：FTS5 元数据 + 正文内容，支持中文/拼音）
uv run experience-skill search-experiences --query "数据库" --type SKILL --top-k 5

# 仅元数据检索（FTS5，旧默认行为）
uv run experience-skill search-experiences --query "数据库" --type SKILL --metadata-only

# 仅正文检索（跳过 FTS5）
uv run experience-skill search-experiences --query "数据库" --type SKILL --content-only

# 按 ID 删除
uv run experience-skill delete-by-ids --ids <uuid1> <uuid2>

# 按来源路径删除
uv run experience-skill delete-by-source --source data/skill_hub/example-skill

# 清空所有数据
uv run experience-skill delete-all
```

### 4. 启动 Web 管理界面

```bash
cd scripts
uv run experience-skill web
```

Web 服务默认监听 `127.0.0.1:8080`，在 macOS 或有图形环境的 Linux 下会自动打开浏览器。支持自定义端口：

```bash
uv run experience-skill web --port 9090 --no-browser
```

Web 页面功能：
- **类型筛选**：全部 / Skill / Wiki 标签切换
- **名称搜索**：模糊匹配经验名称
- **关键词过滤**：多选关键词标签联动过滤
- **热门筛选**：仅查看热门经验
- **检索模式切换**：混合检索（默认）/ 元数据 / 正文
- **分页浏览**：上一页 / 下一页翻页

## 核心概念

### Skill（技能）

聚焦个人标准化工作流程的沉淀描述。每个 Skill 以目录形式存放，目录内需包含：

- `skill_def.md`：技能定义文档（YAML Front Matter + Markdown）
- `database.yaml`（可选）：评测用例集

**skill_def.md 示例结构**：

```yaml
---
name: example-skill
description: 这是一个示例技能，用于展示 Skill 的标准文档结构。
keywords: [示例, 技能, 文档]
---

# Example Skill
## 约束
## 流程
## 能力
## 结构
## 规则
```

### Wiki（知识库）

工作过程中查阅的网页、文档等资料的提炼总结，与 Skill 采用相同的 **YAML front matter + Markdown 正文** 格式，以单个 `.md` 文件形式存放。仅 YAML header 中的 name、description、keywords、references 元信息存入数据库用于检索，Markdown 正文不入库，检索命中后按 source 路径读取完整文件。

> 混合检索模式下，正文内容会通过 ripgrep/grep 参与搜索，即使元数据中未包含某关键词，正文中的匹配也能被召回。

```yaml
---
name: "Example Wiki Document"
description: "示例 Wiki 文档，展示标准化 Wiki 的 YAML front matter + Markdown 正文格式"
keywords:
  - keyword1
  - keyword2
  - keyword3
references:
  - name: "《example_1 的入门简介》"
    type: online
    source: "http://example.com"
---

# Example Wiki Document

## 简介
这是 Wiki 文档的正文内容区域，使用标准 Markdown 格式编写。

## 参考资料
- [《example_1 的入门简介》](http://example.com)（在线）
```

## 数据模型

### experience_table（经验主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT (UUID) | 主键，唯一标识 |
| `type` | TEXT | 类型：`skill` / `wiki` |
| `name` | TEXT | 经验名称（来自 YAML front matter） |
| `description` | TEXT | 描述文本（参与 FTS5 全文检索，入库前过滤特殊字符） |
| `references` | TEXT | 参考资料 JSON 字符串（来自 YAML front matter） |
| `status` | TEXT | 状态：`existed` / `deleted`（软删除） |
| `is_hot` | BOOLEAN | 是否热门（高频使用时自动标记，同类型 Top 20） |
| `source` | TEXT | 来源路径（唯一键，防重复注册） |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

### keyword_table（关键词表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT (UUID) | 主键 |
| `experience_id` | TEXT | 关联的经验 ID |
| `name` | TEXT | 关键词名称 |

### experience_fts（全文索引 - 虚拟表）

基于 FTS5 + `simple` 分词器，对 `description` 字段建立全文索引，通过触发器自动同步增删改操作。

## 检索机制

组件默认启用**混合检索**，融合元数据与正文两种召回通路：

1. **FTS5 元数据检索**：基于 SQLite FTS5 + `simple` 分词器，对 `description` 字段进行中文、拼音混合查询
   - 第一阶段：使用 `simple_query()` 做 AND 语义精确查询（取 `top_k // 2` 条）
   - 第二阶段：若结果不足，使用标准 OR 语法做松散查询补全（去重后补足至 `top_k` 条）
2. **正文内容检索**：基于 ripgrep（`rg --json --fixed-strings`）或 Python 原生扫描，搜索 Markdown 正文内容
   - 自动跳过 YAML front matter，仅匹配正文部分
   - ripgrep 不可用时自动降级为 Python 逐文件行扫描
3. **加权融合排序**：
   - DB 得分 = 1 / rank（位置得分，#1 = 1.0）
   - 内容得分 = 命中行数 / 最大命中行数（归一化到 [0, 1]）
   - 最终得分 = 0.6 × DB 得分 + 0.4 × 内容得分
   - 结果标注匹配类型：`both`（双重命中）/ `metadata`（仅元数据）/ `content`（仅正文）
4. **检索模式切换**：
   - CLI：`--metadata-only` 仅元数据 / `--content-only` 仅正文 / 默认混合
   - Web API：`search_mode=hybrid|metadata|content`
5. **检索过滤**：支持按 `fields`（关键词字段）、`is_hot`（热门）、`banned_experience_ids`（排除）、`experience_ids`（限定范围）多维度过滤

## 热门经验机制

- 每次全文检索命中后，命中经验会调用 `update_hot_experience` 更新热度
- 同类型（Skill / Wiki 分别计数）最多保留 **20 条**热门经验
- 超出阈值时，按 `updated_at` 升序淘汰最早的热门记录（LRU 策略）
- 热门标记通过 `is_hot` 字段持久化存储，支持 CLI 和 Web 界面按热门筛选

## 约束规范

- 所有新建 Skill、Wiki 必须统一存放至 `data/skill_hub`、`data/wiki_hub` 目录，禁止自定义存储路径
- 沉淀内容禁止包含恶意代码、敏感数据、隐私信息及违规内容
- 新建前必须先执行检索查重；存在相似资源时，优先推荐合并、优化，而非重复新建
- 当存量资源体量较大时，定期合并同质化内容，精简资源库、降低冗余维护成本

## 能力说明

| 能力 | Skill | Wiki | 说明 |
|------|-------|------|------|
| 创建 | `create-skill` | `create-wiki` | 从对话或资料中沉淀标准化经验；创建前自动查重 |
| 评估 | `eval-skill` | `eval-wiki` | 基于评测集或抽样问答开展质量核验 |
| 检索 | `find-skill` | `find-wiki` | FTS5 全文检索 + 正文内容 grep（默认混合检索） |
| 合并 | `merge-skill` | `merge-wiki` | 识别相似资源，多份内容合并整编 |
| 优化 | `optimize-skill` | `optimize-wiki` | 依据评估报告迭代优化，修复错误、补全内容 |
