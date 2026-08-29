# find-wiki

## 触发条件

当用户需要查找已有的 Wiki 资源时触发，包括但不限于：

- "查找 / 搜索 XX 相关的 Wiki"
- "有没有 XX 知识文档"
- 在执行任务前检索可参考的资料沉淀
- create-wiki / merge-wiki / optimize-wiki 流程中的前置查重步骤
- 需要查阅某领域的工作参考资料时

## 检索能力概述

检索**仅基于 YAML front matter 中存入 DB 的元信息**（name、description、keywords），不搜索 Markdown 正文。正文内容仅供检索命中后按 source 路径读取使用。

本能力结合 **SQLite 关键字检索** 与 **FTS5 全文检索**，实现双重匹配：

- **关键字检索**：通过 `keyword_table` 精确匹配 Wiki 标签，适合按类别、领域筛选。
- **全文检索**：通过 `experience_fts`（simple tokenizer，支持中文/拼音分词）对 description 字段做模糊匹配，适合自然语言查询。

两种模式可组合使用，兼顾精确过滤与语义召回。

## 执行方式

> **运行环境**：以下命令需在 `scripts/` 目录下执行。首次使用前需运行 `uv sync` 安装依赖。

### Web 界面搜索（推荐）

启动 Web 管理界面后，可在浏览器中可视化搜索：

```bash
cd scripts
uv run experience-skill web
```

页面功能：

- 点击 **Wiki** 标签筛选类型
- 在「名称搜索」输入框输入名称片段模糊匹配
- 在「关键词全文检索」输入框使用 FTS5 语义搜索
- 勾选「仅热门」查看高频使用的 Wiki

### 基础搜索（全文检索）

```bash
uv run experience-skill search-experiences \
    --query "<搜索关键词>" \
    --type WIKI \
    --top-k 10
```

- `--query`：自然语言搜索关键词，支持中文、英文、拼音混合输入。
- `--type WIKI`：限定只搜索 Wiki 类型经验。
- `--top-k`：返回结果数量，默认 5，最大建议不超过 20。

### 按关键字过滤搜索

```bash
uv run experience-skill search-experiences \
    --query "<搜索关键词>" \
    --type WIKI \
    --fields <关键词1> <关键词2> \
    --top-k 10
```

- `--fields`：指定必须匹配的关键字标签（对应 keyword_table 中的 name 字段）。只有 keywords 包含指定标签的 Wiki 才会被召回。

### 限制搜索范围

```bash
uv run experience-skill search-experiences \
    --query "<搜索关键词>" \
    --type WIKI \
    --experience-ids <id1> <id2> \
    --top-k 10
```

- `--experience-ids`：限定仅在指定的 Wiki ID 列表中搜索。

### 排除特定 Wiki

```bash
uv run experience-skill search-experiences \
    --query "<搜索关键词>" \
    --type WIKI \
    --banned-ids <id1> <id2> \
    --top-k 10
```

- `--banned-ids`：排除指定 ID 的 Wiki，常用于去重场景。

### 热门优先搜索

```bash
uv run experience-skill search-experiences \
    --query "<搜索关键词>" \
    --type WIKI \
    --is-hot true \
    --top-k 10
```

- `--is-hot true`：仅搜索热门 Wiki（被频繁检索使用过的 Wiki）。

## 检索原理

### 两阶段检索策略

1. **紧凑查询（AND 语义）**：使用 `simple_query()` 对查询分词后做 AND 匹配，召回高精度结果。
2. **松散查询（OR 语义）**：若紧凑查询结果不足 `top_k`，使用标准 OR 语法补全，扩大召回。

### 查询预处理

- 自动过滤 FTS5 特殊符号，保留中文、英文、数字。
- 过滤单字母 ASCII 字符，避免前缀匹配误召回。
- 分词后以空格分隔送入 FTS5 MATCH 语句。

## 结果解读

搜索结果输出每个 Wiki 的完整元信息：

| 字段 | 说明 |
| ---- | ---- |
| ID | Wiki 唯一标识符 |
| 类型 | 固定为 WIKI |
| 名称 | Wiki 名称（来自 .md 文件 YAML front matter 的 name 字段） |
| 状态 | existed / deleted |
| 描述 | Wiki 描述文本 |
| 关键词 | Wiki 标签列表 |
| 来源 | Wiki .md 文件的绝对路径 |
| 是否热门 | 是否高频使用 |
| 创建时间 | 首次入库时间 |
| 更新时间 | 最近一次检索命中时间 |

搜索结果按 FTS5 rank（相关性评分）降序排列。

## 读取 Wiki 内容

搜索返回的是 Wiki 在 DB 中的元信息（name、description、keywords、references）。Markdown 正文不存入数据库，需通过 source 路径读取完整 `.md` 文件获取正文内容：

```bash
cat <搜索结果中的 source 路径>
```

## 结果为空时的处理

1. 确认 simple tokenizer 扩展已编译：`bash scripts/src/experience_skill_cli/tokenizer/build.sh`
2. 尝试缩短 / 精简查询词，减少 AND 语义过紧导致的零召回。
3. 尝试使用 `list-experiences` 命令浏览全量 Wiki 列表：

   ```bash
   uv run experience-skill list-experiences --type WIKI
   ```

4. 或启动 Web 界面可视化浏览：

   ```bash
   uv run experience-skill web
   ```

5. 若确实无相关 Wiki，提示用户可考虑 create-wiki 新建。

## 与其他能力的协作

- **create-wiki**：创建前调用 find-wiki 查重。
- **merge-wiki**：合并前调用 find-wiki 定位相似 Wiki。
- **optimize-wiki**：优化前调用 find-wiki 定位待优化的 Wiki。
- **eval-wiki**：评估时使用 find-wiki 进行召回命中率测试。
