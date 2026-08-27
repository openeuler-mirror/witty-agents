from __future__ import annotations

import re
from typing import Any


_WRITE_PATTERNS = [
    r"\bdelete\b",
    r"\bupdate\b",
    r"\bindex\b",
    r"\bcreate\b",
    r"\bdrop\b",
    r"\binsert\b",
    r"_delete_by_query",
    r"update_by_query",
]


def assert_readonly_sql(sql: str) -> None:
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("show") or s.startswith("describe") or s.startswith("explain")):
        # ES SQL 也可能是 SELECT ...
        if not s.startswith("select"):
            raise ValueError("默认只读：仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN 类语句")
    for pat in _WRITE_PATTERNS:
        if re.search(pat, s) and not s.startswith("select"):
            raise ValueError(f"检测到可能的写操作，已拦截: {pat}")


def clamp_size(size: int, max_size: int = 100) -> int:
    return max(1, min(int(size), int(max_size)))


def ensure_index_allowed(index: str, whitelist: list[str] | None) -> None:
    if not whitelist:
        return
    for w in whitelist:
        if w == "*" or index == w or (w.endswith("*") and index.startswith(w[:-1])):
            return
    raise ValueError(f"索引不在白名单内: {index}")
