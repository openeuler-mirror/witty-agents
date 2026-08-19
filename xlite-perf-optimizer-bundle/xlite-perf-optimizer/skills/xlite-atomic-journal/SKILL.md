# xlite-atomic-journal

## 用途

记录每一次原子代码修改的 `before.patch` 与 `after.patch`，并根据测试结果标记 `kept` 或 `rolled_back`，支持回滚。

## 何时使用

- `[xlite-operator-dev]` 修改任何源码前：保存 `before.patch`。
- `[xlite-operator-dev]` 修改完成后：保存 `after.patch`。
- 测试失败或性能退化时：执行回滚。

## 输入

- 修改描述（一句话）。
- 需要跟踪的文件路径列表。

## 输出

- `.xlite-opt/journal/<timestamp>-<slug>/`
  - `before.patch`
  - `after.patch`
  - `description.md`
  - `test-result.json`
  - `status.json`：`kept` / `rolled_back`

## 执行步骤

### 保存 before patch

```bash
git diff -- <files> > .xlite-opt/journal/<ts>-<slug>/before.patch
```

如果文件尚未被 git 追踪，使用：

```bash
git diff --no-index /dev/null <file> > .xlite-opt/journal/<ts>-<slug>/before.patch
```

### 保存 after patch

```bash
git diff -- <files> > .xlite-opt/journal/<ts>-<slug>/after.patch
```

### 标记 kept

写入 `status.json`：

```json
{"status": "kept", "reason": "wall 15.93ms -> 10.2ms"}
```

### 回滚

```bash
git apply -R .xlite-opt/journal/<ts>-<slug>/after.patch
```

然后写入 `status.json`：

```json
{"status": "rolled_back", "reason": "精度误差 3e-2 超过阈值"}
```

## 工具

- `Bash`：生成 patch、应用 patch、读写 status。
- `Write`：创建 `description.md` 与 `status.json`。

## 约束

- 只回滚通过本 journal 产生的 patch。
- 回滚后必须确认工作目录干净，无残留修改。
- 保留的 journal 数量超过 `XLITE_MAX_ROLLBACK`（默认 10）时，自动删除最旧的 `rolled_back` 记录。
