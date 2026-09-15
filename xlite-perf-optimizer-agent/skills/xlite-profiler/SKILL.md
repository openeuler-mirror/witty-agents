---
name: xlite-profiler
description: |
  配置 xlite 三级时间打点（XProf serve 端到端逐相 / msprof 设备级时间线 /
  内核微基准隔离脚本），聚合统计算子耗时并输出 JSON/CSV/Markdown。
  用于获取性能数据、定位耗时算子与逐相（prefill/decode）分析。
  Triggers: 打点、profiling、性能统计、算子耗时、XProf、msprof。
---

# xlite-profiler

## 用途

配置 xlite 的时间打点、聚合统计算子耗时，并输出结构化结果（JSON/CSV/Markdown）。

本 skill 覆盖三级打点体系（按粒度从粗到细）：
1. **XProf(serve 端到端逐相打点，首选)** —— model.cpp 内置，prefill/decode 分相耗时；
2. **msprof(设备级时间线)** —— CANN 自带，内核级调度/AIC-AIV-MTE 占用分析；
3. **内核微基准打点（隔离脚本）** —— 单内核/单 stage 精确计时与逐 region 定位。

## 何时使用

- 优化前：收集基线 profiling。
- 优化后：收集优化后 profiling 以对比。
- 生成 HTML 报告前：提供数据。

---

## 一级:XProf(serve 逐相打点,model.cpp 内置)

### 开启方式

```bash
# 方式 1: 环境变量(serve 启动命令前加)
XLITE_PROF=1 XLITE_PROF_DUMP_EVERY=64 XLITE_PROF_OUT=/tmp/opencode/xlite_prof.json vllm serve ...

# 方式 2: 文件 flag(env 传不进 engine-core 子进程时的兜底)
touch /tmp/xlite_prof_enable   # 存在即开启
```

- `XLITE_PROF_DUMP_EVERY`(默认 100):每 N 个 forward step dump 一次并重置计数;
- `XLITE_PROF_OUT`(默认 `/tmp/xlite_prof.json`):**JSONL append**,每行一个窗口。

### 输出 schema

```json
{"steps":64,"total_dev_us":49841.4,"phases":[
  {"name":"lin_core_recur","count":3072,"dev_us":...,"host_us":...,
   "dev_us_per_occ":...,"host_us_per_occ":...}]}
```

- `dev_us`:aclrt event 在 stream 上夹取的真实设备耗时;`host_us`:host 侧 enqueue 耗时;
- **相是嵌套的**:`attn` 含 `lin_*`/`full_*` 子相,`ffn` 含 `mlp` —— 聚合时**不得跨层级求和**;
- `total_dev_us` 只覆盖模型 forward 段,与 TPOT 的差值即非模型开销(调度/sampling/host)。

### 分析方法(实证模式)

- dump 窗口 vs bench:512 output tokens + `DUMP_EVERY=64` → 8 个窗口;**window 0 含 prefill+63 步 decode,window≥1 是纯 decode**;
  - decode 逐步均值 = window≥1 的 `dev_us/steps`;
  - prefill ≈ window0 − 63 × decode 均值;
- **打点自身有开销**(实测 TTFT 598→703ms),优化前后对比必须在**同打点条件**下进行。

### 实证基线(2026-09-08, Qwen3.5-27B, 512/512, 1 prompt)

- decode/步:ffn(MLP) 29.3ms(58%,权重带宽 bound) + attn 19.7ms(含 lin_core 2.5ms,其中 recurrent 仅 0.88ms);
- prefill:lin_core_recur(recurrent 内核) 268ms / TTFT ≈ 38%,为第一瓶颈。

---

## 二级:msprof(MindStudio Profiling,设备级)

已验证可用:`/usr/local/Ascend/cann-9.0.1/bin/msprof`。

### 用法

```bash
# 包在隔离内核基准脚本外面(不要直接包整个 vllm serve,太重且与 ACL graph 冲突)
msprof --application="python3 /tmp/opencode/bench_v4.py" \
       --output=.xlite-opt/reports/msprof-<ts>
```

- 产出:kernel 级耗时表(op_stat)、step 时间线(step_trace)、AIC/AIV/MTE 各 pipe 占用;
- 适用:确认某内核内部的 pipe 利用(如 VEC barrier 风暴、MTE 气泡)、单内核热点;
- 与 XProf 的分工:XProf 回答"端到端里哪个相慢",msprof 回答"这个内核内部为什么慢"。

---

## 三级:内核微基准打点(隔离脚本模式)

### 基准脚本模式(bench_v4.py 实证)

```python
def bench(fn, iters=10, warm=3):
    for _ in range(warm): fn()
    torch.npu.synchronize()
    t = time.perf_counter()
    for _ in range(iters): fn()
    torch.npu.synchronize()
    return (time.perf_counter()-t)/iters*1e3   # ms
```

- 多 launch 流水线逐 stage 分解:对每个 stage 单独 bench(launch 间 host 同步,求和≈总耗时);
- **病态基线陷阱**:基线必须在生产精确 shape 下测(实证:recurrent 在 V=128 比特化快路径,V≤64 慢 2.6 倍;窄 shape 下的加速比结论可能是假象)。

### 逐 region 定位(精度/竞争类 bug)

- 对 wsA 等中间 buffer 按 region 快照(probe_chain.py 模式):CPU fp32 gold 链逐级对比,第一个发散的 region 即出错 stage;
- 竞争类 bug 特征:坏值位置固定(如最后一行尾部)、幅值跨进程随机(UB/OOB 残留)、同 build 多次运行结果不同。

---

## 原通用流程(日志解析路径)

1. **开启编译期打点(可选)**
   ```bash
   XLITE_DEBUG_ON=forward cmake -B build -S .
   cmake --build build -j
   ```

2. **运行测试并收集日志**
   - 执行用户或 agent 指定的性能测试命令。
   - 捕获 stdout/stderr 中的算子耗时行。

3. **解析与聚合**
   ```bash
   python3 node_modules/xlite-perf-optimizer/helpers/parse-perf-log.py \
       .xlite-opt/reports/ascend-test-<ts>.log \
       -o .xlite-opt/reports/metrics-<ts>.json
   ```

4. **输出结构化结果**:JSON / CSV / Markdown。

## 输入

- 当前 xlite 源码路径。
- 需要开启的打点维度(per-op、per-layer、prefill/decode)。
- 测试命令或运行脚本。

## 输出

- `.xlite-opt/reports/profile-<ts>.json` / `.csv` / `.md`
- XProf:`$XLITE_PROF_OUT`(JSONL)
- msprof:`.xlite-opt/reports/msprof-<ts>/`

## 可配置项

- `XLITE_PROFILING_ENABLED=true/false`:是否自动开启打点。
- 聚合维度:`operator`、`layer`、`phase`。
- 输出格式:`json`、`csv`、`markdown`。
