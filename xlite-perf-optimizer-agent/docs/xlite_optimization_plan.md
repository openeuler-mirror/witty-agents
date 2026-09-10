# xlite Qwen3.5-27B 性能优化计划（半个月冲刺版）

> **目标修正**：当前模型为 **Qwen3.5-27B**，当前 xlite full_mode 时延是原生 ACLGraph 的 **2 倍**。要求在半个月内让 xlite **比原生图模式快 10%**。  
> 按当前 profiling 单步 wall≈15.93ms 估算，若原生图≈8ms，目标需将 xlite 降至 **≤7.2ms**（降幅 ≥55%）。
> 源码参考：`/tmp/opencode/GVirt_2803/xlite`，分支 `qwen35_attention_l0_and_linear_state`。

---

## 1. 为什么现在会慢 2 倍？

从 profiling 看，耗时高度集中在 **线性注意力（Linear Attention / Gated DeltaNet）链路**：

| 当前问题 | 证据 | 影响 |
|----------|------|------|
| **Conv1dAndSiLU 异常慢** | 18 层线性 attention，每次 0.258ms，合计 **4.65ms（29%）** | 当前实现是按通用 prefill 写的，decode（seqlen=1）走同一条路径，大量 launch/同步/GM 搬运 overhead |
| **Transpose + Concat + SplitCol 纯搬运** | Transpose 1.38ms + Concat 0.90ms + SplitCol 0.79ms = **3.07ms（19%）** | 全是因为 conv 要 channels-first 布局、in-proj 权重每步重拼 |
| **线性 attention 链路碎片化** | L2Norm/Expand/BetaDecay/GDR/RmsNorm/SiluAndMul 合计 **~3.5ms** | decode 单 token 场景下分成 6+ 个小核，各自 launch + GM 往返 |
| **MHA 已经很快** | Attention/RopeCache/QkRmsNorm/SigmoidGateMul 合计 **~0.6ms（6 层）** | 主要慢的不是 MHA，是 18 层线性 attention |
| **Matmul 单价正常但次数多** | 96 次，单次 0.024ms | 总体量不大，但 decode M=1 时 launch 开销占比高 |

**结论**：核心矛盾不是模型适配错误，而是 **Qwen3.5 的线性 attention 在 xlite 里没有 decode 特化路径**，被当作长序列通用 conv 处理，导致 native ACLGraph 的 2 倍差距。

---

## 2. 半个月目标拆解

| 阶段 | 时间 | 关键交付 | 预计 wall 降幅 | 累计 wall |
|------|------|----------|----------------|-----------|
| 基线 | Day 0 | 复现 15.93ms，确认 native graph 基线 | - | **15.93ms** |
| **Phase 1：decode 卷积急救** | Day 1~4 | `Conv1dAndSiLU_Decode` + channel-last + 权重预拼 | ↓ 5~6ms | **~10ms** |
| **Phase 2：线性 attention decode 融合核** | Day 5~10 | 单核完成 conv→GDR→gate 全链路 | ↓ 2.5~3.5ms | **~7ms** |
| **Phase 3：MLP / 量化收尾** | Day 11~14 | MLP decode 融合或 W8A8，留 regression buffer | ↓ 0.5~1.5ms | **≤7.2ms（目标）** |

> 若 Phase 2 的融合核风险太高，可用 Phase 1 + Gate/GDR 分步融合作为兜底，预计做到 **8.5ms 左右**，接近 native，但仍需后续迭代才能快 10%。

---

## 3. 优化项（按优先级和风险排序）

### P0：Decode 特化 Conv1dAndSiLU（最大单点，预计降 3~4ms）

**问题**  
当前 `csrc/kernels/conv1d_and_silu.h` 是为任意 `seqLen ≤ 4096` 写的通用核：
- 每次调用都要把 `state[K]` 和 `input[S]` 从 GM 搬到 UB 做 bf16→fp32；
- 前 `K-1` 个位置走标量循环；
- 按 channels 分 block，decode 时并行度差。

对于 **decode 场景 `seqlen=1`**，其实只需要：
```
new_state = [old_state[1:], x]      # 滑动 1 位
cache_conv = dot(new_state, weight)  # K 个元素点积
out = SiLU(cache_conv)
```
这是一个几十 us 的向量操作，不是 258us。

**动作**
1. 新增 `conv1d_and_silu_decode_*` 核，仅处理 `batch * channels` 个单 token，每个 block 负责 `(batch, channel)` 二维分块。
2. 直接对 bf16 做 `vgather`/点积，仅在 SiLU 时局部转 fp32，去掉整段 GM→UB 的来回转换。
3. 在 `csrc/op.cpp::XliteOpConv1dAndSiLU` 中增加 `if (seqLen == 1) dispatch_decode_kernel` 分支。

**涉及文件**
- `csrc/kernels/conv1d_and_silu.h`（新增 decode 路径）
- `csrc/kernels/conv1d_and_silu_*_t.cpp`
- `csrc/op.cpp`

**预期收益**
- 18 层线性 attention：4.65ms → ~0.9ms，**省 3.5~3.8ms**。
- 若 seqlen>1 仍走原核，不影响 prefill。

**工期**：Day 1~4。

---

### P0：channel-last 布局，消除两次 Transpose_1_2（预计降 1.3ms）

**问题**
```cpp
// model.cpp::ForwardAttnLinear ~L754
XliteOpTranspose_1_2(mix3d, mixTrans);      // [B,S,C] -> [B,C,S]
XliteOpConv1dAndSiLU(...);                  // 要求 [B,C,S]
XliteOpTranspose_1_2(convOut, convSeq);     // [B,C,S] -> [B,S,C]
```
两次 Transpose self 合计 **1.38ms**。

**动作**
1. 让 `Conv1dAndSiLU` 直接支持 **channel-last `[B, S, C]`** 输入。
2. 对 decode 路径（S=1），channel-last 与 channel-first 数据等价，可直接跳过 transpose。
3. 对 prefill 路径，保持原 transpose 或并行实现 channel-last 通用核。

**涉及文件**
- `csrc/model.cpp::ForwardAttnLinear`
- `csrc/op.cpp::XliteOpConv1dAndSiLU`

**预期收益**
- 单步降 **1.0~1.38ms**。

**工期**：Day 2~5（与 P0-ConvDecode 并行）。

---

### P0：in-proj 静态权重预拼接 + SplitCol 视图化（预计降 1.5ms）

**问题**
```cpp
// model.cpp::ForwardAttnLinear ~L719
XliteOpConcat({W_qkv, W_z, W_b, W_a}, W);    // 0.90ms
XliteOpMatmul(hiddenState, W, projOut);
XliteOpSplitCol(projOut, {mixQkv,z,b,a});  // 0.79ms
```
权重在推理期间不变，每步重复 concat/split 是浪费。

**动作**
1. 在 `XModel::init()` 阶段将 4 个 in-proj 权重拼接成 `inProjWeight[layer]`，保存各段 offset。
2. 用 `XTensor::Init({B*S, qkvDim}, dtype, projOut.ptr + offset)` 生成 `mixQkv/z/b/a` 视图，**零拷贝**。
3. 删除 `XliteOpConcat` 与 `XliteOpSplitCol` 调用。

**涉及文件**
- `csrc/model.cpp`（新增成员 `inProjWeight`）
- `csrc/_C.cpp`（Python 侧 init 同步）

**预期收益**
- 单步降 **~1.5ms**（Concat 0.90 + SplitCol 0.79）。

**工期**：Day 1~3。

---

### P0：线性 attention decode 融合核（关键胜负手，预计降 2.5~3.5ms）

**目标**：把 decode 单 token 场景下的 6+ 个小核合并成一个 `XliteOpLinearAttnDecodeStep`。

**当前链路（线性层）**
```
in_proj matmul -> mixQkv,z,b,a
    -> SplitCol
    -> BetaDecay
    -> Transpose -> Conv1dAndSiLU -> Transpose
    -> SplitCol -> L2Norm x2 -> ExpandLinearHeads x2
    -> RecurrentGatedDeltaRule
    -> RmsNorm -> ConcatCol(z, core) -> SiluAndMul
    -> out_proj matmul
```

**融合后（线性层）**
```
in_proj matmul -> [mixQkv,z,b,a 视图]
    -> XliteOpLinearAttnDecodeStep(conv_state, ssm_state, weights, norm)
    -> gated
    -> out_proj matmul
```

**融合核内部（单 token）**
1. 读取 `mixQkv` 并更新 conv_state，计算 `conv_out = SiLU(dot(state, weight))`。
2. 按 offset 取出 Q/K/V。
3. 对 Q/K 做 L2Norm，并按 `nVHeads/nKHeads` 展开（可用 vector 重复或 reshape）。
4. 读取 `b/a/A_log/dt_bias`，在 kernel 内完成 `sigmoid`/`softplus`/`exp`，得到 `beta/g`。
5. 执行 recurrent gated delta rule：更新 ssm_state，输出 core。
6. 对 core 做 RMSNorm，读取 `z`，计算 `silu(z) * core` 得到 gated。
7. 写回新的 conv_state 与 ssm_state。

**涉及文件**
- 新增 `csrc/kernels/linear_attn_decode.h` + `*_t.cpp`
- `csrc/op.cpp` 新增 `XliteOpLinearAttnDecodeStep`
- `csrc/model.cpp::ForwardAttnLinear` 新增 `if (seqlen == 1)` 分支
- `csrc/model.h` 新增权重/offset 缓存

**预期收益**
- 消除 SplitCol、L2Norm、ExpandLinearHeads、BetaDecay、RecurrentGatedDeltaRule、RmsNorm、ConcatCol、SiluAndMul 中属于线性 attention 的部分。
- 单步降 **2.5~3.5ms**（融合核自身约 0.8~1.2ms，被替换的原子合计约 3.5~4.5ms）。

**风险与兜底**
- **风险**：核比较大，UB 布局、精度对齐、head 展开处理容易出错。
- **兜底**：若 Day 10 还无法合入，退而求其次做“BetaDecay + GDR 入口融合” + “Gate 段三合一”，仍可再降 1.5~2ms。

**工期**：Day 5~10（核心开发 + 精度对齐）。

---

### P1：MLP decode 融合（预计降 0.6~1.0ms）

**问题**
每层 MLP：
```
gate_up matmul -> silu_mul -> down matmul
```
当前 `SiluAndMul` 42 次调用 self 0.77ms，其中 24 次来自 MLP；中间结果还需要一次 GM 往返。

**动作**
1. 新增 decode 特化 `XliteOpMLPDecodeStep`：输入 `hidden`，在单个核内完成 `gate_up` gemv、silu_mul、`down` gemv，直接写回 residual-add 可用的输出。
2. 该核与 `ForwardLinear` 中的 matmul 路径二选一，仅在 `seqlen==1` 时启用。

**涉及文件**
- 新增 `csrc/kernels/mlp_decode.h` + `*_t.cpp`
- `csrc/op.cpp`
- `csrc/model.cpp::ForwardMLP`

**预期收益**
- 单步降 **0.6~1.0ms**。

**工期**：Day 10~13。

---

### P2：W8A8 量化（可选高杠杆，预计降 1~2ms）

**问题**
- bf16 matmul 受限于权重显存带宽；W8A8 可使权重带宽减半，同时 Cube 单元在 int8 上效率更高。
- xlite 已有 `XliteOpMatmulDeQuant`、`quant_dynamic`、`matmul_int8_t` 支持。

**动作**
1. 离线将 Qwen3.5-27B dense 权重（in_proj、out_proj、gate_up、down、o_proj）量化成 int8，生成 `quantBias` / `deqScale`。
2. 在 `load_weights` 中识别 int8 checkpoint，直接绑定到 `XModel` 的 quant 字段；或在 init 阶段对 bf16 权重动态量化并缓存。
3. 在 `ForwardLinear` 中根据权重 dtype 选择 `XliteOpMatmulDeQuant` 路径。

**涉及文件**
- `tests/models/qwen3_5.py::load_weights`
- `csrc/model.cpp` 中 `ForwardLinear`
- 新增量化转换脚本（参考 `tests/kernels/matmul_int8.py`、`quant_dyn.py`）

**预期收益**
- Matmul 2.29ms → ~1.2ms，并降低全局显存压力。
- 单步降 **1~2ms**。

**风险**
- 精度退化需评估；半个月内如果量化调参不可控，优先保 Phase 1/2。
- 建议作为 **保险项**：前面收益已达标时不做；若接近目标还差 1ms，则启动。

**工期**：Day 11~14（视 Phase 1/2 收益决定）。

---

### P2：小项清理（预计降 0.3~0.5ms）

1. **Gate 段三合一（RmsNorm + ConcatCol + SiluAndMul）**  
   若 Phase 2 融合核未能完全覆盖 gate，单独做此融合可省 0.5ms。
2. **减少 `GetTensor/PutTensor` 动态分配抖动**  
   对 decode 路径中固定 shape 的中间张量（如 `projOut`、`gated`、`attnOutput`）做 per-layer 预分配，避免每步从 tensor pool 分配/归还。
3. **关闭 XDEBUG 编译**  
   当前若按 debug 构建，`XDEBUG_PRINT*` 和 `gettensor` 日志会有 overhead；发布构建时务必不带 `XLITE_DEBUG_ON`。

---

## 4. 两周排期（建议）

| 天 | 核心任务 | 负责人建议 | 验收标准 |
|----|----------|-----------|----------|
| **1** | 复现 baseline；确认 native graph 时延；验证 `seqlen=1` 路径 | 任意同学 | 有稳定可复现的 wall 数据 |
| **2~3** | P0-3：in-proj 权重预拼 + SplitCol 视图化 | 模型/管线 | Concat/SplitCol 耗时归零，精度一致 |
| **2~4** | P0-1：Decode Conv1dAndSiLU 特化核 | 算子同学 | 单核精度通过，18 层 conv 总时 <1ms |
| **3~5** | P0-2：channel-last 消除 transpose | 算子+模型 | Transpose_1_2 在 decode 路径消失 |
| **6** | Phase 1 合入 + 端到端回归 | 全组 | wall 降至 **~10~11ms**，精度一致 |
| **7~9** | P0-4：LinearAttnDecodeStep 融合核开发 | 算子同学 | 单核与 eager 输出误差 <1e-3 |
| **10~11** | 融合核接入 `ForwardAttnLinear`，支持 `seqlen==1` 分支 | 模型同学 | wall 降至 **~7.5ms** |
| **12~13** | P1：MLP decode 融合 / P2：W8A8（二选一或并行） | 算子/量化 | 再降 0.5~1ms |
| **14** | 全量回归、精度对比、性能压测、输出最终报告 | 全组 | wall **≤7.2ms**，精度无损 |

---

## 5. 关键决策点

| 时间点 | 决策 | 触发条件 | 行动 |
|--------|------|----------|------|
| **Day 5 晚** | Phase 1 收益是否达标 | 若 wall 仍 >12ms | 排查 conv decode 核并行度/GM 搬运是否还有问题 |
| **Day 10 晚** | 融合核是否能合入 | 若融合核精度/性能未达标 | 启用兜底：BetaDecay+GDR 入口融合 + Gate 三合一，目标 wall≈8.5ms |
| **Day 12 晚** | 是否启用 W8A8 | 若 wall 在 7.5~8.0ms | 启动 W8A8 作为最后 1ms 杠杆；若已 ≤7.2ms 则不做 |

---

## 6. 验证方法

1. **单算子精度**：每个新核与 PyTorch eager 结果对比，bf16 相对误差 `<1e-3`，绝对最大误差 `<1e-2`。
2. **端到端精度**：固定 prompt + temperature=0，对比优化前后 token 序列；长 prompt（4k/8k）做 perplexity 对比，相对变化 `<0.5%`。
3. **性能指标**：
   - `wall(ms)`、`tpot(ms/token)`、`throughput(tokens/s)`
   - 每完成一个优化项重新跑一次 profiling，确认对应算子小时且未引入新瓶颈。
4. **分场景验证**：
   - decode 单 token（主要目标）
   - prefill 短序列（128/512）
   - prefill 长序列（4k/8k）
   确保 decode 优化不恶化 prefill。

---

## 7. 风险与兜底

| 风险 | 影响 | 兜底 |
|------|------|------|
| 融合核开发超预期 | 无法按期合入 | 用分步融合兜底（conv decode + gate 三合一 + GDR 入口融合），做到接近 native |
| W8A8 精度不达标 | 无法作为最后杠杆 | 改做 MLP 融合 + 减少 tensor pool 抖动，再省 0.5~1ms |
| decode 核上线后 prefill 回归 | 长序列性能下降 | 保留原核作为 `seqlen>1` fallback，decode 单独走新核 |
| 半个月时间不足 | 目标无法完全达成 | 至少完成 Phase 1（预计 wall≈10ms），使 xlite 从 2x 差距收窄到 1.25x，为后续迭代奠基 |

---

## 8. 总结

要达到“比 native graph 快 10%”，**不能只做小算子调优，必须做 decode 路径的结构性优化**：

1. **P0-1**：Decode 特化 Conv1dAndSiLU，把 4.65ms 降到 1ms 以下。
2. **P0-2**：channel-last + 消除两次 Transpose，省 1.3ms。
3. **P0-3**：in-proj 权重预拼 + SplitCol 视图，省 1.5ms。
4. **P0-4**：线性 attention decode 全链路融合核，省 2.5~3.5ms。

完成以上四项，单步 wall 可从 **15.93ms 降至 7~8ms**，结合 MLP 融合或 W8A8 可稳进 **≤7.2ms**，实现比原生图模式快 10% 的目标。

> 本计划已更新并保存为 `/home/zjq/vllm_ascend_op/xlite_optimization_plan.md`。
