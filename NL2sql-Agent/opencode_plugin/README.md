# OpenCode 接入

1. 准备 NL2SQL 仓库根（含 `nl2sql_core/`）：用 `.env` 或 skill CLI `settings-set` 配置 LLM、rag、业务库。
2. 将 `skills/nl2sql` 链到或复制进 OpenCode skills（例如 `~/.config/opencode/skills/nl2sql`）。
3. 若 skill 与仓库不在同一棵目录树：复制 `scripts/config.example.json` → `scripts/config.json`，设置 `nl2sql_root` 为仓库绝对路径（或 `export NL2SQL_ROOT=...`）。
4. Agent **只**按 `SKILL.md` / `references/api.md` 调本地脚本，**不要**访问 `:8199`。

示例：

```bash
python3 opencode_plugin/skills/nl2sql/scripts/nl2sql_skill_cli.py ask \
  -q "40-60岁 去过成都的重点关注人员" --datasource-id local-es
```

可选系统提示：`role-prompt.md`。  
**生成**可用 Agent 会话模型或 NL2SQL 已配置 LLM；**执行**始终走 skill CLI / `nl2sql_core`。
