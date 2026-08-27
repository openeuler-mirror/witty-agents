# OpenCode 接入（方案甲）

1. 确保本机 Web 已启动：`./scripts/start_web.sh`（8199）。
2. 将本目录 `skills/` 链到系统 OpenCode skills 目录，或复制过去。
3. 使用 `role-prompt.md` 作为 nl2sql Agent 系统提示（后续 register 脚本会自动化）。

Agent 只通过 HTTP 调用 Core，不重复实现引擎逻辑。
