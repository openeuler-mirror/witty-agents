---
name: xlite-complexity-estimator
description: |
  建立单算子时间复杂度模型与端到端 latency 公式，按用户给定的
  (input_tokens, output_tokens, batch_size) 估算推理耗时并与实际 profiling 对比，
  输出 complexity_report.json。用于优化前评估理论收益、优化后验证偏差。
  Triggers: 复杂度估算、latency 估算、理论耗时、端到端时间模型。
---

# xlite-complexity-estimator

## 用途

基于当前 xlite 代码结构，建立单算子时间复杂度模型与端到端 latency 公式。根据用户给定的 `(input_tokens, output_tokens, batch_size)` 估算推理耗时，并与实际 profiling 对比。

## 何时使用

- 优化方案设计前：评估理论收益。
- 优化完成后：验证实际耗时与理论模型的偏差。
- 生成 HTML 报告时：提供复杂度估算图表。

## 输入

- 当前 xlite 模型配置（hidden size、layers、heads、attention type、linear dims 等）。
- 单算子 profiling 基线（用于拟合系数）。
- 用户指定的 `(input_tokens, output_tokens, batch_size)`。

## 输出

- `.xlite-opt/journal/<ts>/complexity_report.json`
- `.xlite-opt/journal/<ts>/complexity_estimation.md`

## 执行步骤

1. **建立单算子模型**
   - 从源码和 profiling 中提取关键变量：
     - `Conv1dAndSiLU`: `B, C, S, K`
     - `RecurrentGatedDeltaRule`: `B, H, S, kDim, vDim`
     - `XliteOpMatmul`: `M, N, K`
   - 用 profiling 数据拟合每个算子的系数。

2. **端到端公式**
   - Prefill：
     ```
     T_prefill = embed + Σ_layer(T_attn_prefill + T_ffn_prefill + T_norm_add) + head
     ```
   - Decode（单步）：
     ```
     T_decode_step = embed + Σ_layer(T_attn_decode + T_ffn_decode + T_norm_add) + head
     T_decode_total = T_prefill + output_tokens * T_decode_step
     ```

3. **代入估算**
   - 将 `input_tokens` 映射到 prefill 的 seqlen。
   - 将 `output_tokens` 映射到 decode 步数。
   - `batch_size` 影响 `B` 和 `M`。

4. **偏差分析**
   - 对比估算值与实际 profiling，输出偏差最大的算子，作为下一步优化重点。

## 工具

- `Read` / `Grep`：读取模型配置与算子实现。
- `Bash` / Python：执行公式计算与系数拟合。

## 输出示例

```json
{
  "input_tokens": 128,
  "output_tokens": 1024,
  "batch_size": 4,
  "estimated_ms": {
    "prefill": 45.2,
    "decode_step": 7.2,
    "total": 7418.6
  },
  "per_operator_ms": {
    "XliteOpConv1dAndSiLU": 0.9,
    "XliteOpMatmul": 1.1
  },
  "vs_baseline_ms": 15.93
}
```
