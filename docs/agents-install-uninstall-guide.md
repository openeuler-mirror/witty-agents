# Witty Agents 安装与卸载指南（四个 Agent）

适用 online npm 包（2026-09-15 发布版本）：

| Agent | npm 包 | 版本 |
|---|---|---|
| 神农崩溃分析 | `witty-agent-shennong-online` | 0.10.6 |
| NL2SQL | `witty-agent-nl2sql-online` | 0.2.0 |
| openEuler 运维 | `witty-agent-openeuler-ops-online` | 2.0.0 |
| xlite 性能优化 | `witty-agent-xlite-perf-optimizer-online` | 0.2.0 |

环境：openEuler / Linux（macOS 同样适用）。所有注册信息写入
`~/.config/opencode/opencode.jsonc`，skill 以**符号链接**落在
`~/.config/opencode/skills/`。

## 统一命令约定

四个 Agent 全部采用神农同款**双命令**结构：

| 命令 | 职责 |
|---|---|
| `<agent>-setup install` | 准备本机依赖：venv / 模型 / 在线 Skills / 起服务所需环境（**不写 opencode 配置**） |
| `<agent>-configure install --target=opencode` | 注册 Agent（plugin + skill 软链，幂等） |
| `<agent>-configure remove --target=opencode` | 反注册（幂等，自动备份配置） |
| `<agent>-configure status` | 查看注册状态（JSON） |
| `<agent>-setup check` | 只读环境/完整性校验 |

四个命令名：`shennong-setup` / `shennong-configure`、
`nl2sql-setup` / `nl2sql-configure`、
`openeuler-ops-setup` / `openeuler-ops-configure`、
`xlite-perf-optimizer-setup` / `xlite-perf-optimizer-configure`。

> 旧的 `nl2sql`、`nl2sql-agent`、`openeuler-ops-agent`、`xlite-opt-init`、
> `xlite-perf-optimizer-configure configure/register` 已随本版本移除，
> 不保留别名，请直接改用新命令。

---

## 一、装了什么（卸载前必读）

安装并注册后，系统里存在以下内容，卸载需逐一清理：

1. **npm 包本体**：全局（`$(npm root -g)/<包名>`）或项目 `node_modules/<包名>`。
2. **OpenCode 插件注册**：`opencode.jsonc` 的 `plugin` 数组中一条
   `file://.../dist/index.js`；神农另有 `mcp` 配置两项。
3. **skill 符号链接**：`~/.config/opencode/skills/<skill>` → 包内 skill 目录。
4. **Python 虚拟环境 / 模型缓存**（神农、NL2SQL）：`~/.cache/witty-agents/<包名>/`。
5. **常驻服务**（神农 SSE MCP：`127.0.0.1:12144`；NL2SQL Web：`127.0.0.1:8199`）。
6. **配置备份文件**：每次改配置自动生成 `opencode.jsonc.<owner>-backup-<时间戳>`。
7. **历史遗留**（仅用过旧引导才会有）：
   - xlite：旧版 `xlite-opt-init` 复制的 `~/.config/opencode/agents/xlite-perf-optimizer/`
     与实体 skill 目录、项目 `opencode.jsonc` 片段。
   - ops：`openeuler-ops-setup install` 经 skillhub 安装的 `~/.config/opencode/skills/@chuangyinbot-boop/`。

> 卸载顺序固定为：**停服务 → 反注册（删 plugin + skill 链接）→ npm 卸载 → 清缓存/残留**。
> 若先删 npm 包，反注册命令会丢失，需按第五节手动清理。

---

## 二、安装流程

统一三步：**① 装包 → ② setup 准备依赖（无后端者为 no-op/可选）→ ③ configure 注册并链接 skill → 重启 OpenCode**。

### 神农

```bash
npm install -g witty-agent-shennong-online
shennong-setup install                      # 建 3 个 venv、下载 OCR 模型、准备 MCP
shennong-configure install --target=opencode
```

### NL2SQL

```bash
npm install -g witty-agent-nl2sql-online
nl2sql-setup install                        # 建共享 venv、装后端依赖（~/.cache/witty-agents/...）
nl2sql-configure install --target=opencode  # 注册 + 软链 skill

# 可选：交互配置 LLM/rag/ES/Web（写 .env 与 configs/datasources.yaml，CI 管道下取默认值）
nl2sql-setup init
# 后台启动 Web（pid/日志在包内 .runtime/），然后浏览器打开 http://127.0.0.1:8199
nl2sql-setup start
nl2sql-setup status                         # 或 curl http://127.0.0.1:8199/api/health
nl2sql-setup stop
# 备选一键编排（自带 ES/rag 检查，包内自建 .venv，前台运行）：scripts/start_all.sh
```

### openEuler Ops（无后端）

```bash
npm install -g witty-agent-openeuler-ops-online
openeuler-ops-setup install                 # 可选：装 skillhub 并在线拉取 Skill（失败自动降级）
openeuler-ops-configure install --target=opencode
```

### xlite 性能优化（无后端）

```bash
npm install -g witty-agent-xlite-perf-optimizer-online
xlite-perf-optimizer-setup install          # 无后端依赖，校验包完整性后直接成功
xlite-perf-optimizer-configure install --target=opencode
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
# (1) 停止后台 Web 并反注册
nl2sql-setup stop
nl2sql-configure remove

# (2) 卸载 npm 包
npm uninstall -g witty-agent-nl2sql-online

# (3) 清理后端 venv
rm -rf ~/.cache/witty-agents/witty-agent-nl2sql-online
```

自定义缓存位置：`NL2SQL_VENV_CACHE/<包名>/venvs/nl2sql`。
包内 `.runtime/`（pid/日志）随 npm 卸载一并删除；手工配置过的 `.env` 也在包目录内。

### 3. openEuler Ops

```bash
# (1) 反注册并移除全部 11 个 skill 软链
openeuler-ops-configure remove

# (2) 卸载 npm 包
npm uninstall -g witty-agent-openeuler-ops-online
```

无 venv / 无服务。仅在你用过 `openeuler-ops-setup install` 的 skillhub 在线安装时，再清理：

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
ss -lntp | grep -E '12144|8199' || echo "12144/8199 端口已释放"

# 4) 旧命令应不存在（新命令为各 <agent>-setup / <agent>-configure）
command -v shennong-setup nl2sql-setup openeuler-ops-setup xlite-perf-optimizer-setup >/dev/null || echo "包已卸载"

# 5) 缓存目录
ls ~/.cache/witty-agents/ 2>/dev/null || echo "缓存已清空"
```

删包前可用各命令自带的 status 确认：

```bash
shennong-configure status --target=opencode
nl2sql-configure status
nl2sql-setup status                # NL2SQL Web 服务状态
openeuler-ops-configure status
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

3. 服务仍在运行时按端口/进程停掉：

   ```bash
   # 神农 SSE MCP / NL2SQL Web
   fuser -k 12144/tcp 2>/dev/null || true
   fuser -k 8199/tcp  2>/dev/null || true
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
| 准备依赖 | `shennong-setup install` | `nl2sql-setup install` | `openeuler-ops-setup install`（可选） | `xlite-perf-optimizer-setup install`（no-op） |
| 注册 | `shennong-configure install --target=opencode` | `nl2sql-configure install --target=opencode` | `openeuler-ops-configure install --target=opencode` | `xlite-perf-optimizer-configure install --target=opencode` |
| 反注册 | `shennong-configure remove --target=opencode` | `nl2sql-configure remove` | `openeuler-ops-configure remove` | `xlite-perf-optimizer-configure remove` |
| 状态 | `shennong-configure status` | `nl2sql-configure status` / `nl2sql-setup status` | `openeuler-ops-configure status` | `xlite-perf-optimizer-configure status` |
| 停服务 | `shennong-setup stop` | `nl2sql-setup stop` | — | — |
| 卸包 | `npm uninstall -g witty-agent-shennong-online` | `npm uninstall -g witty-agent-nl2sql-online` | `npm uninstall -g witty-agent-openeuler-ops-online` | `npm uninstall -g witty-agent-xlite-perf-optimizer-online` |
| 清缓存 | `rm -rf ~/.cache/witty-agents/witty-agent-shennong-online` | `rm -rf ~/.cache/witty-agents/witty-agent-nl2sql-online` | — | — |
| skill 数 | 随包内置 | 1（软链） | 11（软链） | 8（软链） |

## vLLM Benchmark

vLLM 压测 Agent 使用同样的双命令契约：`vllm-benchmark-setup install/check` 和 `vllm-benchmark-configure install/remove/status`。目前从本地构建的 online tgz 安装，详见 [安装、配置及卸载说明](../vllm-benchmark-agent/README.md)。
