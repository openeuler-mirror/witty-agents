# kernel-dataset Agent

内核数据集增量更新 Agent。周期性地（默认每 1 小时）从上游拉取 linux 与 openEuler 数据集的增量，
按数据根目录（`dataRoot`，默认 `/home/data`，可配置）下既有文件的目录结构与字段格式落盘，供下游分析使用。

**不做格式转换、不做内容加工、不重写已存在的文件。**

## 数据集

下表目录均相对数据根目录 `<dataRoot>`（默认 `/home/data`）：

| 数据集 | 本地目录 | 文件 | 上游 |
| --- | --- | --- | --- |
| linux-bugzilla | `<dataRoot>/linux/bugzilla` | `bugzilla_<id>.json` | bugzilla.kernel.org REST API（匿名） |
| linux-commit | `<dataRoot>/linux/commit` | `commit_<sha>.json` | api.github.com（torvalds/linux） |
| linux-email | `<dataRoot>/linux/email` | `data-BNN/indexes/<part>.html`、`data-BNN/raw/<part>/<page>.html`、`manifest.jsonl`、`state.json` | lkml.iu.edu MHonArc 归档 |
| openeuler-commit | `<dataRoot>/openEuler/commit` | `commit_<sha>.json` | api.gitcode.com（openeuler/kernel） |
| openeuler-issue | `<dataRoot>/openEuler/issue` | `issue_<number>.json` | api.gitcode.com（openeuler/kernel） |

## 安装与启动

```bash
npm install -g <包名>

kernel-dataset-setup install            # 准备运行目录（幂等，默认动作）
kernel-dataset-configure install        # 注册到 opencode（幂等，默认动作）
kernel-dataset-setup start              # 后台常驻，默认每 1 小时一轮
kernel-dataset-setup status             # 服务状态（JSON）
kernel-dataset-setup stop               # 停止服务
```

## 命令

### kernel-dataset-setup

```
install | check | run | start | status | stop
```

`install` / `check` / `run` / `start` 选项：

| 选项 | 说明 |
| --- | --- |
| `--once` | 只跑一轮后退出 |
| `--dataset <a,b>` | 只跑指定数据集 |
| `--limit <n>` | 每个数据集本轮最多写入 n 条（email 为每个 part 最多 n 页） |
| `--max-parts <n>` | email 本轮最多处理的 part 数（默认 4） |
| `--max-pages <n>` | 分页接口本轮最多翻 n 页 |
| `--since <ISO>` | 指定起始水位（回补历史时使用） |
| `--full` | 全量复核（重扫所有 part） |
| `--interval <ms>` | 常驻周期，默认 `3600000` |
| `--root <path>` | 数据根目录，覆盖配置文件与环境变量（内置默认 `/home/data`） |
| `--log-level <level>` | `debug` \| `info` \| `warn` \| `error` |

### kernel-dataset-configure

```
install | remove | status        # 支持 --target=opencode|all
```

## 运行机制

- **水位拉取**：每个数据集记录上次成功处理到的水位（ISO 时间），下一轮从水位续传；失败（含限流）不推进水位。
- **目录回补**：写入前比对本地已有文件，发现缺失即补；email 会扫 `raw/<part>/` 与上游索引比对，回补空洞页。
- **email 分片滚动**：新数据先追加到当前 `data-BNN`，超过条目数/字节数阈值后 **在 part 边界**
  新建 `data-B(n+1)`，同一个 part 不会被拆到两个分片。
- **增长的 part**：上游最新 part 每轮重扫索引取增量；其余 part 收齐后不再重扫（`--full` 可强制重扫）。
- **失败页**：索引里有链接但上游已删除的页记入 `failures.jsonl`，之后不再重复请求。

## 配置

优先级由低到高（后者覆盖前者）：

1. **内置默认值**：`dataRoot = /home/data`、`intervalMs = 3600000`
2. **包内示例配置** `<包目录>/config/datasets.json`（随包分发，升级会被覆盖，别在这里写机器专属路径）
3. **用户配置**（每台机器一份，升级不丢）：`$KERNEL_DATASET_CONFIG` >
   `$XDG_CONFIG_HOME/kernel-dataset-agent/datasets.json` > `~/.config/kernel-dataset-agent/datasets.json`
4. **环境变量**：`KERNEL_DATASET_ROOT`、`KERNEL_DATASET_INTERVAL_MS`、
   `KERNEL_DATASET_TOKEN_GITHUB` / `GITHUB_TOKEN`、`KERNEL_DATASET_TOKEN_GITCODE` / `GITCODE_TOKEN`、
   `KERNEL_DATASET_DATASETS`、`KERNEL_DATASET_DISABLE`、`KERNEL_DATASET_PAGE_SIZE`
5. **命令行**：`--root <path>`、`--interval <ms>`（只作用于本次进程）

配置文件内容（键都是可选的，按需覆盖）：

```json
{
  "dataRoot": "/home/data",
  "intervalMs": 3600000,
  "tokens": { "github": "", "gitcode": "" }
}
```

`check` 会输出当前生效的 `dataRoot`、`dataRootSource`（`default` / `package-config` / `user-config` / `env` / `cli`）
与 `configFiles`，可用来确认配置有没有生效：

```bash
kernel-dataset-setup check | jq '{dataRoot, dataRootSource, configFiles}'
```

### 在其他机器上复用

数据根目录可以指向任意路径，服务启动时会自动创建。推荐用用户配置（持久、升级不丢）：

```bash
mkdir -p ~/.config/kernel-dataset-agent
cat > ~/.config/kernel-dataset-agent/datasets.json <<'EOF'
{
  "dataRoot": "/data/kernel-dataset",
  "tokens": { "github": "", "gitcode": "" }
}
EOF

kernel-dataset-setup check         # 确认 dataRootSource = user-config
kernel-dataset-setup start         # 后台常驻服务会使用该根目录
```

临时切换（不改配置，只作用于本次进程）：

```bash
KERNEL_DATASET_ROOT=/data/kernel-dataset kernel-dataset-setup start
kernel-dataset-setup run --once --root /data/kernel-dataset
```

> 注意：`start` 的 `--root` 只作用于本次启动的常驻进程；`status` / `stop` 通过包内 `.runtime/` 定位进程，
> 与数据根目录无关。要长期生效请写用户配置。
> 另外水位状态按数据集 id 记在包内 `.runtime/state/<dataset>.json`，不按 `dataRoot` 区分；
> 若要在同一台机器上并行维护两个数据根目录，请分别安装两份包。切换根目录本身不会丢数据
> （首轮会按目录回补补齐缺口），只是会多跑一轮全量比对。

## 运行时文件

| 路径 | 说明 |
| --- | --- |
| `.runtime/kernel-dataset.pid.json` | 后台进程记录 |
| `.runtime/heartbeat.json` | 心跳（`status` 据此判定 `running/stale/starting`） |
| `.runtime/kernel-dataset.log` | 服务日志 |
| `.runtime/state/<dataset>.json` | 各数据集水位与累计计数 |

## 排障

- `status` 为 `stale`：进程存活但心跳超过 3 个周期未更新，看日志尾部确认是否卡在长请求，必要时 `stop` 后 `start`。
- `401/403`：Token 失效，更新用户配置 `~/.config/kernel-dataset-agent/datasets.json` 的 `tokens`
  （或包内 `config/datasets.json`）后再重启服务，也可用环境变量。
- 限流：本轮不推进水位，等下一轮；不要手工编辑 `.runtime/state/*.json`。