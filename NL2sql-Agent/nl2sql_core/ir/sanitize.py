"""IR 通用清洗：同字段矛盾等值 AND 改写 + 对照 schema 的字段存在性校验。

不绑定具体业务问句 / 城市 / 标签文案；只按 IR 结构与 schema 工作。
"""
from __future__ import annotations

from typing import Any

from nl2sql_core.ir.schema import Pred, QueryIR, SemiJoin
from nl2sql_core.models import SchemaSummary

# 半连接自关联时推断关联键的通用候选（按优先级）；最终仍以 schema 是否存在为准
_JOIN_KEY_CANDIDATES = (
    "idcardno",
    "id_no",
    "zjhm",
    "sfzh",
    "person_id",
    "user_id",
    "id",
)


def schema_to_field_map(summary: SchemaSummary | None) -> dict[str, set[str]]:
    """index/table 名 → 小写字段集合。"""
    out: dict[str, set[str]] = {}
    if summary is None:
        return out
    for idx in summary.indexes or []:
        name = (idx.name or "").strip()
        if not name:
            continue
        fields = {str(f.name).lower() for f in (idx.fields or []) if f.name}
        out[name] = fields
        # 兼容带集群前缀的名字
        short = name.split(":")[-1]
        if short and short not in out:
            out[short] = fields
    return out


def _norm_val(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return json_dumps_stable(v)
    return str(v)


def json_dumps_stable(v: Any) -> str:
    import json

    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _eq_groups(preds: list[Pred]) -> dict[str, list[Pred]]:
    """field → 多个等值谓词（op='='）。"""
    groups: dict[str, list[Pred]] = {}
    for p in preds:
        op = (p.op or "=").lower()
        if op != "=":
            continue
        groups.setdefault(p.field, []).append(p)
    return groups


def _contradictory_eq_fields(preds: list[Pred]) -> dict[str, list[Any]]:
    """同字段多个不同等值 → 矛盾（单行不可能同时满足）。"""
    out: dict[str, list[Any]] = {}
    for field, ps in _eq_groups(preds).items():
        vals = []
        seen: set[str] = set()
        for p in ps:
            key = _norm_val(p.value)
            if key in seen:
                continue
            seen.add(key)
            vals.append(p.value)
        if len(vals) >= 2:
            out[field] = vals
    return out


def _pick_join_key(fields: set[str], preferred: list[str] | None = None) -> str | None:
    lower = {f.lower(): f for f in fields}
    for c in list(preferred or []) + list(_JOIN_KEY_CANDIDATES):
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _actual_field_name(fields: set[str], name: str) -> str | None:
    lower = {f.lower(): f for f in fields}
    return lower.get((name or "").lower())


def rewrite_contradictory_eq_and(ir: QueryIR) -> tuple[QueryIR, list[str]]:
    """
    将「同一 where 列表里同字段多个等值 AND」拆成可求交的半连接。

    - semi_join.where 内矛盾：拆成多个同 index 半连接（每个保留一个等值）
    - 主表 where 内矛盾：保留第一个等值在主表，其余变为对 from 的自半连接求交
    """
    warnings: list[str] = []
    new_joins: list[SemiJoin] = []

    for sj in ir.semi_joins:
        if (sj.where_op or "and").lower() == "or" or sj.where_or_groups:
            new_joins.append(sj)
            continue
        bad = _contradictory_eq_fields(sj.where)
        if not bad:
            new_joins.append(sj)
            continue
        # 一次只拆一个矛盾字段（通常双标签只有一个）；其余矛盾字段递归可再跑一遍
        field, values = next(iter(bad.items()))
        other = [p for p in sj.where if not (p.field == field and (p.op or "=").lower() == "=")]
        warnings.append(
            f"半连接 {sj.index}.{field} 存在矛盾等值 AND，已拆成 {len(values)} 次求交半连接"
        )
        for v in values:
            new_joins.append(
                SemiJoin(
                    index=sj.index,
                    local_key=sj.local_key,
                    foreign_key=sj.foreign_key,
                    where=other + [Pred(field=field, op="=", value=v)],
                    where_op="and",
                    limit=sj.limit,
                )
            )

    # 主表 where 矛盾
    main_where = list(ir.where)
    main_bad = _contradictory_eq_fields(main_where)
    extra_joins: list[SemiJoin] = []
    if main_bad:
        # 需要自关联键
        preferred = list(ir.order_by or [])
        # 无 schema 时仍尝试候选名（后续字段校验会再收紧）
        join_key = None
        for c in preferred + list(_JOIN_KEY_CANDIDATES):
            if c:
                join_key = c
                break
        if join_key:
            for field, values in main_bad.items():
                eq_preds = [
                    p
                    for p in main_where
                    if p.field == field and (p.op or "=").lower() == "="
                ]
                other = [
                    p
                    for p in main_where
                    if not (p.field == field and (p.op or "=").lower() == "=")
                ]
                # 第一个等值留在主表；其余半连接
                main_where = other + [eq_preds[0]]
                for v in values[1:]:
                    extra_joins.append(
                        SemiJoin(
                            index=ir.from_index,
                            local_key=join_key,
                            foreign_key=join_key,
                            where=[Pred(field=field, op="=", value=v)],
                            where_op="and",
                            limit=10000,
                        )
                    )
                warnings.append(
                    f"主表 {ir.from_index}.{field} 矛盾等值 AND，已改为自半连接求交（键 {join_key}）"
                )
        else:
            warnings.append(
                f"主表存在矛盾等值 AND，但无法推断关联键，未自动拆分: {list(main_bad)}"
            )

    new_ir = ir.model_copy(
        update={"where": main_where, "semi_joins": new_joins + extra_joins}
    )
    return new_ir, warnings


def validate_fields_against_schema(
    ir: QueryIR,
    field_map: dict[str, set[str]],
) -> tuple[QueryIR, list[str]]:
    """
    对照 schema 去掉不存在的投影/排序/过滤字段；索引或关联键不存在则报错。

    field_map 为空时跳过（schema 不可用）。
    """
    warnings: list[str] = []
    if not field_map:
        return ir, warnings

    def fields_of(index: str) -> set[str] | None:
        if index in field_map:
            return field_map[index]
        # 大小写不敏感匹配
        for k, v in field_map.items():
            if k.lower() == index.lower():
                return v
        return None

    from_fields = fields_of(ir.from_index)
    if from_fields is None:
        raise ValueError(
            f"索引/表不存在于当前 schema: {ir.from_index}；可选: {', '.join(sorted(field_map)[:20])}"
        )

    # select
    select = list(ir.select or ["*"])
    if select and select != ["*"] and not (len(select) == 1 and select[0] == "*"):
        kept_sel = []
        for c in select:
            if c == "*" or _actual_field_name(from_fields, c):
                kept_sel.append(_actual_field_name(from_fields, c) or c)
            else:
                warnings.append(f"已去掉不存在的 select 字段 {ir.from_index}.{c}")
        select = kept_sel or ["*"]

    # order_by
    order_by = []
    for c in ir.order_by or []:
        actual = _actual_field_name(from_fields, c)
        if actual:
            order_by.append(actual)
        else:
            warnings.append(f"已去掉不存在的 order_by 字段 {ir.from_index}.{c}")

    # main where
    where: list[Pred] = []
    for p in ir.where or []:
        actual = _actual_field_name(from_fields, p.field)
        if actual:
            where.append(p.model_copy(update={"field": actual}))
        else:
            warnings.append(f"已去掉不存在的 where 字段 {ir.from_index}.{p.field}")

    new_joins: list[SemiJoin] = []
    for sj in ir.semi_joins:
        sj_fields = fields_of(sj.index)
        if sj_fields is None:
            raise ValueError(f"半连接索引不存在于当前 schema: {sj.index}")
        lk = _actual_field_name(from_fields, sj.local_key)
        fk = _actual_field_name(sj_fields, sj.foreign_key)
        if not lk:
            raise ValueError(
                f"半连接 local_key 不存在: {ir.from_index}.{sj.local_key}"
            )
        if not fk:
            raise ValueError(
                f"半连接 foreign_key 不存在: {sj.index}.{sj.foreign_key}"
            )
        sj_where: list[Pred] = []
        for p in sj.where or []:
            actual = _actual_field_name(sj_fields, p.field)
            if actual:
                sj_where.append(p.model_copy(update={"field": actual}))
            else:
                warnings.append(f"已去掉不存在的半连接条件 {sj.index}.{p.field}")
        groups: list[list[Pred]] = []
        for g in sj.where_or_groups or []:
            ng = []
            for p in g:
                actual = _actual_field_name(sj_fields, p.field)
                if actual:
                    ng.append(p.model_copy(update={"field": actual}))
                else:
                    warnings.append(
                        f"已去掉不存在的半连接 OR 条件 {sj.index}.{p.field}"
                    )
            if ng:
                groups.append(ng)
        new_joins.append(
            SemiJoin(
                index=sj.index,
                local_key=lk,
                foreign_key=fk,
                where=sj_where,
                where_op=sj.where_op,
                where_or_groups=groups,
                limit=sj.limit,
            )
        )

    return (
        ir.model_copy(
            update={
                "select": select,
                "where": where,
                "order_by": order_by,
                "semi_joins": new_joins,
            }
        ),
        warnings,
    )


def sanitize_ir(
    ir: QueryIR,
    field_map: dict[str, set[str]] | None = None,
) -> tuple[QueryIR, list[str]]:
    """先拆矛盾等值 AND，再做字段存在性校验。可多跑一轮拆分。"""
    warnings: list[str] = []
    cur = ir
    for _ in range(3):
        cur, w = rewrite_contradictory_eq_and(cur)
        warnings.extend(w)
        if not w:
            break
    if field_map:
        # 主表矛盾拆分时若关联键不在 schema，换成 schema 内候选
        from_fields = None
        for k, v in field_map.items():
            if k.lower() == cur.from_index.lower():
                from_fields = v
                break
        if from_fields:
            preferred = list(cur.order_by or [])
            key = _pick_join_key(from_fields, preferred)
            if key:
                fixed_joins = []
                for sj in cur.semi_joins:
                    if (
                        sj.index.lower() == cur.from_index.lower()
                        and sj.local_key.lower() not in from_fields
                    ):
                        fixed_joins.append(
                            sj.model_copy(update={"local_key": key, "foreign_key": key})
                        )
                    else:
                        fixed_joins.append(sj)
                cur = cur.model_copy(update={"semi_joins": fixed_joins})
        cur, w2 = validate_fields_against_schema(cur, field_map)
        warnings.extend(w2)
    return cur, warnings
