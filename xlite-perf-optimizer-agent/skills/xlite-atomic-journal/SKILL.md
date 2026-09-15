---
name: xlite-atomic-journal
description: |
  原子修改记录器：每次源码修改前保存 before.patch/after.patch（或 .bak），
  测试通过标记 kept、失败或性能退化标记 rolled_back 并支持回滚。一次只改一个
  独立行为；无 wall/tpot/throughput 或 golden 数据禁止标记。
  Triggers: 原子修改、保存 patch、回滚、kept、rolled_back、修改记录。
---

# xlite-atomic-journal

## 用途

记录每一次原子代码修改的 `before.patch` 与 `after.patch`(或整文件 `.bak`)，并根据测试结果标记 `kept` 或 `rolled_back`，支持回滚。

## 核心原则(实证约定)

1. **原子粒度**:一次只改一个独立行为(一个根因/一处同步/一个参数);不捆 Batch 修改。
2. **改前必存**:任何源码修改前先保存快照,再动手。
3. **改后必测**:golden/精度测试 + 性能数据齐全前,不得标 `kept`;**没有 wall/tpot/throughput 或 golden 数据时禁止标记**。
4. **失败必退**:测试失败或性能退化,立即回滚并记 `rolled_back` + 原因。
5. **回归先隔离后归因**(实证教训):出现回归时,第一动作是 stash/回退做 A/B 二分,**不凭假设续改**;实证案例:pad-zero 补丁引入 B1S32 回归,A/B 重建"PASS 态"后仍失败 → 证明真根因是预存的 V→S 同步竞争,两个补丁都是无辜的。
6. **大段替换后校验结构**(实证教训):整块 edit 后跑括号深度检查(`depth==0` 且关键行深度正确),防止残留旧块/多删 `}`——实证事故:大段替换残留旧 a~/z 块导致 20 个编译错误。
7. **同步敏感内核的结构保守**:在手工管理 pipe flag 的 AscendC 热循环里,优先改标量/地址/系数,避免新增 vector op、分支、pipe flag——任何结构变化都可能被编译器重排而暴露潜在竞争。
8. **竞争类 bug 的验证**:单次 PASS 不算数,同一 shape 至少连跑 3 次;并覆盖多 shape(对齐/非对齐/多 H)。

## 何时使用

- `[xlite-operator-dev]` 修改任何源码前:保存 before 快照。
- 修改完成后:保存 after 快照。
- 测试失败或性能退化时:执行回滚。

## 输入

- 修改描述(一句话)。
- 需要跟踪的文件路径列表。

## 输出

- `.xlite-opt/journal/<timestamp>-<slug>/`
  - `before.patch` / `after.patch`(或整文件 `*.bak`,见下)
  - `description.md` 或汇总 `NOTES.md`
  - `test-result.json`
  - `status.json`:`kept` / `rolled_back`

## 执行步骤

### 标准路径(工作树干净时):git patch

```bash
git diff -- <files> > .xlite-opt/journal/<ts>-<slug>/before.patch
# ... 修改 ...
git diff -- <files> > .xlite-opt/journal/<ts>-<slug>/after.patch
```

文件未被 git 追踪时:`git diff --no-index /dev/null <file> > before.patch`。

### 变体路径(工作树已有大量未提交修改时):整文件 .bak

实证用法——当目标文件已包含大量未提交的在研修改,`git diff` 无法隔离本次变更时:

```bash
cp <file> .xlite-opt/journal/<ts>-<slug>/<name>.bak   # 改前
# ... 修改 ...
# 回滚:cp 回去即可
```

配合一个累计 `NOTES.md` 逐项记录:`修复 N (kept/rolled_back): 现象 / 根因 / 证据 / 数据`。

### 标记 kept

```json
{"status": "kept", "reason": "wall 15.93ms -> 10.2ms; golden 6 shape PASS"}
```

### 回滚

```bash
git apply -R .xlite-opt/journal/<ts>-<slug>/after.patch   # 或 cp .bak 覆盖
```

回滚后必须**复跑 golden 确认**工作目录状态正确,再写 `status.json`:

```json
{"status": "rolled_back", "reason": "精度误差 3e-2 超过阈值"}
```

## 工具

- `Bash`:生成/应用 patch、`cp` 快照、括号深度校验。
- `Write`:创建 `description.md` / `status.json` / `NOTES.md`。

## 约束

- 只回滚通过本 journal 产生的修改。
- 回滚后必须确认工作目录无残留修改(复跑测试验证)。
- 保留的 journal 数量超过 `XLITE_MAX_ROLLBACK`(默认 10)时,自动删除最旧的 `rolled_back` 记录。
