---
name: xlite-analyzer
description: |
  读取 xlite 源码结构、profiling 数据与模型配置，识别算子级与流程级性能瓶颈
  （如 decode 路径被按 prefill 处理、可融合链路），输出 bottleneck_report.json、
  process_bottleneck.md、optimization_candidates.md。性能优化任务的第一步。
  Triggers: 性能优化、瓶颈分析、profiling 分析、识别瓶颈、优化候选。
---

# xlite-analyzer

## 用途

读取 xlite 代码库、profiling 数据、模型配置，识别**算子级**与**流程级**性能瓶颈，输出结构化的瓶颈分析报告。

## 何时使用

收到性能优化任务后，**第一步**调用本 skill。

## 输入

- 项目根目录（默认当前工作目录）。
- profiling 数据文件路径，或最近一次运行结果目录（如 `.xlite-opt/reports/`）。
- 模型名称/配置文件（如 `Qwen3.5-27B`，或 `config.json` 路径）。

## 输出

- `.xlite-opt/journal/<ts>/bottleneck_report.json`
- `.xlite-opt/journal/<ts>/process_bottleneck.md`
- `.xlite-opt/journal/<ts>/optimization_candidates.md`

## 执行步骤

1. **定位源码结构**
   - 确认 `csrc/op.cpp`、`csrc/model.cpp`、`csrc/kernels/`、对应 `tests/models/*.py` 存在。
   - 读取 `doc/models.md`、`doc/feature_matrix.md` 获取模型支持状态。

2. **读取 profiling 数据**
   - 支持格式：Markdown 表格、CSV、JSON。
   - 提取字段：`算子名`、`self(ms)`、`占比`、`调用次数`、`单次(ms)`。
   - 按 `self(ms)` 降序排序，标记占用 >5% 的算子。

3. **算子级分析**
   - 对 Top 瓶颈算子，在 `csrc/` 中定位实现。
   - 检查是否存在：
     - 重复 GM 搬运 / transpose / concat / split；
     - 未针对 decode（seqlen=1）特化的通用核；
     - 静态权重每步重新拼接；
     - 可融合的连续小算子链。

4. **流程级分析**
   - 阅读 `csrc/model.cpp` 中 `ForwardAttnLinear`、`ForwardMLP`、`ForwardLayers*` 等管线函数。
   - 检查：
     - decode 与 prefill 是否走同一条路径；
     - 是否存在跨算子的冗余内存往返；
     - 是否存在可合并的连续阶段（如 conv + split + l2norm + GDR + gate）。
   - 输出流程瓶颈：哪个阶段耗时最高、哪个阶段 launch 次数最多。

5. **生成候选优化项**
   - 每个候选包含：问题描述、涉及文件、预期收益、风险、建议优先级。
   - 区分算子优化与流程重构。

## 工具

- `Read` / `Glob` / `Grep`：读取源码与 profiling 数据。
- `Bash`：解析 Markdown/CSV 并生成 JSON。

## 输出示例

```json
{
  "wall_ms": 15.93,
  "process_bottlenecks": [
    {"stage": "linear-attention-decode", "self_ms": 8.2, "ratio": 0.52, "issue": "未做 decode 特化"}
  ],
  "top_kernels": [
    {"name": "XliteOpConv1dAndSiLU", "self_ms": 4.65, "ratio": 0.29, "calls": 18, "per_call_ms": 0.258}
  ],
  "candidates": [
    {
      "id": "conv-decode",
      "type": "operator",
      "title": "Decode 特化 Conv1dAndSiLU",
      "files": ["csrc/kernels/conv1d_and_silu.h", "csrc/op.cpp"],
      "expected_ms": -3.5,
      "priority": "P0"
    },
    {
      "id": "linear-attn-fusion",
      "type": "process",
      "title": "线性 attention decode 全链路融合",
      "files": ["csrc/model.cpp::ForwardAttnLinear"],
      "expected_ms": -3.0,
      "priority": "P0"
    }
  ]
}
```

