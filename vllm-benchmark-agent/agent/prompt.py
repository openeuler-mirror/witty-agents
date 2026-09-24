"""Presentation only; the orchestrator decides whether execution is blocked."""
import json


def render(gate, **data):
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if gate == "WAIT_USER_DECISION":
        return ("无法按本次配置继续执行。根据以下证据说明：具体阻塞原因、受影响配置、"
                "已尝试的处理，以及保持配置不变或最小变更的可行方案。只询问这个阻塞项。"
                "不要建议未经验证的可用端口或设备，不得擅自降参、抢占资源、安装依赖或停止已有服务。"
                "用户决定后调用 main.py resume 并传入用户批准的覆盖参数；若用户自行修改了 YAML，"
                "使用 resume --reload-config。配置原样重试用 resume；明确同意重跑当前轮才用 --retry-round。"
                "用户明确接受本轮部分指标才用 resume --accept-partial，报告标注不完整。正常步骤无需再次确认。\n" + payload)
    if gate == "ANALYZE":
        return ("基于以下实际运行配置、服务证据与有效指标输出性能报告。报告数据里 analysis 字段已包含"
                "归一化后的每轮指标、goodput、饱和点启发式和瓶颈分类；请结合它并自行核对，不要盲信分类。"
                "重点比较各轮（axis 为 concurrency 或 request_rate）的 Throughput / Goodput / TTFT P50/P90/P99 / "
                "TPOT P50/P90/P99 / queue / prefill / running / waiting / KV cache / preemption / NPU 利用率。"
                "TTFT breakdown 只能按均值近似：other/residual = client 均值 TTFT - server queue - server prefill，"
                "其中包含网络/frontend 开销和 vLLM 未暴露的 arrival→queue 间隙，P99 不可相加。"
                "判断瓶颈时区分：queue/scheduler 容量、prefill、prefill/decode 干扰、decode、KV pressure、"
                "CPU/frontend、通信；并给出“先调配置、再 profiler、最后改源码”的分级建议和需要的参数 sweep。"
                "缺失数据明确标为不可用，不得推断为零或正常。request_timeline 是服务级队列采样，不是单请求跟踪。"
                "若已生成 vllm_performance_*.png，请在报告中说明其路径与主要结论。"
                "样本偏少等统计局限只需提示，不要求重跑。给出后续优化建议但不改本次配置。"
                "输出报告后调用 main.py done；done 在 cleanup.stop_service=true 且服务由本次运行启动时"
                "关闭该服务并释放 NPU 锁，复用的已有服务保持运行。\n" + payload)
    return "环境检查完成，继续按配置执行，无需确认。\n" + payload
