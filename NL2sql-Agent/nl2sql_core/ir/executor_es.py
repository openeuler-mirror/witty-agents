from __future__ import annotations

import time
from typing import Any

from nl2sql_core.ir.compile_sql import (
    compile_outer_sql,
    compile_semi_join_sql,
    format_ir_for_display,
)
from nl2sql_core.ir.schema import QueryIR
from nl2sql_core.models import QueryResult
from nl2sql_core.safety import clamp_size
from nl2sql_core.sql_stabilize import default_order_cols_for_index

# 单次 IN 字面量上限，避免请求过大
_IN_CHUNK = 800


def _normalize_ir(ir: QueryIR, config: dict[str, Any]) -> QueryIR:
    max_size = clamp_size(int(config.get("max_size") or 100))
    # 最终结果统一为数据源 max_size（当前 100），避免模型写 50 导致截断抖动
    order_by = list(ir.order_by or [])
    if not order_by:
        order_by = default_order_cols_for_index(ir.from_index, ir.select)
    return ir.model_copy(update={"limit": max_size, "order_by": order_by})


def _extract_id_set(result: QueryResult, foreign_key: str) -> set[str]:
    cols = result.columns or []
    col_idx = 0
    for j, c in enumerate(cols):
        if str(c).lower() == foreign_key.lower():
            col_idx = j
            break
    ids: set[str] = set()
    for row in result.rows or []:
        if col_idx < len(row) and row[col_idx] is not None:
            ids.add(str(row[col_idx]))
    return ids


async def execute_ir_on_es(
    ir: QueryIR,
    engine: Any,
    config: dict[str, Any],
) -> QueryResult:
    """
    按 IR 多步执行：每个 semi_join 单表查关联键 → 按 local_key 求交集 → 回表主表。
    每步只发 ES 可执行的单表 SQL（无 IN 子查询）。
    """
    start = time.time()
    warnings: list[str] = []
    step_sqls: list[str] = []
    step_meta: list[dict[str, Any]] = []
    ir = _normalize_ir(ir, config)

    if not ir.semi_joins:
        sql = compile_outer_sql(ir, None, join_key=None)
        step_sqls.append(sql)
        result = await engine.execute(sql, config, mode="sql")
        return _finalize(ir, result, step_sqls, step_meta, warnings, start)

    # local_key -> 交集集合；第一个半连接初始化，后续与之求交
    key_sets: dict[str, set[str]] = {}
    for i, sj in enumerate(ir.semi_joins, 1):
        sql = compile_semi_join_sql(sj)
        step_sqls.append(sql)
        # 半连接需要较大 key 集合，勿用展示用 max_size=100 截断
        sj_cap = max(1000, min(int(sj.limit or 10000), 50000))
        sj_cfg = {**config, "max_size": sj_cap}
        sub = await engine.execute(sql, sj_cfg, mode="sql")
        ids = _extract_id_set(sub, sj.foreign_key)
        step_meta.append(
            {"step": i, "role": "semi_join", "index": sj.index, "sql": sql, "keys": len(ids)}
        )
        warnings.append(f"半连接[{i}] {sj.index}.{sj.foreign_key} → {len(ids)} 个键")
        if sj.local_key not in key_sets:
            key_sets[sj.local_key] = ids
        else:
            key_sets[sj.local_key] &= ids

    # 多个不同 local_key 时全部施加（少见）
    if not key_sets:
        empty = QueryResult(columns=[], rows=[], row_count=0, mode="ir", latency_ms=0)
        return _finalize(ir, empty, step_sqls, step_meta, warnings + ["无半连接键"], start)

    # 若所有 local_key 相同，一次 IN；否则 AND 多个 IN（分批取交集思路：先取最小集合作主过滤）
    if len(key_sets) == 1:
        join_key, id_set = next(iter(key_sets.items()))
        result = await _outer_with_ids(ir, engine, config, join_key, id_set, step_sqls, step_meta)
        return _finalize(ir, result, step_sqls, step_meta, warnings, start)

    # 多 key：选最小集合作主 IN，其余在内存过滤（主表结果再滤）
    primary_key = min(key_sets.keys(), key=lambda k: len(key_sets[k]))
    result = await _outer_with_ids(
        ir, engine, config, primary_key, key_sets[primary_key], step_sqls, step_meta
    )
    for k, s in key_sets.items():
        if k == primary_key:
            continue
        if k not in (result.columns or []):
            warnings.append(f"结果中无列 {k}，无法施加额外半连接过滤")
            continue
        idx = result.columns.index(k)
        filtered = [row for row in result.rows if idx < len(row) and str(row[idx]) in s]
        result.rows = filtered
        result.row_count = len(filtered)
        warnings.append(f"附加半连接 {k} 后保留 {result.row_count} 行")
    return _finalize(ir, result, step_sqls, step_meta, warnings, start)


async def _outer_with_ids(
    ir: QueryIR,
    engine: Any,
    config: dict[str, Any],
    join_key: str,
    id_set: set[str],
    step_sqls: list[str],
    step_meta: list[dict[str, Any]],
) -> QueryResult:
    if not id_set:
        sql = compile_outer_sql(ir, [], join_key=join_key)
        step_sqls.append(sql)
        step_meta.append({"step": len(step_sqls), "role": "outer", "sql": sql, "keys": 0})
        return QueryResult(
            columns=[],
            rows=[],
            row_count=0,
            mode="ir",
            query=sql,
            warnings=["半连接交集为空"],
            raw={"empty_join": True},
        )

    ids = sorted(id_set, key=str)
    # 分块 IN，合并结果（按 join_key+整行去重）
    merged_cols: list[str] | None = None
    merged_rows: list[list[Any]] = []
    seen: set[str] = set()
    for offset in range(0, len(ids), _IN_CHUNK):
        chunk = ids[offset : offset + _IN_CHUNK]
        sql = compile_outer_sql(ir, chunk, join_key=join_key)
        step_sqls.append(sql)
        step_meta.append(
            {
                "step": len(step_sqls),
                "role": "outer",
                "sql": sql[:500] + ("…" if len(sql) > 500 else ""),
                "keys": len(chunk),
            }
        )
        part = await engine.execute(sql, config, mode="sql")
        if merged_cols is None:
            merged_cols = list(part.columns or [])
        for row in part.rows or []:
            key = "|".join("" if x is None else str(x) for x in row)
            if key in seen:
                continue
            seen.add(key)
            merged_rows.append(row)

    # 合并后再按 IR order_by / 行内容稳定排序，再截断
    if merged_rows and merged_cols and ir.order_by:
        col_idx = {c.lower(): i for i, c in enumerate(merged_cols)}
        keys = [col_idx[o.lower()] for o in ir.order_by if o.lower() in col_idx]

        def _row_key(row: list[Any]) -> tuple:
            cells = []
            for i in keys or range(len(merged_cols)):
                v = row[i] if i < len(row) else None
                cells.append((1, "") if v is None else (0, str(v)))
            return tuple(cells)

        merged_rows.sort(key=_row_key)

    return QueryResult(
        columns=merged_cols or [],
        rows=merged_rows[: ir.limit],
        row_count=min(len(merged_rows), ir.limit),
        mode="ir",
        query=format_ir_for_display(ir),
    )


def _finalize(
    ir: QueryIR,
    result: QueryResult,
    step_sqls: list[str],
    step_meta: list[dict[str, Any]],
    warnings: list[str],
    start: float,
) -> QueryResult:
    result.mode = "ir"
    result.query = format_ir_for_display(ir)
    result.warnings = list(warnings) + list(result.warnings or [])
    result.raw = {
        "ir": ir.model_dump(by_alias=True),
        "steps": step_meta or [{"sql": s} for s in step_sqls],
        "step_sqls": step_sqls,
        "engine_raw": result.raw,
    }
    result.latency_ms = (time.time() - start) * 1000
    return result
