"""执行前统一 LIMIT，并在缺省时补稳定 ORDER BY，避免无序截断导致结果抖动。"""
from __future__ import annotations

import re
from typing import Any

from nl2sql_core.safety import clamp_size


_TABLE_ORDER: dict[str, list[str]] = {
    "ticket_sales": ["id_no", "ticket_no"],
    "tag_person": ["idcardno"],
    "resident_population": ["idcardno"],
}
_ID_PREF = ("idcardno", "id_no", "ticket_no", "zjhm")


def default_order_cols_for_index(index: str, select: list[str] | None = None) -> list[str]:
    """按主索引/投影列给出稳定排序键。"""
    idx = (index or "").strip().split(".")[-1].lower()
    if select:
        cleaned = []
        for c in select:
            c = (c or "").strip()
            if not c or c == "*":
                continue
            c = c.split(".")[-1]
            if c and all(ch.isalnum() or ch == "_" for ch in c):
                cleaned.append(c)
        if cleaned:
            lower_map = {x.lower(): x for x in cleaned}
            preferred = [lower_map[p] for p in _ID_PREF if p in lower_map]
            if preferred:
                return preferred
            return cleaned[:3]
    if idx in _TABLE_ORDER:
        return list(_TABLE_ORDER[idx])
    return ["idcardno", "id_no"]


def _from_table(sql: str) -> str:
    m = re.search(r"\bFROM\s+([`\"\w.]+)", sql, re.I)
    if not m:
        return ""
    return m.group(1).strip('`"').split(".")[-1].lower()


def _select_idents(sql: str) -> list[str] | None:
    m = re.search(r"\bSELECT\s+(.*?)\s+FROM\b", sql, re.I | re.S)
    if not m:
        return None
    body = m.group(1).strip()
    if re.match(r"(?i)^(distinct\s+)?\*$", body):
        return None
    out: list[str] = []
    for part in body.split(","):
        part = re.split(r"\s+AS\s+", part.strip(), flags=re.I)[0].strip()
        part = part.split(".")[-1].strip('`"')
        if part and all(c.isalnum() or c == "_" for c in part):
            out.append(part)
    return out or None


def order_cols_for_sql(sql: str) -> list[str]:
    idents = _select_idents(sql)
    return default_order_cols_for_index(_from_table(sql), idents)


def stabilize_select_sql(sql: str, max_size: int = 100) -> tuple[str, list[str]]:
    """强制 LIMIT=max_size；若无 ORDER BY 则按表/投影补排序。"""
    warnings: list[str] = []
    s = sql.strip().rstrip(";")
    lim = clamp_size(int(max_size), int(max_size))

    if re.search(r"\bLIMIT\s+\d+", s, re.I):
        s_new = re.sub(r"\bLIMIT\s+\d+", f"LIMIT {lim}", s, count=1, flags=re.I)
        if s_new != s:
            warnings.append(f"LIMIT 已统一为 {lim}")
        s = s_new
    else:
        s = f"{s} LIMIT {lim}"
        warnings.append(f"已补 LIMIT {lim}")

    if not re.search(r"\bORDER\s+BY\b", s, re.I):
        cols = order_cols_for_sql(s)
        order = ", ".join(cols)
        s = re.sub(
            r"\bLIMIT\s+\d+\s*$",
            f"ORDER BY {order} LIMIT {lim}",
            s,
            count=1,
            flags=re.I,
        )
        warnings.append(f"已补 ORDER BY {order}")
    return s, warnings


def stabilize_dsl(dsl: dict[str, Any], max_size: int = 100) -> tuple[dict[str, Any], list[str]]:
    """DSL：size 固定为 max_size；缺 sort 时补稳定排序（允许缺字段）。"""
    warnings: list[str] = []
    out = dict(dsl)
    lim = clamp_size(int(max_size), int(max_size))
    prev = out.get("size")
    out["size"] = lim
    if prev is not None and int(prev) != lim:
        warnings.append(f"DSL size 已统一为 {lim}")
    if "sort" not in out:
        out["sort"] = [
            {"idcardno": {"order": "asc", "unmapped_type": "keyword"}},
            {"id_no": {"order": "asc", "unmapped_type": "keyword"}},
            {"ticket_no": {"order": "asc", "unmapped_type": "keyword"}},
            "_doc",
        ]
        warnings.append("已补 DSL sort（证件号/票号）")
    return out, warnings
