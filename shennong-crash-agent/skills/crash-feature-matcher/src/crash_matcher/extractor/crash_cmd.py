"""crash 命令封装 — 通过 crash 命令分析 vmcore + vmlinux

移植自 osclinic cmd_plugin/crash_analysis/prase_crash.go
"""

import os
import re
import shutil
import tempfile
import subprocess
import logging
from typing import Optional

from ..models import CrashFeatures, HostFeatures
from .module import parse_modules_from_dmesg
from .hardware import detect_hardware_error

logger = logging.getLogger(__name__)

CRASH_TIMEOUT = 600  # 10 minutes

CRASH_COMMANDS = [
    "sys",
    "mach",
    "bt",
    "bt -a",
    "log -mT",
]

# crash bt 调用栈行: #N [hex] func at hex
BT_FUNC_RE = re.compile(r"#\d+\s+\[[0-9a-f]+\]\s+(\S+)\s+at\s")
# bt 首行: CPU / COMMAND
BT_CPU_COMMAND_RE = re.compile(r'CPU:\s+(\d+)\s+COMMAND:\s+"([^"]*)"')
# exception RIP 行
BT_EXC_RIP_RE = re.compile(r'\[exception RIP:\s+([^\]]+)\]')
# 纯十六进制地址 (过滤 extract_related_modules 的误判)
HEX_ADDR_RE = re.compile(r"^[0-9a-fA-F]+$")

# 已知问题分类
PANIC_CLASSIFY = {
    "general protection fault": "general_protection",
    "NULL pointer":              "null_pointer",
    "page fault":                "page_fault",
    "BUG":                       "kernel_bug",
}

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
})


def run_crash_analysis(
    vmcore_path: str,
    vmlinux_path: str,
) -> tuple[Optional[CrashFeatures], Optional[HostFeatures], bool]:
    """执行 crash 分析"""
    if not os.path.exists(vmcore_path):
        logger.error(f"vmcore not found: {vmcore_path}")
        return None, None, False
    if not os.path.exists(vmlinux_path):
        logger.error(f"vmlinux not found: {vmlinux_path}")
        return None, None, False

    crash_bin = shutil.which("crash")
    if not crash_bin:
        logger.error("crash command not available")
        return None, None, False

    cmd_file = _create_command_file()
    if not cmd_file:
        return None, None, False

    try:
        outputs = _execute_crash(crash_bin, vmcore_path, vmlinux_path, cmd_file)
    finally:
        if os.path.exists(cmd_file):
            os.unlink(cmd_file)

    if not outputs:
        return None, None, False

    feature = CrashFeatures()
    host = HostFeatures()

    # 按顺序解析
    _parse_sys(outputs.get("sys", ""), host, feature)
    _parse_mach(outputs.get("mach", ""), host)
    _parse_bt(outputs.get("bt", ""), feature)
    _parse_bta(outputs.get("bt -a", ""), feature)
    _parse_logmt(outputs.get("log -mT", ""), feature, host)

    # 从 call trace 中提取关联模块 [module_name]
    _extract_calltrace_modules(feature)

    # shennong 字段对齐
    feature.call_trace_signature = list(feature.call_trace_functions)
    feature.call_trace_text = " ".join(feature.call_trace_signature)

    return feature, host, False


# ============================================================
# crash 命令执行
# ============================================================

def _create_command_file() -> Optional[str]:
    try:
        fd, path = tempfile.mkstemp(prefix="crash_cmd_", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            for cmd in CRASH_COMMANDS:
                f.write(cmd + "\n")
            f.write("exit\n")
        return path
    except OSError as e:
        logger.error(f"failed to create command file: {e}")
        return None


def _execute_crash(
    crash_bin: str, vmcore: str, vmlinux: str, cmd_file: str
) -> dict[str, str]:
    cmd = [crash_bin, vmcore, vmlinux, "-i", cmd_file]
    logger.info(f"running crash: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(timeout=CRASH_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.error("crash command timed out")
        return {}
    except OSError as e:
        logger.error(f"crash command failed: {e}")
        return {}

    if proc.returncode != 0 and not stdout.strip():
        logger.error(f"crash exit {proc.returncode}: {stderr[:500]}")
        return {}

    return _split_outputs(stdout)


def _split_outputs(stdout: str) -> dict[str, str]:
    """按 'crash>' 提示符分割输出"""
    outputs: dict[str, str] = {}
    current_cmd = ""
    current_lines: list[str] = []

    for line in stdout.splitlines():
        if line.startswith("crash>"):
            if current_lines:
                outputs[current_cmd] = "\n".join(current_lines)
            current_cmd = line[len("crash>"):].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines and current_cmd != "exit":
        outputs[current_cmd] = "\n".join(current_lines)

    return outputs


# ============================================================
# sys — 内核版本 / 主机名 / PANIC / DATE
# ============================================================

def _parse_sys(output: str, host: HostFeatures, feature: CrashFeatures):
    """解析 sys 输出

    格式:
          KERNEL: /path/to/vmlinux
        DUMPFILE: /path/to/vmcore
            CPUS: 128
            DATE: Sat Sep  6 09:38:05 CST 2025
          UPTIME: 717 days, 00:47:35
        NODENAME: yg-hulk-k8s-node5434.mt
         RELEASE: 5.10.0-xxx
         VERSION: #1 SMP ...
         MACHINE: x86_64  (1996 Mhz)
          MEMORY: 1011.7 GB
           PANIC: "Kernel panic - not syncing: Hard LOCKUP"
    """
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("RELEASE:"):
            host.kernel_version = line.split(":", 1)[-1].strip()
        elif line.startswith("NODENAME:"):
            host.host_name = line.split(":", 1)[-1].strip()
        elif line.startswith("PANIC:"):
            value = line.split(":", 1)[-1].strip().strip('"')
            feature.bug = value
            feature.bug_key = value
            feature.bug_type = _classify_panic(value)


def _classify_panic(panic_msg: str) -> str:
    lower = panic_msg.lower()
    if "lockup" in lower:
        return "hard_lockup" if "hard" in lower else "soft_lockup"
    for pattern, btype in PANIC_CLASSIFY.items():
        if pattern in panic_msg:
            return btype
    if lower.startswith("sysrq"):
        return "manual_crash"
    return "oops"


# ============================================================
# mach — CPU / 内存 / 机型
# ============================================================

def _parse_mach(output: str, host: HostFeatures):
    """解析 mach 输出

    格式:
              MACHINE TYPE: x86_64
               MEMORY SIZE: 1011.7 GB
                      CPUS: 128
    """
    for line in output.splitlines():
        stripped = line.strip()
        if "CPUS:" in stripped:
            try:
                host.cpu_num = int(stripped.split(":")[-1].strip())
            except ValueError:
                pass
        elif "MEMORY SIZE:" in stripped:
            try:
                mem_str = stripped.split(":")[-1].strip().split()[0]
                host.memory_size = f"{int(float(mem_str) * 1024)}MB"
            except (ValueError, IndexError):
                pass
        elif stripped.startswith("MACHINE TYPE:"):
            host.machine_model = stripped.split(":", 1)[-1].strip()


# ============================================================
# mod -t — 模块列表
# ============================================================
# bt — 调用栈 / RIP / CPU / COMMAND
# ============================================================

def _parse_bt(output: str, feature: CrashFeatures):
    """解析 bt (当前进程栈) 输出

    格式:
        PID: 254423   TASK: ffff9ca48867d480  CPU: 67   COMMAND: "java"
         #0 [fffffe0000f7ebb0] panic at ffffffffaf25a75a
         #1 [fffffe0000f7ec38] watchdog_hardlockup_check at ffffffffaf263d79
         ...
            [exception RIP: native_queued_spin_lock_slowpath+382]
         ...
        --- <NMI exception stack> ---
        #10 [ffffbc6336aff948] native_queued_spin_lock_slowpath at ffffffffae955aae
        ...
    """
    funcs: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()

        # CPU / COMMAND from first line
        if not feature.crash_cpu or not feature.crash_command:
            m = BT_CPU_COMMAND_RE.search(stripped)
            if m:
                if not feature.crash_cpu:
                    feature.crash_cpu = int(m.group(1))
                if not feature.crash_command:
                    feature.crash_command = m.group(2)

        # 调用栈函数名
        m = BT_FUNC_RE.search(stripped)
        if m:
            name = m.group(1)
            if name not in IGNORE_FUNCS:
                funcs.append(name)

        # exception RIP (含十进制偏移, 需转 hex)
        m = BT_EXC_RIP_RE.search(stripped)
        if m:
            rip_raw = m.group(1)
            feature.rip = rip_raw
            if "+" in rip_raw:
                func, sep, off = rip_raw.partition("+")
                feature.rip_function = func
                if off.startswith("0x"):
                    feature.rip_offset = off
                else:
                    try:
                        feature.rip_offset = hex(int(off))
                    except ValueError:
                        feature.rip_offset = off
                feature.rip = f"{feature.rip_function}+{feature.rip_offset}"
            else:
                feature.rip_function = rip_raw

    if output.strip():
        feature.call_trace = output
        feature.call_trace_functions = funcs


# ============================================================
# bt -a — 所有进程栈 (补充 call_trace)
# ============================================================

def _parse_bta(output: str, feature: CrashFeatures):
    """解析 bt -a (所有进程栈) — 若 bt 未提取到, 从此补充"""
    if not output.strip():
        return

    if not feature.call_trace:
        feature.call_trace = output

    if not feature.call_trace_functions:
        funcs: list[str] = []
        for line in output.splitlines():
            # 找到崩溃进程的栈段 (PID 行开头)
            if line.strip() and not line[0].isspace():
                # 新进程段开始, 检查是否为目标 PID
                if feature.crash_command:
                    m = re.search(r'COMMAND:\s+"([^"]*)"', line)
                    if m and m.group(1) != feature.crash_command:
                        continue
            m = BT_FUNC_RE.search(line.strip())
            if m:
                name = m.group(1)
                if name not in IGNORE_FUNCS:
                    funcs.append(name)
        feature.call_trace_functions = funcs


# ============================================================
# log -mT — 内核日志
# ============================================================

def _parse_logmt(output: str, feature: CrashFeatures, host: HostFeatures):
    """解析 log -mT 输出 — 内核日志"""
    if not output.strip():
        return

    logs = [l for l in output.splitlines() if l.strip()]

    # 从内核日志中提取完整模块列表 (Modules linked in:)
    # log -mT 的每行带 [timestamp] <level> 前缀, 需要剥离
    for line in logs:
        if "Modules linked in:" in line:
            stripped_line = re.sub(r'^\[.*?\]\s*<\d+>\s*', '', line)
            modules = parse_modules_from_dmesg([stripped_line])
            host.modules = list(modules.keys())
            break

    # 硬件错误检测
    has_hw, hw_detail = detect_hardware_error(logs)
    if has_hw:
        feature.bug_type = "hardware_error"
        feature.bug = hw_detail
        feature.crash_log = hw_detail
        return

    feature.crash_log = "\n".join(logs[-300:])


# ============================================================
# 关联模块提取
# ============================================================

def _extract_calltrace_modules(feature: CrashFeatures):
    """从 call trace 文本中提取 [module_name] 格式的关联模块

    过滤纯 hex 地址 (如 [ffffbc6336aff948]) 和已知噪音标记.
    """
    found: set[str] = set()
    bracket_pat = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")

    for text in (feature.rip, feature.call_trace):
        if not text:
            continue
        for m in bracket_pat.finditer(text):
            mod = m.group(1)
            if mod.startswith("<") or mod in ("exception", "end"):
                continue
            if HEX_ADDR_RE.match(mod):
                continue
            found.add(mod)

    feature.related_modules = sorted(found)
