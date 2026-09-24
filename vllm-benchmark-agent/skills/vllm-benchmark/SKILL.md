---
name: vllm-benchmark
description: 按 benchmark.yaml 在已有 Ascend 容器中执行 vLLM 压测，分析吞吐、时延、SLO 与 NPU 指标；支持异常恢复和报告生成。
---

在用户工作目录使用 `vllm-benchmark`，不要切换到 npm 包目录。
先读 `benchmark.yaml`；配置不存在时从包内模板复制并根据用户目标填写。
用户要求按配置压测后执行 `vllm-benchmark run`，指定文件使用 `--config PATH`。
返回 ANALYZE 时按 `llm_prompt` 分析真实数据，再执行 `vllm-benchmark done` 完成清理。
查看进度用 `vllm-benchmark status` 或 `watch --once`。
只在返回 `needs_user_decision` 时解释阻塞原因，用户批准变更后执行 `resume`。
不要自行降低压测参数、创建容器或停止其他任务。复用的服务由运行器保留。
修改 YAML 后，仅在用户要求当前任务使用新配置时运行 `resume --reload-config`。
报告与运行数据默认位于 `~/.local/share/witty-agents/vllm-benchmark`；保留原始测量数据并标明缺失指标。
