"""深度分析链构建 — 从宕机特征提取事件时间线、崩溃传播链与源码线索。

为 LLM 的 analysis[] 推理提供结构化输入, 支撑 "先分析后判定" 的诊断流程。
输出为数据字段 (event_timeline / propagation_chain / source_clues), 供根因推理使用;
注意这些是数据字段, 不是 reasoning_flow 的 stage 取值 (stage 用 stack/hypothesis/path_analysis/internal/community/commit/source_compare/conclusion)。
"""

import logging
import re

logger = logging.getLogger(__name__)

# dmesg 行首时间戳, 如 "[  123.456789] "
_TIMESTAMP_RE = re.compile(r"\[\s*(\d+\.\d+)\]")

# 已知内存释放函数 (用于 UAF 传播检测)
FREE_FUNCS = frozenset({
    "kfree", "vfree", "kvfree", "free_pages", "free_skb", "kfree_skb",
    "dev_kfree_skb", "dev_kfree_skb_any", "dev_kfree_skb_irq",
    "mlx5e_free_rq", "mlx5e_free_sq", "kfree_rcu", "call_rcu",
    "kmem_cache_free", "dma_free_coherent",
})

# 已知内存分配函数
ALLOC_FUNCS = frozenset({
    "kmalloc", "kzalloc", "kcalloc", "vmalloc", "alloc_pages",
    "alloc_skb", "__alloc_skb", "netdev_alloc_skb",
    "kmem_cache_alloc", "dma_alloc_coherent",
})

# 写类操作函数特征 (用于数据污染推断)
_WRITE_HINTS = ("_set_", "_write", "_store", "_update", "_fill", "_copy", "memcpy", "memset")

# NULL 解引用相关 bug_key
_NULL_DEREF_KEYS = ("null", "unable to handle kernel null")

# 函数名前缀 → 源码目录映射
_FUNC_FILE_HINTS: list[tuple[str, str]] = [
    ("mlx5e_", "drivers/net/ethernet/mellanox/mlx5/core/"),
    ("mlx5_", "drivers/net/ethernet/mellanox/mlx5/core/"),
    ("tcp_", "net/ipv4/"),
    ("udp_", "net/ipv4/"),
    ("ip_", "net/ipv4/"),
    ("inet_", "net/ipv4/"),
    ("ipv6_", "net/ipv6/"),
    ("nf_", "net/netfilter/"),
    ("nft_", "net/netfilter/"),
    ("xfrm_", "net/xfrm/"),
    ("skb_", "net/core/"),
    ("__skb_", "net/core/"),
    ("netif_", "net/core/"),
    ("dev_", "net/core/"),
    ("xfs_", "fs/xfs/"),
    ("ext4_", "fs/ext4/"),
    ("btrfs_", "fs/btrfs/"),
    ("nfs_", "fs/nfs/"),
    ("fuse_", "fs/fuse/"),
    ("nvme_", "drivers/nvme/"),
    ("scsi_", "drivers/scsi/"),
    ("blk_", "block/"),
    ("__blk_", "block/"),
    ("mmc_", "drivers/mmc/"),
    ("virtio_", "drivers/virtio/"),
    ("kvm_", "arch/x86/kvm/"),
    ("__kvm_", "arch/x86/kvm/"),
    ("amdgpu_", "drivers/gpu/drm/amd/amdgpu/"),
    ("i915_", "drivers/gpu/drm/i915/"),
    ("kmem_", "mm/"),
    ("__kmalloc", "mm/"),
    ("vmalloc", "mm/"),
    ("free_pages", "mm/"),
    ("alloc_pages", "mm/"),
    ("kfree", "mm/"),
    ("rcu_", "kernel/rcu/"),
    ("call_rcu", "kernel/rcu/"),
    ("kfree_rcu", "kernel/rcu/"),
]

# 关键词 → 时序图参与者(泳道)映射, 按优先级排列
_ACTOR_RULES: list[tuple[tuple[str, ...], str]] = [
    (("crash at", "kernel crash", "panic", "general protection", "bug:"), "崩溃路径"),
    (("mlx5", "mlx4", "ice_", "i40e", "igb", "ixgbe", "bnx", "tg3", "驱动",
      "cqe", "nic ", "ethernet", "收包", "发包"), "网卡驱动"),
    (("tcp_", "udp_", "inet_", "ip_", "gro", "skb", "sock", "协议栈",
      "netif", "napi"), "网络协议栈"),
    (("softirq", "irq", "硬中断", "软中断", "net_rx", "hrtimer"), "内核软中断"),
    (("sched", "pick_next", "schedule", "rq->", "调度"), "调度器"),
    (("xfs", "ext4", "btrfs", "nfs", "vfs", "文件"), "文件系统"),
    (("nvme", "scsi", "blk_", "block", "磁盘"), "块设备"),
]

# 来源兜底泳道 (无法按内容归类时)
_SOURCE_FALLBACK_ACTOR = {
    "dmesg": "系统日志观测",
    "calltrace": "调用路径",
    "inferred": "状态推断",
}


def _infer_actor(text: str, source: str) -> str:
    """根据事件文本关键词推断所属时序图参与者(泳道)"""
    low = (text or "").lower()
    for keywords, actor in _ACTOR_RULES:
        if any(k in low for k in keywords):
            return actor
    return _SOURCE_FALLBACK_ACTOR.get(source, "系统日志观测")


def _with_actor(event: dict) -> dict:
    """为时间线事件补充 actor/to_actor 字段"""
    event["actor"] = _infer_actor(event.get("event", ""), event.get("source", ""))
    return event


# 精确函数名 → 源码文件映射
_FUNC_EXACT_FILES: dict[str, str] = {
    "__do_softirq": "kernel/softirq.c",
    "do_softirq": "kernel/softirq.c",
    "process_backlog": "net/core/dev.c",
    "net_rx_action": "net/core/dev.c",
    "__netif_receive_skb": "net/core/dev.c",
    "netif_receive_skb": "net/core/dev.c",
    "ip_rcv": "net/ipv4/ip_input.c",
    "ip_local_deliver": "net/ipv4/ip_input.c",
    "tcp_v4_rcv": "net/ipv4/tcp_ipv4.c",
    "schedule": "kernel/sched/core.c",
    "__schedule": "kernel/sched/core.c",
    "kfree": "mm/slub.c",
    "kmalloc": "mm/slub.c",
    "kmem_cache_alloc": "mm/slub.c",
    "kmem_cache_free": "mm/slub.c",
}


def _as_str_list(value) -> list[str]:
    """容错转换为字符串列表 (非列表/非标量输入返回空列表)"""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    return []


def _infer_file_hint(func: str) -> str:
    """根据函数名命名约定推断可能的源码路径"""
    if func in _FUNC_EXACT_FILES:
        return _FUNC_EXACT_FILES[func]
    for prefix, path in _FUNC_FILE_HINTS:
        if func.startswith(prefix):
            return path
    return "unknown"


def _find_evidence_line(call_trace_text: str, func_a: str, func_b: str) -> str:
    """从原始调用栈文本中提取包含目标函数的原始行作为证据"""
    lines = (call_trace_text or "").splitlines()
    if len(lines) <= 1:
        # 单行文本 (如签名字符串拼接) 无逐帧原始行可提供
        return ""
    for target in (func_a, func_b):
        for line in lines:
            if target in line:
                return line.strip()[:200]
    return ""


def _build_event_timeline(anomaly: dict, crash_time: str, rip_function: str,
                          call_trace_text: str) -> list[dict]:
    """构建事件时间线: 异常前兆 → 错误升级 → 崩溃点"""
    timeline: list[dict] = []

    # 1) 崩溃前的异常事件 (dmesg 原始日志行)
    for event in _as_str_list(anomaly.get("pre_crash_events")):
        m = _TIMESTAMP_RE.search(event)
        timeline.append({
            "time": m.group(1) if m else "unknown",
            "event": event[:300],
            "source": "dmesg",
        })

    # 2) 重复错误模式 (错误升级信号)
    for err in _as_str_list(anomaly.get("repeated_errors")):
        m = _TIMESTAMP_RE.search(str(err))
        timeline.append({
            "time": m.group(1) if m else "unknown",
            "event": f"repeated error pattern: {str(err)[:200]}",
            "source": "dmesg",
        })

    # 3) 从调用栈文本提取时间戳 (若有)
    for m in _TIMESTAMP_RE.finditer(call_trace_text or ""):
        timeline.append({
            "time": m.group(1),
            "event": "call trace record",
            "source": "calltrace",
        })

    # 4) 崩溃点
    timeline.append({
        "time": crash_time or "unknown",
        "event": f"crash at {rip_function}" if rip_function else "kernel crash",
        "source": "inferred",
    })

    # 按时间排序: 数值时间戳 (dmesg 相对秒数) 升序在前, 无法解析时间的
    # 事件保持原有相对顺序 (stable sort), 崩溃点始终置于末尾
    def _sort_key(e: dict) -> float:
        try:
            return float(e["time"])
        except (TypeError, ValueError):
            return float("inf")

    crash_entry = timeline.pop()
    timeline.sort(key=_sort_key)
    timeline.append(crash_entry)

    # 5) 推断每个事件的时序图泳道(参与者)
    return [_with_actor(e) for e in timeline]


def _classify_edge_type(func_from: str, func_to: str, bug_key: str,
                        rip_function: str) -> str:
    """判定相邻栈帧间的传播类型"""
    if func_from in FREE_FUNCS:
        return "uaf_free"
    bug_key_lower = (bug_key or "").lower()
    if func_to == rip_function and any(k in bug_key_lower for k in _NULL_DEREF_KEYS):
        # NULL 解引用发生在故障点函数内
        return "null_deref"
    if any(h in func_from.lower() for h in _WRITE_HINTS):
        return "data_pollution"
    return "call"


def _elixir_source_url(kernel_version: str, func: str) -> str:
    """构造在线源码链接（elixir.bootlin.com ident 页，直接定位函数定义）。

    openEuler 内核与主线同路径，按主版本 vX.Y 锚定。函数 ident 页无需行号
    即可跳转到定义处；版本/函数无法确定时返回空串（报告降级为仅显示路径）。
    """
    if not func:
        return ""
    kv = (kernel_version or "").strip()
    m = re.match(r"^(\d+)\.(\d+)", kv)
    if not m:
        return ""
    tag = f"v{m.group(1)}.{m.group(2)}"
    return f"https://elixir.bootlin.com/linux/{tag}/ident/{func}"


def _build_propagation_chain(signature: list[str], call_trace_text: str,
                             bug_key: str, rip_function: str,
                             kernel_version: str = "") -> list[dict]:
    """从调用栈函数序列构建崩溃传播链"""
    chain: list[dict] = []
    for i in range(len(signature) - 1):
        func_from, func_to = signature[i], signature[i + 1]
        if not func_from or not func_to:
            continue
        hint = _infer_file_hint(func_to)
        chain.append({
            "from": func_from,
            "to": func_to,
            "type": _classify_edge_type(func_from, func_to, bug_key, rip_function),
            "source_file": "" if hint == "unknown" else hint,
            "source_url": _elixir_source_url(kernel_version, func_to),
            "source_snippet": "",  # 源码原文片段由 LLM 基于真实源码查阅填写，工具不编造
            "detail": "",  # 源码级解读由 LLM 基于源码分析填写
            "evidence": _find_evidence_line(call_trace_text, func_from, func_to),
        })
    return chain


def _build_source_clues(signature: list[str], rip_function: str) -> list[dict]:
    """为调用栈上的函数推断源码位置线索"""
    clues: list[dict] = []
    seen: set[str] = set()

    for func in signature:
        if not func or func in seen:
            continue
        seen.add(func)
        clues.append({
            "function": func,
            "file_hint": _infer_file_hint(func),
            "line_hint": "unknown",
            "reason": "call_trace",
        })

    # RIP 函数标记为崩溃点 (高置信度)
    if rip_function:
        for clue in clues:
            if clue["function"] == rip_function:
                clue["reason"] = "crash_point"
                break
        else:
            clues.insert(0, {
                "function": rip_function,
                "file_hint": _infer_file_hint(rip_function),
                "line_hint": "unknown",
                "reason": "crash_point",
            })

    return clues


def build_analysis_chain(crash_features: dict) -> dict:
    """构建深度分析链: 事件时间线 + 崩溃传播链 + 源码线索。

    Args:
        crash_features: analyze_crash 返回的 crash_features 字典, 应包含
            rip_function / call_trace_signature / call_trace_text /
            bug_type / bug_key / anomaly_features / crash_time。

    Returns:
        结构化分析数据字典, 含 event_timeline / propagation_chain /
        source_clues / pre_crash_events / error_keywords / repeated_errors。
    """
    features = crash_features if isinstance(crash_features, dict) else {}
    anomaly = features.get("anomaly_features")
    if not isinstance(anomaly, dict):
        anomaly = {}
    signature = _as_str_list(features.get("call_trace_signature"))
    call_trace_text = features.get("call_trace_text") or ""
    rip_function = features.get("rip_function") or ""
    bug_key = features.get("bug_key") or features.get("bug_type") or ""
    crash_time = features.get("crash_time") or ""
    kernel_version = features.get("kernel_version") or ""

    # 兜底: 签名缺失时至少包含 RIP 函数
    if not signature and rip_function:
        signature = [rip_function]

    return {
        "event_timeline": _build_event_timeline(
            anomaly, crash_time, rip_function, call_trace_text),
        "propagation_chain": _build_propagation_chain(
            signature, call_trace_text, bug_key, rip_function, kernel_version),
        "source_clues": _build_source_clues(signature, rip_function),
        "pre_crash_events": _as_str_list(anomaly.get("pre_crash_events")),
        "error_keywords": _as_str_list(anomaly.get("error_keywords")),
        "repeated_errors": _as_str_list(anomaly.get("repeated_errors")),
    }
