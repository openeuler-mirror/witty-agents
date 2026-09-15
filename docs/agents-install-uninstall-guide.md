# Witty Agents 安装与卸载指南（四个 Agent）

适用 online npm 包（2026-09-15 发布版本）：

| Agent | npm 包 | 版本 |
|---|---|---|
| 神农崩溃分析 | `witty-agent-shennong-online` | 0.10.6 |
| NL2SQL | `witty-agent-nl2sql-online` | 0.1.3 |
| openEuler 运维 | `witty-agent-openeuler-ops-online` | 1.0.1 |
| xlite 性能优化 | `witty-agent-xlite-perf-optimizer-online` | 0.1.1 |

环境：openEuler / Linux（macOS 同样适用）。所有注册信息写入
`~/.config/opencode/opencode.jsonc`，skill 以**符号链接**落在
`~/.config/opencode/skills/`。

---

## 一、装了什么（卸载前必读）

安装并注册后，系统里存在以下内容，卸载需逐一清理：

1. **npm 包本体**：全局（`$(npm root -g)/<包名>`）或项目 `node_modules/<包名>`。
2. **OpenCode 插件注册**：`opencode.jsonc` 的 `plugin` 数组中一条
   `file://.../dist/index.js`；神农另有 `mcp` 配置两项。
3. **skill 符号链接**：`~/.config/opencode/skills/<skill>` → 包内 skill 目录。
4. **Python 虚拟环境 / 模型缓存**（神农、NL2SQL）：`~/.cache/witty-agents/<包名>/`。
5. **常驻服务**（仅神农）：`witty-log-detection` SSE MCP，监听 `127.0.0.1:12144`。
6. **配置备份文件**：每次改配置自动生成 `opencode.jsonc.<owner>-backup-<时间戳>`。
7. **历史遗留**（仅用过旧引导才会有）：
   - xlite：旧版 `xlite-opt-init` 复制的 `~/.config/opencode/agents/xlite-perf-optimizer/`
     与实体 skill 目录、项目 `opencode.jsonc` 片段。
   - ops：`install.sh` 经 skillhub 安装的 `~/.config/opencode/skills/@chuangyinbot-boop/`。

> 卸载顺序固定为：**停服务 → 反注册（删 plugin + skill 链接）→ npm 卸载 → 清缓存/残留**。
> 若先删 npm 包，反注册命令会丢失，需按第五节手动清理。

---

## 二、安装流程（回顾）

每个 agent 都是三步：**① 装包 → ② 装依赖/起服务（需要后端的）→ ③ configure 注册并链接 skill → 重启 OpenCode**。

### 神农

```bash
npm install -g witty-agent-shennong-online
shennong-setup install                      # 建 3 个 venv、下载 OCR 模型、拉起 MCP
shennong-configure install --target=opencode
```

### NL2SQL

```bash
npm install -g witty-agent-nl2sql-online
nl2sql init                                 # 交互配置 LLM/rag/ES/Web → .env
nl2sql start                                # 自建 .venv、装依赖、起 Web(8199)
nl2sql-agent configure                      # register 为别名
# 备选: nl2sql-setup install && start_all.sh（CI/合同模型）
```

### openEuler Ops（无后端）

```bash
npm install -g witty-agent-openeuler-ops-online
openeuler-ops-agent configure               # register 为别名
```

### xlite 性能优化（无后端）

```bash
npm install -g witty-agent-xlite-perf-optimizer-online
xlite-perf-optimizer-configure configure    # register 为别名
```

> 项目内（非全局）安装时，把命令写为 `npm exec -- <命令> ...`，最后用
> `npm uninstall <包名>` 在该项目内移除。

---

## 三、标准卸载流程

### 1. 神农 shennong

```bash
# (1) 停止常驻 SSE MCP 服务（stdio MCP 按需启动，无需处理）
shennong-setup stop

# (2) 反注册：移除 plugin、mcp 配置（自动备份 opencode.jsonc）
shennong-configure remove --target=opencode

# (3) 卸载 npm 包
npm uninstall -g witty-agent-shennong-online

# (4) 清理 Python venv 与 OCR 模型缓存（约数百 MB）
rm -rf ~/.cache/witty-agents/witty-agent-shennong-online
```

缓存路径若自定义过，以环境变量为准：`SHENNONG_VENV_CACHE/<包名>/`
（内含 `venvs/` 与 `ocr-models/`）。

### 2. NL2SQL

```bash
# (1) 反注册并移除 skill 软链
nl2sql-agent remove

# (2) 卸载 npm 包
npm uninstall -g witty-agent-nl2sql-online

# (3) 清理后端 venv
rm -rf ~/.cache/witty-agents/witty-agent-nl2sql-online
```

自定义缓存位置：`NL2SQL_VENV_CACHE/<包名>/venvs/nl2sql`。
NL2SQL 无常驻服务。

### 3. openEuler Ops

```bash
# (1) 反注册并移除全部 11 个 skill 软链
openeuler-ops-agent remove

# (2) 卸载 npm 包
npm uninstall -g witty-agent-openeuler-ops-online
```

无 venv / 无服务。仅在你用过 `install.sh` 的 skillhub 在线安装时，再清理：

```bash
# 可选：删除 skillhub 装的 @namespace 嵌套 skill（OpenCode 本就不扫描该目录）
rm -rf ~/.config/opencode/skills/@chuangyinbot-boop
# 可选：删除 skillhub CLI
rm -f ~/.local/bin/skillhub
```

### 4. xlite 性能优化

```bash
# (1) 反注册并移除 8 个 skill 软链
xlite-perf-optimizer-configure remove

# (2) 卸载 npm 包
npm uninstall -g witty-agent-xlite-perf-optimizer-online
```

无 venv / 无服务。若用过**旧引导** `xlite-opt-init`，额外清理：

```bash
# 旧版复制（非软链）的 agent 与 skill
rm -rf ~/.config/opencode/agents/xlite-perf-optimizer
# 旧版复制到 skills 目录的 8 个实体目录（与新版软链同名，确认是普通目录后再删）
ls -l ~/.config/opencode/skills | grep xlite-            # 确认类型
rm -rf ~/.config/opencode/skills/xlite-analyzer \
       ~/.config/opencode/skills/xlite-complexity-estimator \
       ~/.config/opencode/skills/xlite-operator-dev \
       ~/.config/opencode/skills/xlite-atomic-journal \
       ~/.config/opencode/skills/xlite-profiler \
       ~/.config/opencode/skills/xlite-ascend-runner \
       ~/.config/opencode/skills/xlite-gitcode-runner \
       ~/.config/opencode/skills/xlite-html-reporter
# 同时手动删除项目 opencode.jsonc 中旧片段 config.agent["xlite-perf-optimizer"]
```

工作目录 `.xlite-opt/`（优化 journal、HTML 报告）属**用户数据**，默认保留；
确认不需要后可在各项目内自行删除。

### 5. 收尾

```bash
# 重启 OpenCode，使插件与 skill 列表刷新
```

可选：清理历史配置备份（确认无需回滚后）：

```bash
ls ~/.config/opencode/opencode.jsonc.*-backup-*
# rm -f ~/.config/opencode/opencode.jsonc.*-backup-*
```

备份文件 owner 前缀：`shennong` / `nl2sql` / `openeuler-ops` / `xlite-perf-optimizer`。

---

## 四、卸载验证

```bash
# 1) plugin 数组中不应再有对应 file:// 条目
grep -n "dist/index.js" ~/.config/opencode/opencode.jsonc

# 2) skill 软链应已消失
ls -l ~/.config/opencode/skills/ | grep -E 'shennong|nl2sql|xlite|cool-agent|buddy-log|docker-diag|ops-maintenance' || echo "skills 已清理"

# 3) 神农 MCP 配置与端口
grep -n "crash-feature-matcher\|witty-log-detection" ~/.config/opencode/opencode.jsonc || echo "mcp 已清理"
ss -lntp | grep 12144 || echo "12144 端口已释放"

# 4) 命令应不存在
command -v shennong-configure nl2sql-agent openeuler-ops-agent xlite-perf-optimizer-configure || echo "命令已移除"

# 5) 缓存目录
ls ~/.cache/witty-agents/ 2>/dev/null || echo "缓存已清空"
```

用各命令自带的 status 也可确认（删包前执行）：

```bash
shennong-configure status --target=opencode
nl2sql-agent status
openeuler-ops-agent status
xlite-perf-optimizer-configure status
```

---

## 五、故障处理：已先删 npm 包（反注册命令丢失）

若已执行 `npm uninstall` 但没先 `remove`，手动清理：

1. 编辑 `~/.config/opencode/opencode.jsonc`：
   - 从 `plugin` 数组删除指向对应包的
     `file://.../node_modules/<包名>/dist/index.js` 整行；
   - 神农还要从 `mcp` 对象删除 `crash-feature-matcher`、`witty-log-detection`。
2. 删除失效 skill 软链（`ls -l` 显示 `-> .../node_modules/...` 且目标已不存在）：

   ```bash
   find ~/.config/opencode/skills -maxdepth 1 -xtype l -print   # 列出悬空软链
   find ~/.config/opencode/skills -maxdepth 1 -xtype l -delete  # 确认后删除
   ```

3. 神农服务仍在运行时按端口/进程停掉：

   ```bash
   # 找到并结束 SSE 服务进程
   fuser -k 12144/tcp 2>/dev/null || true
   ```

4. 删除缓存目录（同第三节各 agent 的 `~/.cache/witty-agents/<包名>`）。

> 自定义配置路径时，替换为对应环境变量指向的文件：
> `SHENNONG_OPENCODE_CONFIG` / `NL2SQL_OPENCODE_CONFIG` /
> `OPENEULER_OPS_OPENCODE_CONFIG` / `XLITE_OPENCODE_CONFIG`；
> skill 链接在该文件同级的 `skills/` 目录下。

---

## 六、速查表

| 动作 | 神农 | NL2SQL | openEuler Ops | xlite |
|---|---|---|---|---|
| 停服务 | `shennong-setup stop` | — | — | — |
| 反注册 | `shennong-configure remove --target=opencode` | `nl2sql-agent remove` | `openeuler-ops-agent remove` | `xlite-perf-optimizer-configure remove` |
| 卸包 | `npm uninstall -g witty-agent-shennong-online` | `npm uninstall -g witty-agent-nl2sql-online` | `npm uninstall -g witty-agent-openeuler-ops-online` | `npm uninstall -g witty-agent-xlite-perf-optimizer-online` |
| 清缓存 | `rm -rf ~/.cache/witty-agents/witty-agent-shennong-online` | `rm -rf ~/.cache/witty-agents/witty-agent-nl2sql-online` | — | — |
| skill 数 | 随包内置 | 1（软链） | 11（软链） | 8（软链） |
