# OpenCode 接入

1. 准备仓库根：`.env` 或用 skill CLI `settings-set` 配置 LLM、rag-core、业务库。
2. 将 `skills/nl2sql` 链到（或复制进）OpenCode skills 目录。
3. Agent **只**按 `skills/nl2sql/SKILL.md` 与 `references/api.md` 调用本地脚本，**不要**访问 `:8199`。

示例：

```bash
python3 opencode_plugin/skills/nl2sql/scripts/nl2sql_skill_cli.py ask \
  -q "40-60岁 去过成都的重点关注人员" --datasource-id local-es
```

可选系统提示：`role-prompt.md`。  
**生成**可用 Agent 会话模型或 NL2SQL 已配置 LLM；**执行**始终走 skill CLI / `nl2sql_core`。
