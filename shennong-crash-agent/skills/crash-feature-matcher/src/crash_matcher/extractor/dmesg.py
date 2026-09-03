"""dmesg 解析器 — 从内核日志中提取宕机特征

移植自 osclinic cmd_plugin/crash_analysis/parse_dmesg.go
"""

import re
import logging
from datetime import datetime, timezone

from ..models import CrashFeatures, HostFeatures
from ..bug_types import BUG_KEY_TO_TYPE, classify_kasan_subtype
from ..config import Config
from .calltrace import parse_calltrace_functions, extract_function_name
from .hardware import detect_hardware_error
from .module import parse_modules_from_dmesg, extract_dominant_modules

logger = logging.getLogger(__name__)

# 检测 kern 格式: Mon DD HH:MM:SS hostname kernel: [sec.usec] content
KERN_PREFIX_RE = re.compile(r'^[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\S+\s+kernel:\s+\[?[\d.]+\]?\s*')

def _is_kern_format(raw_lines: list[str]) -> bool:
    """检测日志是否为 kern 格式 (带 hostname+kernel: 前缀)"""
    kern_count = 0
    check = min(len(raw_lines), 5)
    for line in raw_lines[:check]:
        if KERN_PREFIX_RE.match(line):
            kern_count += 1
    return kern_count >= check // 2 + 1

# ============================================================
# BugKey 关键词表
# BugKey 关键词表 — 决定匹配策略 (移植自 osclinic BugKeyWordsMap)
# ============================================================
BUG_KEY_PATTERNS = list(BUG_KEY_TO_TYPE)

OOM_CONTEXT_WINDOW = 50

# 时间戳正则: [  123.456789] 或 [123.456789]
TIMESTAMP_RE = re.compile(r"^\[\s*(\d+\.\d+)\]\s")


def _is_oom_context(logs: list[str], index: int) -> bool:
    """检查 BugKey 匹配是否属于 OOM kill 上下文 (避免误判)"""
    start = max(0, index - OOM_CONTEXT_WINDOW)
    for i in range(index, start - 1, -1):
        if "invoked oom-killer" in logs[i]:
            return True
    return False


def _find_bug_key(logs: list[str]) -> tuple[str, str, int]:
    """从日志中寻找 BugKey 和 Bug 行"""
    for i, line in enumerate(logs):
        for keyword in BUG_KEY_PATTERNS:
            if keyword in line:
                if _is_oom_context(logs, i):
                    continue
                return keyword, line, i
    return "", "", -1


def _parse_dump_bug(logs: list[str], start: int) -> str:
    """解析 Kernel panic - not syncing: 子消息"""
    for i in range(start, min(start + 10, len(logs))):
        line = logs[i]
        if "Kernel panic - not syncing:" in line:
            return line.split("Kernel panic - not syncing:", 1)[-1].strip()
    return ""


def _parse_rip(logs: list[str], start: int) -> tuple[str, str, str]:
    """从 RIP: 行解析指令指针 (x86)"""
    for i in range(start, min(start + 10, len(logs))):
        line = logs[i]
        if line.startswith("RIP:"):
            parts = [p.strip() for p in line.split(":")]
            if len(parts) >= 3 and parts[1] != "0033":
                rip_code = parts[1]
                rip_raw = parts[2].split()[0] if parts[2].split() else ""
                # 去掉函数体大小后缀 /0x2f0，只保留函数名+偏移
                if "/0x" in rip_raw:
                    rip_raw = rip_raw.split("/0x")[0]
                # 提取模块名
                mod_part = ""
                if "[" in parts[2] and "]" in parts[2]:
                    mod_start = parts[2].index("[")
                    mod_end = parts[2].index("]")
                    mod_part = " [" + parts[2][mod_start + 1:mod_end] + "]"
                rip = rip_raw + mod_part
                rip_func = _extract_rip_function(rip_raw)
                rip_offset = _extract_rip_offset(rip_raw)
                return rip, rip_func, rip_offset
            break
    return "", "", ""


def _parse_pc_arm64(logs: list[str], start: int) -> tuple[str, str, str]:
    """从 pc : 行解析 PC 寄存器 (ARM64)"""
    for i in range(start, min(start + 100, len(logs))):
        line = logs[i]
        if line.startswith("pc "):
            colon_idx = line.index(":") if ":" in line else -1
            if colon_idx == -1:
                continue
            pc_val = line[colon_idx + 1:].strip()
            parts = pc_val.split()
            if not parts:
                continue
            func_part = parts[0]
            # 去掉 /0x... 部分
            plus_idx = func_part.rfind("+")
            slash_idx = func_part.rfind("/0x")
            if plus_idx != -1 and slash_idx > plus_idx:
                func_part = func_part[:slash_idx]
            rip_func = _extract_rip_function(func_part)
            rip_offset = _extract_rip_offset(func_part)
            mod_part = " " + parts[1] if len(parts) > 1 and parts[1].startswith("[") else ""
            return func_part + mod_part, rip_func, rip_offset
    return "", "", ""


def _parse_calltrace_text(logs: list[str], start: int) -> str:
    """从日志中提取 Call Trace 原始文本块"""
    lines = []
    in_trace = False
    for i in range(start, min(start + 100, len(logs))):
        line = logs[i]
        if "Call Trace:" in line or "Call trace:" in line:
            in_trace = True
            lines.append(line)
            continue
        if in_trace:
            if "+0x" not in line and not any(
                t in line for t in ("<IRQ>", "<NMI>", "<TASK>")
            ):
                break
            lines.append(line)
    return "\n".join(lines)


def _parse_cpu_command(logs: list[str], start: int) -> tuple[int, str]:
    """从 CPU: 行解析 CPU 编号和进程名"""
    for i in range(start, min(start + 10, len(logs))):
        line = logs[i]
        if line.startswith("CPU:"):
            parts = line.split()
            cpu = -1
            command = ""
            for j, word in enumerate(parts):
                if word == "CPU:" and j + 1 < len(parts):
                    try:
                        cpu = int(parts[j + 1])
                    except ValueError:
                        pass
                if word == "Comm:" and j + 1 < len(parts):
                    command = parts[j + 1]
            return cpu, command
    return -1, ""


def _parse_hardware_name(logs: list[str], start: int) -> str:
    """从 Hardware name: 行解析硬件型号"""
    for i in range(start, min(start + 10, len(logs))):
        line = logs[i]
        if line.startswith("Hardware name:"):
            parts = line.split(": ", 1)
            if len(parts) > 1:
                return parts[1]
    return ""


def _extract_crash_log(logs: list[str], bug_index: int) -> str:
    """提取崩溃日志片段 (BugKey前后各20行, 最多 max_log_line_in_db 行)"""
    begin = max(0, bug_index - 20)
    end = min(len(logs), begin + Config().get().matcher.max_log_line_in_db)
    return "\n".join(logs[begin:end])


def _extract_rip_function(rip_raw: str) -> str:
    """从 RIP 文本提取纯函数名"""
    if not rip_raw:
        return ""
    func = rip_raw.split("+0x")[0] if "+0x" in rip_raw else rip_raw
    func = func.split("/0x")[0] if "/0x" in func else func
    return func


def _extract_rip_offset(rip_raw: str) -> str:
    """从 RIP 文本提取偏移量"""
    if "+0x" in rip_raw:
        offset = rip_raw.split("+0x")[1]
        return "0x" + offset.split("/")[0].split(" ")[0]
    return "0x0"


def parse_dmesg(text: str) -> tuple[CrashFeatures, HostFeatures, bool]:
    """解析 dmesg 或 vmcore-dmesg 文本

    Args:
        text: dmesg/vmcore-dmesg 的原始文本

    Returns:
        (CrashFeatures, HostFeatures, has_hardware_error)
    """
    feature = CrashFeatures()
    host = HostFeatures()

    # 按行拆分，去除空行
    raw_lines = [l for l in text.splitlines() if l.strip()]
    if not raw_lines:
        return feature, host, False

    # 检测并预处理 kern 格式日志 (带 hostname kernel: [ts] 前缀)
    if _is_kern_format(raw_lines):
        stripped = []
        for line in raw_lines:
            m = KERN_PREFIX_RE.match(line)
            if m:
                stripped.append(line[m.end():])
            elif line.strip():
                stripped.append(line)
        raw_lines = stripped

    # 裁剪时间窗口 (取宕机前 dmesg_analysis_window_seconds 秒)
    logs = _crop_by_time(raw_lines)

    # 全量检测硬件错误
    has_hw, hw_detail = detect_hardware_error(raw_lines)
    if has_hw:
        feature.crash_type = "硬件故障"
        feature.bug_type = "hardware_error"
        feature.bug = hw_detail
        feature.crash_log = hw_detail
        return feature, host, True

    # 找 BugKey
    bug_key, bug_line, bug_idx = _find_bug_key(logs)
    feature.bug_key = bug_key
    feature.bug = bug_line

    # 解析 DumpBug (panic 子类型)
    feature.bug_type = _classify_bug_type(bug_key, logs, bug_idx)

    # 从 bug_idx 开始解析各类信息
    start = max(0, bug_idx) if bug_idx >= 0 else 0
    search_logs = logs[start:]

    # RIP (x86)
    rip, rip_func, rip_off = _parse_rip(search_logs, 0)
    if not rip:
        rip, rip_func, rip_off = _parse_pc_arm64(search_logs, 0)
    feature.rip = rip
    feature.rip_function = rip_func
    feature.rip_offset = rip_off

    # rip 归一化：处理没有 RIP 行的异常类型（int3/invalid_opcode/kernel_bug 等）
    if not feature.rip:
        # 从 bug_key 中提取 at <function>+<offset> 模式，如 "int3: ... at btf_put+0x30/0x80"
        at_match = re.search(r'at [^ ]+\s+([a-zA-Z_][a-zA-Z0-9_]+)\+0x', feature.bug or '')
        if at_match:
            rip = at_match.group(1)
        else:
            # KASAN/UAF 报告行: "BUG: KASAN: use-after-free in <函数>+0x..."
            kasan_match = re.search(r' in\s+([a-zA-Z_][a-zA-Z0-9_]+)\+0x', feature.bug or '')
            if kasan_match:
                rip = kasan_match.group(1)
            else:
                # 或者从 bug_key 第一个函数名匹配
                func_match = re.match(r'^[a-zA-Z_][a-zA-Z0-9_]+\+0x[0-9a-fA-F]+', bug_key or '')
                if func_match:
                    rip = func_match.group(0)
        if rip:
            # 归一化 rip：去掉函数体大小后缀 /0x...
            if '/0x' in rip:
                rip = rip.split('/0x')[0]
            feature.rip = rip
            feature.rip_function = _extract_rip_function(rip)
            feature.rip_offset = _extract_rip_offset(rip)
    # 对所有已有 rip 也做 /0x 截断（兜底）
    if feature.rip and '/0x' in feature.rip:
        feature.rip = feature.rip.split('/0x')[0]

    # Call Trace
    feature.call_trace = _parse_calltrace_text(logs, start)
    if feature.call_trace:
        feature.call_trace_functions = parse_calltrace_functions(feature.call_trace)
    else:
        feature.call_trace = "\n".join(logs[max(0, bug_idx - 2):min(len(logs), bug_idx + 50)])
        feature.call_trace_functions = parse_calltrace_functions(feature.call_trace)

    # CPU / Command
    feature.crash_cpu, feature.crash_command = _parse_cpu_command(search_logs, 0)

    # Hardware Name
    host.machine_model = _parse_hardware_name(search_logs, 0)

    # Modules
    host.modules = list(parse_modules_from_dmesg(logs).keys())
    dominant_mod, _qualified_modules = extract_dominant_modules(feature.call_trace)
    feature.related_modules = [] if dominant_mod == "kernel" else [dominant_mod]

    # Crash Log 片段
    if bug_idx >= 0:
        feature.crash_log = _extract_crash_log(logs, bug_idx)
    else:
        feature.crash_log = "\n".join(logs[-200:])

    # DumpBug
    dump_bug = _parse_dump_bug(logs, start)
    if dump_bug and not feature.bug_type:
        feature.bug_type = _classify_panic_subtype(dump_bug)

    # crash_type 中文化
    feature.crash_type = _to_crash_type_cn(feature.bug_type)

    # shennong 字段对齐: 复制到新字段名
    feature.call_trace_signature = list(feature.call_trace_functions)
    feature.call_trace_text = " ".join(feature.call_trace_signature)

    # Extract anomaly features for enhanced matching
    feature.anomaly_features = _extract_anomaly_features(raw_lines, logs, bug_idx)

    return feature, host, False


CRASH_TYPE_CN = {
    "null_pointer": "内核宕机",
    "page_fault": "内核宕机",
    "stack_overflow": "内核宕机",
    "memory_corruption": "内核宕机",
    "general_protection": "内核宕机",
    "invalid_opcode": "内核宕机",
    "kernel_bug": "内核宕机",
    "hard_lockup": "软硬件hang",
    "soft_lockup": "软硬件hang",
    "double_fault": "内核宕机",
    "warning": "内核警告",
    "nx_violation": "内核宕机",
    "smep_violation": "内核宕机",
    "page_table_corruption": "内核宕机",
    "kasan": "内核宕机",
    "kfence": "内核宕机",
    "rcu_stall": "软硬件hang",
    "hung_task": "软硬件hang",
    "list_corruption": "内核宕机",
    "oops": "内核宕机",
    "hardware_error": "硬件故障",
    "oom": "OOM",
    "unknown": "未知原因",
}


def _classify_bug_type(bug_key: str, logs: list[str], bug_idx: int) -> str:
    """BugKey → BugType 分类"""
    if not bug_key:
        # 检查是否有 OOM 特征
        for line in logs[max(0, bug_idx - 50):bug_idx + 1]:
            if "invoked oom-killer" in line or "Memory cgroup out of memory" in line:
                return "oom"
        return "unknown"

    for key, btype in BUG_KEY_TO_TYPE.items():
        if key in bug_key:
            if btype == "kasan":
                line = logs[bug_idx] if 0 <= bug_idx < len(logs) else bug_key
                return classify_kasan_subtype(line)
            return btype

    # 检查 Kernel panic 子类型
    for i in range(max(0, bug_idx), min(len(logs), bug_idx + 10)):
        if "Kernel panic - not syncing:" in logs[i]:
            return _classify_panic_subtype(logs[i])
    return "unknown"


def _classify_panic_subtype(line: str) -> str:
    """Kernel panic - not syncing 子类型分类"""
    msg = line.split("Kernel panic - not syncing:", 1)[-1].strip().lower()
    if "out of memory" in msg or "oom" in msg:
        return "oom"
    if "sysrq" in msg:
        return "manual_crash"
    if "vfs" in msg or "filesystem" in msg:
        return "filesystem"
    if "hard lockup" in msg or "hardlockup" in msg:
        return "hard_lockup"
    if "soft lockup" in msg or "softlockup" in msg:
        return "soft_lockup"
    return "panic"


def _to_crash_type_cn(bug_type: str) -> str:
    return CRASH_TYPE_CN.get(bug_type, "内核宕机")


# ============================================================
# 辅助函数
# ============================================================

def _crop_by_time(raw_lines: list[str]) -> list[str]:
    """按时间窗口裁剪日志 (取最后 dmesg_analysis_window_seconds 秒)"""
    window = Config().get().matcher.dmesg_analysis_window_seconds
    last_ts = None
    for line in reversed(raw_lines):
        m = TIMESTAMP_RE.match(line)
        if m:
            last_ts = float(m.group(1))
            break

    if last_ts is None:
        return raw_lines

    cutoff = last_ts - window
    filtered = []
    for line in raw_lines:
        m = TIMESTAMP_RE.match(line)
        if m:
            ts = float(m.group(1))
            if ts >= cutoff and line.strip():
                content = TIMESTAMP_RE.sub("", line)
                filtered.append(content)
    if len(filtered) >= 5:
        return filtered
    # fallback: 全部行去掉时间戳
    return [TIMESTAMP_RE.sub("", l) for l in raw_lines if l.strip()]


def _extract_anomaly_features(raw_lines: list[str], logs: list[str], bug_idx: int) -> dict:
    """Extract additional anomaly features from crash logs for enhanced matching."""
    features: dict = {
        "repeated_errors": [],
        "error_keywords": [],
        "register_values": {},
        "dump_stack_context": "",
        "pre_crash_events": [],
        "cpu_context": "",
    }

    error_line_counts: dict[str, int] = {}
    error_pattern = re.compile(r'(error|timeout|fail|panic|oops|BUG|WARNING|hung|stall|corruption)', re.IGNORECASE)

    for line in raw_lines[-500:]:
        if error_pattern.search(line):
            stripped = TIMESTAMP_RE.sub("", line).strip()
            key = stripped[:120]
            error_line_counts[key] = error_line_counts.get(key, 0) + 1

    repeated = [(line, cnt) for line, cnt in error_line_counts.items() if cnt >= 3]
    repeated.sort(key=lambda x: x[1], reverse=True)
    features["repeated_errors"] = [line for line, _ in repeated[:5]]

    error_kw_patterns = [
        r'\b(NULL|BUG_ON|WARN_ON|panic|oops|deadlock|lockup|corruption|overflow|uaf|use.after.free)\b',
        r'\b(timeout|fail|error|fault|stall|hung|OOM|oom)\b',
        r'\[(Hardware Error|Firmware Bug|Machine check)\]',
    ]
    kws = set()
    for line in logs[max(0, bug_idx - 100):min(len(logs), bug_idx + 50)]:
        for patt in error_kw_patterns:
            found = re.findall(patt, line)
            kws.update(f.lower() for f in found)
    features["error_keywords"] = sorted(kws)[:15]

    ctx_start = max(0, bug_idx - 10)
    ctx_end = min(len(logs), bug_idx + 10)
    features["dump_stack_context"] = "\n".join(logs[ctx_start:ctx_end])

    pre_start = max(0, bug_idx - 50)
    features["pre_crash_events"] = [
        l.strip()[:200] for l in logs[pre_start:max(0, bug_idx - 1)]
        if error_pattern.search(l)
    ][:10]

    cpu_info_parts = []
    for line in logs[max(0, bug_idx):min(len(logs), bug_idx + 30)]:
        if re.search(r'(CPU:|NMI|triggered|smp_processor_id)', line):
            cpu_info_parts.append(line.strip()[:150])
    features["cpu_context"] = "\n".join(cpu_info_parts[:5]) if cpu_info_parts else ""

    return features
