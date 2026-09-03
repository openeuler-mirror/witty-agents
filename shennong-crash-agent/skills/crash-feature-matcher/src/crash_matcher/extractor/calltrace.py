"""调用栈解析器 — 从 dmesg/crash 输出中提取函数名列表"""

import re

# 忽略函数列表 (移植自 sysom views.py + osclinic 的过滤逻辑)
IGNORE_FUNCS = frozenset({
    "schedule", "schedule_timeout", "ret_from_fork", "kthread",
    "do_syscall_64", "entry_SYSCALL_64_after_swapgs",
    "system_call_fastpath", "fastpath",
    "entry_SYSCALL_64_after_hwframe",
    "start_secondary", "cpu_startup_entry", "arch_cpu_idle", "default_idle",
    "do_IRQ", "common_interrupt", "irq_exit", "do_softirq",
    "__schedule", "io_schedule_timeout", "io_schedule", "dump_stack",
    "exit_to_usermode_loop", "stub_clone", "schedule_preempt_disabled",
    "oom_kill_process", "unwind_backtrace", "dump_header", "show_stack",
    "dump_backtrace", "panic", "watchdog_timer_fn",
    "nmi_panic", "watchdog_overflow_callback", "__perf_event_overflow",
    "perf_event_overflow", "intel_pmu_handle_irq",
    "perf_event_nmi_handler", "nmi_handle", "do_nmi", "end_repeat_nmi",
    "watchdog", "__hrtimer_run_queues", "hrtimer_interrupt",
    "local_apic_timer_interrupt", "smp_apic_timer_interrupt",
    "apic_timer_interrupt", "__pv_queued_spin_lock_slowpath",
    "queued_spin_lock_slowpath",
    # KASAN 报告机制自身栈帧，非真实崩溃路径，应过滤以保留真正崩溃调用链
    "dump_stack_lvl", "print_address_description", "print_report", "kasan_report",
})

# 从 dmesg/vmcore-dmesg 的调用栈中提取函数名
CALLTRACE_LINE_PATTERN_1 = re.compile(r".+[0-9]+\].+\[.*\] *(\S+)\+0x")
CALLTRACE_LINE_PATTERN_2 = re.compile(r".+[0-9]+\] *(\S+)\+0x")
CALLTRACE_LINE_PATTERN_3 = re.compile(r".*#[0-9]+ \[[0-9a-f]+\] (\S+) at")
# crash bt 输出的栈行匹配
CRASH_BT_PATTERN = re.compile(r"#\d+\s+\[[0-9a-f]+\]\s+(\S+)\+")
# 通用模式: 匹配 func+0xNNN/0xMMM 格式 (不需要时间戳括号)
GENERIC_FUNC_PATTERN = re.compile(r"\b([a-zA-Z_][\w.-]*)\+0x[0-9a-fA-F]+/0x[0-9a-fA-F]+")
# 容错模式: 匹配偏移量被省略的函数帧 (如 "func+0x...")
LOOSE_FUNC_PATTERN = re.compile(r"\b([a-zA-Z_][\w.-]*)\+0x")


def extract_function_name(line: str) -> str:
    """从一行调用栈中提取函数名"""
    for pat in [CALLTRACE_LINE_PATTERN_1, CALLTRACE_LINE_PATTERN_2,
                 CALLTRACE_LINE_PATTERN_3, CRASH_BT_PATTERN, GENERIC_FUNC_PATTERN,
                 LOOSE_FUNC_PATTERN]:
        m = pat.search(line)  # 用 search (通用模式可能不是行首)
        if m:
            name = m.group(1).split(".")[0]
            if name not in IGNORE_FUNCS:
                return name
    return ""


def parse_calltrace_functions(text: str) -> list[str]:
    """从 Call Trace 文本中提取函数名列表"""
    funcs = []
    in_calltrace = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Call Trace:") or stripped.startswith("Call trace:"):
            in_calltrace = True
            continue

        if in_calltrace:
            # 中断栈标记不影响继续解析
            if any(tag in stripped for tag in ("<IRQ>", "<NMI>", "<TASK>")):
                continue

            name = extract_function_name(stripped)
            if name:
                funcs.append(name)
                continue

            # 如果遇到不再像调用栈的行 (含 +0x 才算栈帧), 停止
            if "+0x" not in stripped:
                in_calltrace = False

    return funcs


def calltrace_similarity(funcs_a: list[str], funcs_b: list[str]) -> float:
    """计算两个函数名列表的相似度 (基于公共子序列)"""
    if not funcs_a or not funcs_b:
        return 0.0

    set_a = set(funcs_a)
    set_b = set(funcs_b)
    if not set_a or not set_b:
        return 0.0

    intersection = set_a & set_b
    union = set_a | set_b
    jaccard = len(intersection) / len(union) if union else 0.0

    # 序列相似度 (最长公共子序列)
    m, n = len(funcs_a), len(funcs_b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if funcs_a[i - 1] == funcs_b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs = dp[m][n]
    seq_sim = lcs / min(m, n) if min(m, n) > 0 else 0.0

    return 0.4 * jaccard + 0.6 * seq_sim
