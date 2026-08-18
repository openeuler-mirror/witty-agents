"""特征提取器模块"""

from .dmesg import parse_dmesg
from .crash_cmd import run_crash_analysis
from .host import parse_host_from_dmesg
from .calltrace import parse_calltrace_functions, calltrace_similarity
from .hardware import detect_hardware_error, has_hardware_error
from .module import parse_modules_from_dmesg, parse_modules_from_crash_modt, extract_related_modules
from .signature import compute_signature, compute_issue_signature

__all__ = [
    "parse_dmesg",
    "run_crash_analysis",
    "parse_host_from_dmesg",
    "parse_calltrace_functions",
    "calltrace_similarity",
    "detect_hardware_error",
    "has_hardware_error",
    "parse_modules_from_dmesg",
    "parse_modules_from_crash_modt",
    "extract_related_modules",
    "compute_signature",
    "compute_issue_signature",
]
