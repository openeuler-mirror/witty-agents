只维护项目根目录 benchmark.yaml，不启动服务或执行压测。
按用户要求编辑，然后执行 `vllm-benchmark config` 校验，报告修改字段。
用户也可以直接用编辑器修改文件。

字段含义：
- model.path 为容器内模型路径；model.name 可作为模型标识。
- container.name 必须指向已有容器；runtime 为 docker 或 podman；无需 container.image。
- vllm.device 是物理 NPU 编号列表，tensor_parallel_size 必须匹配选卡数量。
- max_model_len、gpu_memory_utilization、extra_args 都实际用于服务启动和复用校验。
- benchmark.concurrency 为正整数列表，每个级别执行 requests 个请求。
- benchmark.request_rates 为可选的受控 QPS 扫描轴，优先级高于 concurrency；配合
  benchmark.max_concurrency 可同时限制在途并发。benchmark.request_rate 是单速率、对所有并发轮生效。
- benchmark.metric_percentiles 指定从 vllm bench 获取的分位数（默认 [50, 90, 99]）。
- slo.ttft_ms / slo.tpot_ms / slo.e2el_ms 为毫秒级 SLO，用于 goodput 与达标分析，
  设置后会传给 `vllm bench serve --goodput`。
- metrics.collect 指定需要的指标组，request_timeline 是服务级队列采样；server 组含
  prefill/decode/KV/preemption/prefix cache，gpu 组为 npu-smi 的 AICore/HBM 采样。
- report.output 相对路径基于数据目录（默认 ~/.local/share/witty-agents/vllm-benchmark，
  可用 VLLM_BENCHMARK_DATA_DIR 覆盖），不再基于项目根目录。

活动任务使用配置快照；编辑文件后，用户批准使用新配置才调用 resume --reload-config。
