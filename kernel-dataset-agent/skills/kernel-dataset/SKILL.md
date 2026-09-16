---
name: kernel-dataset
description: |
  维护内核数据集（默认 /home/data，可用 dataRoot 配置到任意路径）下 linux 与 openEuler 的增量更新：
  启动/巡检常驻采集服务，按既有目录格式把 bugzilla、linux commit、LKML 邮件、openEuler commit/issue
  的新增数据落盘，并在出现空洞或失败时回补（水位续传、目录回补、分片滚动）。
  用于数据更新、增量采集、水位回补、数据集巡检、email 分片、更换数据根目录等场景。
  Triggers: 更新数据集、增量更新、数据采集、水位、回补、kernel-dataset、bugzilla、LKML、openEuler issue、数据根目录、dataRoot。
---

# kernel-dataset

## 用途

把上游（bugzilla.kernel.org、GitHub、GitCode、LKML 归档）的新增数据，按数据根目录 `dataRoot`
（默认 `/home/data`，可配置到任意路径）下既有文件格式增量落盘到本地，供下游数据分析使用。
**不做格式转换，不做内容加工。**

## 何时使用

- 用户要求“更新数据集 / 拉取最新数据 / 增量更新”。
- 需要巡检采集服务是否正常（心跳、水位、上次成功时间）。
- 某个数据集出现空洞、失败或落后，需要回补。
- 需要把数据集落到别的路径（换机器、换挂载点）。

## 数据集与落盘格式

下表目录均相对数据根目录 `<dataRoot>`（默认 `/home/data`）：

| 数据集 | 目录 | 文件 | 关键字段 |
| --- | --- | --- | --- |
| linux-bugzilla | `<dataRoot>/linux/bugzilla` | `bugzilla_<id>.json` | `bug.last_change_time` 为水位 |
| linux-commit | `<dataRoot>/linux/commit` | `commit_<sha>.json` | `commit.committer.date` 为水位 |
| linux-email | `<dataRoot>/linux/email` | `data-BNN/indexes/<part>.html`、`data-BNN/raw/<part>/<page>.html`、`manifest.jsonl`、`state.json` | 以 part（`YYMM.N`）为进度单位 |
| openeuler-commit | `<dataRoot>/openEuler/commit` | `commit_<sha>.json` | `commit.committer.date` 为水位 |
| openeuler-issue | `<dataRoot>/openEuler/issue` | `issue_<number>.json` | `updated_at` 为水位 |

`manifest.jsonl` 每行一条记录，键顺序固定：
`part, page, url, file, bytes, message_id, subject, from, date, in_reply_to`。

## 命令

```bash
kernel-dataset-setup install                  # 准备运行目录（幂等，默认动作）
kernel-dataset-setup check                    # 校验 Node 版本 / 数据集类型 / 数据目录可写
kernel-dataset-setup run    [选项]            # 前台运行（--once 只跑一轮）
kernel-dataset-setup start  [选项]            # 后台常驻（默认每 1 小时一轮）
kernel-dataset-setup status                   # 服务状态（JSON）
kernel-dataset-setup stop                     # 停止服务

kernel-dataset-configure install              # 注册到 opencode（幂等，默认动作）
kernel-dataset-configure status               # 查看注册状态
kernel-dataset-configure remove               # 取消注册
```

`install` / `check` / `run` / `start` 支持的选项：`--once`、`--dataset <a,b>`、`--limit <n>`、
`--max-parts <n>`、`--max-pages <n>`、`--since <ISO>`、`--full`、`--interval <ms>`、`--root <path>`
（数据根目录，覆盖配置文件与环境变量，内置默认 `/home/data`）、`--log-level <level>`。

## 配置数据根目录

优先级由低到高：内置默认 `/home/data` → 包内 `<包目录>/config/datasets.json` →
用户配置 `$KERNEL_DATASET_CONFIG` 或 `~/.config/kernel-dataset-agent/datasets.json` →
环境变量 `KERNEL_DATASET_ROOT` → 命令行 `--root`。

```bash
mkdir -p ~/.config/kernel-dataset-agent
echo '{ "dataRoot": "/data/kernel-dataset" }' > ~/.config/kernel-dataset-agent/datasets.json

kernel-dataset-setup check    # 输出 dataRoot / dataRootSource / configFiles，用于确认生效来源
```

`dataRootSource` 取值：`default` \| `package-config` \| `user-config` \| `env` \| `cli`。
`status` / `stop` 通过包内 `.runtime/` 定位进程，与数据根目录无关。

## 运行机制

- **水位拉取**：每个数据集记录上次成功处理到的水位（ISO 时间），下一轮从该水位续传；
  失败（含限流）不推进水位，避免丢数据。
- **目录回补**：每轮在写入前先比对本地已有文件，发现缺失即补（email 还会扫 `raw/<part>/` 目录
  与上游索引比对，发现空洞页就补）。
- **email 分片滚动**：新数据先追加到当前 `data-BNN`；条目数/字节数超过阈值后 **在 part 边界**
  新建 `data-B(n+1)`，同一个 part 不会被拆到两个分片。
- **仍在增长的 part**：上游最新 part 每轮都会重扫索引取增量；其余 part 收齐后不再重扫（`--full` 可强制重扫）。
- **失败的页**：索引里有链接但上游已删除的页记入 `failures.jsonl`，之后不再重复请求。

## 状态与日志

- 服务状态：`<包目录>/.runtime/kernel-dataset.pid.json` + `.runtime/heartbeat.json`
- 日志：`<包目录>/.runtime/kernel-dataset.log`
- 数据集水位：`<包目录>/.runtime/state/<dataset>.json`
- 用户配置：`~/.config/kernel-dataset-agent/datasets.json`（或 `$KERNEL_DATASET_CONFIG`），
  键：`dataRoot`、`intervalMs`、`tokens`；包内 `config/datasets.json` 只作默认值。

## 常见排障

- `status` 为 `stale`：进程还在但心跳超过 3 个周期没更新，先看日志尾部确认是否卡在长请求；必要时 `stop` 后 `start`。
- `401/403`：Token 失效，更新用户配置 `~/.config/kernel-dataset-agent/datasets.json` 的 `tokens` 或设置
  `KERNEL_DATASET_TOKEN_GITHUB` / `KERNEL_DATASET_TOKEN_GITCODE` 后重启服务。
- 数据没落到预期目录：先看 `kernel-dataset-setup check` 的 `dataRoot` 与 `dataRootSource`，
  确认是配置层级被覆盖还是路径写错。
- 限流：本轮水位不推进，等下一轮；不要手工编辑 `.runtime/state/*.json`。
- 需要从很早的时间补齐：`kernel-dataset-setup run --once --dataset <id> --since <ISO>`。