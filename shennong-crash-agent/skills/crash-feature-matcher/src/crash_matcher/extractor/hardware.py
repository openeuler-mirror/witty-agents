"""硬件错误检测器 — 检测 MCE, PCIe, Memory, 硬件故障"""

from ..models import CrashFeatures

HARDWARE_ERR_KEYS = [
    "[Hardware Error]:   section_type: general processor error",
    "[Hardware Error]:   section_type: memory error",
    "[Hardware Error]:   section_type: PCIe error",
    "[Hardware Error]: PROCESSOR",
    "[Hardware Error]: Hardware error",
    "[Hardware Error]: event severity: fatal",
    "[Hardware Error]: Error 1,type: fatal",
]


def detect_hardware_error(logs: list[str]) -> tuple[bool, str]:
    """检测日志中是否有硬件错误

    Returns:
        (has_error, error_detail)
    """
    for line in logs:
        for err_key in HARDWARE_ERR_KEYS:
            if err_key in line:
                return True, line.strip()
    return False, ""


def has_hardware_error(logs: list[str]) -> bool:
    """快速检测是否有硬件错误"""
    found, _ = detect_hardware_error(logs)
    return found
