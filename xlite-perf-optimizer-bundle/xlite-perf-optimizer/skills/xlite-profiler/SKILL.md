# xlite-profiler

## 用途

配置 xlite 的时间打点、聚合统计算子耗时，并输出结构化结果（JSON/CSV/Markdown）。

## 何时使用

- 优化前：收集基线 profiling。
- 优化后：收集优化后 profiling 以对比。
- 生成 HTML 报告前：提供数据。

## 输入

- 当前 xlite 源码路径。
- 需要开启的打点维度（per-op、per-layer、prefill/decode）。
- 测试命令或运行脚本。

## 输出

- `.xlite-opt/reports/profile-<ts>.json`
- `.xlite-opt/reports/profile-<ts>.csv`
- `.xlite-opt/reports/profile-<ts>.md`

## 执行步骤

1. **开启编译期打点（可选）**
   - 若需要更细粒度日志，重新编译：
     ```bash
     XLITE_DEBUG_ON=forward cmake -B build -S .
     cmake --build build -j
     ```

2. **运行测试并收集日志**
   - 执行用户或 agent 指定的性能测试命令。
   - 捕获 stdout/stderr 中的算子耗时行。

3. **解析与聚合**
   - 使用辅助脚本解析日志并生成 metrics JSON：
     ```bash
     python3 node_modules/xlite-perf-optimizer/helpers/parse-perf-log.py \
         .xlite-opt/reports/ascend-test-<ts>.log \
         -o .xlite-opt/reports/metrics-<ts>.json
     ```
   - 从日志中提取算子名、self 时间、调用次数。
   - 按算子名、层号、阶段聚合。

4. **输出结构化结果**
   - JSON：机器可读。
   - CSV：便于导入 Excel。
   - Markdown：便于对话展示。

## 工具

- `Bash`：运行编译与测试命令。
- Python / `awk`：解析日志并生成报告。

## 可配置项

- `XLITE_PROFILING_ENABLED=true/false`：是否自动开启打点。
- 聚合维度：`operator`、`layer`、`phase`。
- 输出格式：`json`、`csv`、`markdown`。

## 输出示例

```json
{
  "wall_ms": 10.21,
  "operators": [
    {"name": "XliteOpConv1dAndSiLU", "self_ms": 0.92, "calls": 18, "per_call_ms": 0.051}
  ]
}
```
