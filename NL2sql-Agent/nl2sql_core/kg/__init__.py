"""KG 验证占位 — 本期不实现。

后续可在此接入实体抽取、建图与多跳验证。
pipeline 中通过 config.kg.enabled 调用；默认跳过。
"""

from __future__ import annotations

from typing import Any


def verify(result: Any, rules: list[dict] | None = None) -> dict[str, Any]:
    """占位：始终返回 skipped。"""
    return {
        "status": "skipped",
        "enabled": False,
        "message": "KG 验证本期未启用（接口已预留）",
        "inconsistencies": [],
        "graph": {"nodes": [], "edges": []},
    }
