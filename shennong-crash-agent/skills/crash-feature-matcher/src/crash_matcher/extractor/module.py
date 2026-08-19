"""模块提取器 — 提取全体模块和关联模块"""

import re
from typing import Optional


def parse_modules_from_dmesg(lines: list[str]) -> dict[str, bool]:
    """从 dmesg Modules linked in: 行解析模块, 返回 {module_name: is_builtin}

    格式: "iw_cm(OE)" -> is_builtin=False (含 O 标记表示外置模块)
    """
    modules: dict[str, bool] = {}
    in_modules = False
    max_lines = 5

    for i, line in enumerate(lines):
        if line.startswith("Modules linked in:"):
            in_modules = True
            line = line[len("Modules linked in:"):]
        elif in_modules and not line.startswith(" "):
            in_modules = False
            break

        if in_modules:
            line = line.strip()
            if "last unloaded" in line:
                break
            for part in line.split():
                if part.startswith("[last"):
                    continue
                name, is_builtin = _parse_module_info(part)
                if name:
                    modules[name] = is_builtin
    return modules


def parse_modules_from_crash_modt(output: str) -> dict[str, bool]:
    """从 crash mod -t 输出解析模块

    格式:
      NAME                 TAINTS
      ext4                 (OE)
      xfs
    """
    modules: dict[str, bool] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("NAME"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            taints = parts[1]
            modules[name] = "O" not in taints
        elif len(parts) == 1:
            modules[parts[0]] = True  # 无 Taint = 内置
    return modules


_HEX_ADDR_RE = re.compile(r"^[0-9a-fA-F]+$")


def extract_related_modules(rip: str, call_trace: str) -> list[str]:
    """从 RIP 和调用栈中提取关联模块 (出现在 [module] 中的模块名)"""
    found = set()
    bracket_pattern = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")

    for text in [rip, call_trace]:
        for m in bracket_pattern.finditer(text):
            mod = m.group(1)
            if mod.startswith("<") or mod in ("exception", "end"):
                continue
            if _HEX_ADDR_RE.match(mod):
                continue
            found.add(mod)

    return sorted(found)


def extract_dominant_modules(call_trace: str, min_count: int = 3) -> tuple:
    """从 call trace 中按模块出现次数过滤

    Returns:
        (dominant_module, qualified_modules)
    """
    import collections
    module_counts: dict[str, int] = {}
    module_first_order: dict[str, int] = {}
    bracket_pat = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")
    order = 0

    for line in call_trace.splitlines():
        if '+0x' not in line:
            continue
        for m in bracket_pat.finditer(line):
            mod = m.group(1)
            if mod.startswith("<") or mod in ("exception", "end"):
                continue
            module_counts[mod] = module_counts.get(mod, 0) + 1
            if mod not in module_first_order:
                module_first_order[mod] = order
                order += 1

    qualified = sorted([m for m, c in module_counts.items() if c >= min_count])
    if not qualified:
        return "kernel", []

    dominant = max(qualified, key=lambda m: (module_counts[m], -module_first_order.get(m, 999)))
    return dominant, qualified
def _parse_module_info(module_info: str) -> tuple[Optional[str], bool]:
    """解析单个模块信息: 例 'iw_cm(OE)' -> ('iw_cm', False)"""
    if "(" in module_info:
        parts = module_info.split("(")
        name = parts[0]
        is_builtin = "O" not in parts[1] if len(parts) > 1 else True
        return name, is_builtin
    return module_info, True
