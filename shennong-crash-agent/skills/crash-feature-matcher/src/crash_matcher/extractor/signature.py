"""签名计算器 — 为宕机特征生成唯一签名"""

from ..models import CrashFeatures


def compute_signature(feature: CrashFeatures) -> str:
    """计算唯一签名: bug_type::dominant_module::rip_function::offset"""
    dominant = feature.related_modules[0] if feature.related_modules else "kernel"
    rip_func = feature.rip_function or "unknown"
    offset = feature.rip_offset or "0x0"
    return f"{feature.bug_type}::{dominant}::{rip_func}::{offset}"


def compute_issue_signature(
    bug_type: str,
    modules: list[str],
    rip_function: str,
    rip_offset: str,
) -> str:
    """为已知问题计算签名"""
    dominant = modules[0] if modules else "kernel"
    return f"{bug_type}::{dominant}::{rip_function or 'unknown'}::{rip_offset or '0x0'}"
