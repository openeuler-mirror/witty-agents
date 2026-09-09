# xlite-gitcode-runner

## 用途

将本地 xlite 修改推送到 GitCode 仓库，由远端 CI/NPU 环境运行测试；用户手动将测试结果贴回后，Agent 解析并继续优化。

## 何时使用

- 本地没有昇腾 NPU / 容器环境时。
- 用户明确选择 gitcode 测试模式时。
- `[xlite-ascend-runner]` 无法识别到可用容器且 `XLITE_TEST_MODE=gitcode` 时。

## 输入

- 本地 xlite 项目目录（默认当前工作目录）。
- GitCode 仓库地址与目标分支（默认从 git remote 读取）。
- 用户手动粘贴的测试结果文本或日志文件。

## 输出

- `.xlite-opt/reports/gitcode-push-<ts>.json`：推送记录。
- `.xlite-opt/reports/gitcode-result-<ts>.json`：解析后的测试结果。

## 执行步骤

### 1. 准备分支

```bash
git checkout -b xlite-opt-<timestamp>
```

### 2. 提交原子修改

> 仅在本 skill 中允许创建临时测试分支与提交；本地容器测试模式下不应执行 git commit/push。

只提交当前 Agent 产生的优化改动。执行前向用户确认：

```text
将创建临时测试分支 xlite-opt-<timestamp> 并推送，是否继续？
```

确认后执行：

```bash
git checkout -b xlite-opt-<timestamp>
git add -A
git commit -m "[xlite-perf-optimizer] <优化描述>"
```

### 3. 推送到 GitCode

```bash
git push origin xlite-opt-<timestamp>
```

### 4. 提示用户运行测试

向用户输出：

```text
已推送分支：xlite-opt-<timestamp>
请在该分支的 CI/NPU 环境中执行性能测试，然后将测试结果（profiling 日志、wall/tpot/throughput）粘贴给我。
```

### 5. 解析用户输入

用户返回测试结果后：

- 提取关键指标：`wall(ms)`、`tpot(ms/token)`、`throughput(tokens/s)`。
- 与基线对比，计算变化百分比。
- 输出 `gitcode-result-<ts>.json`。

### 6. 反馈给工作流

- 若性能提升：标记为 `kept`，继续下一步优化或生成 HTML 报告。
- 若性能退化或失败：调用 `[xlite-atomic-journal]` 回退本地修改。

## 工具

- `Bash`：`git checkout`、`git commit`、`git push`。
- 对话：等待用户粘贴测试结果。
- `Write`：保存解析后的 JSON。

## 环境变量

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `XLITE_GITCODE_REMOTE` | `origin` | 推送目标 remote |
| `XLITE_TEST_MODE` | `auto` | `auto` / `container_build` / `container_reuse` / `gitcode` |

## 注意事项

- 提交信息统一使用 `[xlite-perf-optimizer]` 前缀，便于识别。
- 不强制推送；如果用户环境未配置 gitcode 权限，提示用户手动 push。
- 回退时只回退本地 commit，不删除远端分支（避免误删）。
