"""主机特征提取器 — 从 dmesg 日志中提取主机信息"""

from ..models import HostFeatures
from .module import parse_modules_from_dmesg


def parse_host_from_dmesg(text: str) -> HostFeatures:
    """从 dmesg 日志中提取主机信息"""
    host = HostFeatures()
    lines = text.splitlines()

    for line in lines:
        line = line.strip()
        if "Linux version" in line and host.kernel_version == "":
            # "Linux version 5.10.0-218.0.0.mt20250120.565 ..."
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "version" and i + 1 < len(parts):
                    host.kernel_version = parts[i + 1]
                    break

        if "DMI:" in line and host.machine_model == "":
            host.machine_model = line.split("DMI:", 1)[-1].strip()

    # 解析模块
    modules = parse_modules_from_dmesg(lines)
    host.modules = list(modules.keys())

    return host
