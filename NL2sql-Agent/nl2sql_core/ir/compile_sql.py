from __future__ import annotations

from typing import Any

from nl2sql_core.ir.schema import Pred, QueryIR, SemiJoin


def _sql_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def pred_sql(p: Pred) -> str:
    op = (p.op or "=").lower()
    f = p.field
    if op == "between":
        if isinstance(p.value, (list, tuple)) and len(p.value) >= 2:
            return f"{f} BETWEEN {_sql_literal(p.value[0])} AND {_sql_literal(p.value[1])}"
        raise ValueError(f"between 需要二元数组: {p.value}")
    if op == "in":
        vals = p.value if isinstance(p.value, (list, tuple)) else [p.value]
        if not vals:
            return "1=0"
        return f"{f} IN ({', '.join(_sql_literal(x) for x in vals)})"
    if op == "like":
        return f"{f} LIKE {_sql_literal(p.value)}"
    if op not in ("=", "!=", ">", ">=", "<", "<="):
        raise ValueError(f"不支持的 op: {op}")
    return f"{f} {op} {_sql_literal(p.value)}"


def where_sql(preds: list[Pred], *, op: str = "and") -> str:
    if not preds:
        return ""
    joiner = " OR " if (op or "and").lower() == "or" else " AND "
    body = joiner.join(pred_sql(p) for p in preds)
    if (op or "and").lower() == "or" and len(preds) > 1:
        return f"({body})"
    return body


def select_sql(cols: list[str]) -> str:
    if not cols or cols == ["*"] or (len(cols) == 1 and cols[0] == "*"):
        return "*"
    out = []
    for c in cols:
        c = c.strip()
        if not c or not all(ch.isalnum() or ch == "_" for ch in c):
            raise ValueError(f"非法 select 列: {c}")
        out.append(c)
    return ", ".join(out) if out else "*"


def compile_semi_join_sql(sj: SemiJoin) -> str:
    if sj.where_or_groups:
        parts = []
        for g in sj.where_or_groups:
            if not g:
                continue
            parts.append(f"({where_sql(g, op='and')})")
        cond = " OR ".join(parts) if parts else ""
    else:
        cond = where_sql(sj.where, op=getattr(sj, "where_op", "and") or "and")
    lim = max(1, min(int(sj.limit or 10000), 50000))
    sql = f"SELECT {sj.foreign_key} FROM {sj.index}"
    if cond:
        sql += f" WHERE {cond}"
    sql += f" LIMIT {lim}"
    return sql


def compile_outer_sql(ir: QueryIR, id_list: list[str] | None, *, join_key: str | None) -> str:
    cols = select_sql(ir.select)
    parts = [f"SELECT {cols} FROM {ir.from_index}"]
    conds: list[str] = []
    if ir.where:
        conds.append(where_sql(ir.where))
    if join_key is not None:
        if id_list is None:
            pass
        elif not id_list:
            conds.append("1=0")
        else:
            lit = ", ".join(_sql_literal(x) for x in id_list)
            conds.append(f"{join_key} IN ({lit})")
    if conds:
        parts.append("WHERE " + " AND ".join(conds))
    if ir.order_by:
        safe = []
        for o in ir.order_by:
            o = o.strip()
            if o and all(ch.isalnum() or ch in "_ " for ch in o):
                safe.append(o)
        if safe:
            parts.append("ORDER BY " + ", ".join(safe))
    parts.append(f"LIMIT {ir.limit}")
    return " ".join(parts)


def format_ir_for_display(ir: QueryIR) -> str:
    lines: list[str] = []
    n = len(ir.semi_joins)
    total = n + 1
    if n:
        lines.append(f"-- Elasticsearch 执行计划：半连接 ×{n} → 回表 {ir.from_index}")
    else:
        lines.append(f"-- Elasticsearch 执行计划：单表 {ir.from_index}")
    for i, sj in enumerate(ir.semi_joins, 1):
        lines.append(f"-- 步骤 {i}/{total}")
        lines.append(compile_semi_join_sql(sj) + ";")
    lines.append(f"-- 步骤 {total}/{total}")
    if ir.semi_joins:
        key = ir.semi_joins[0].local_key
        outer_where = where_sql(ir.where)
        chunk = f"SELECT {select_sql(ir.select)} FROM {ir.from_index} WHERE "
        if outer_where:
            chunk += outer_where + " AND "
        chunk += f"{key} IN (/* 半连接交集 */)"
        chunk += f" LIMIT {ir.limit};"
        lines.append(chunk)
    else:
        lines.append(compile_outer_sql(ir, None, join_key=None) + ";")
    if ir.reason:
        lines.append(f"-- reason: {ir.reason}")
    return "\n".join(lines)
