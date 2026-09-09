from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


CmpOp = Literal["=", "!=", ">", ">=", "<", "<=", "like", "in", "between"]


class Pred(BaseModel):
    field: str
    op: CmpOp = "="
    value: Any = None

    @field_validator("field")
    @classmethod
    def _field_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(f"非法字段名: {v}")
        return v


class SemiJoin(BaseModel):
    """外层 local_key ∈ 子查询 foreign_key（子查询带 where）。"""

    index: str
    local_key: str
    foreign_key: str
    where: list[Pred] = Field(default_factory=list)
    # 同一 semi_join 内多个 where：and（默认）或 or（如车次 G% 或 D%）
    where_op: Literal["and", "or"] = "and"
    # 合并拆坏的 OR 分支时使用：[(A AND B), (A AND C)] → (A AND B) OR (A AND C)
    where_or_groups: list[list[Pred]] = Field(default_factory=list)
    limit: int = 10000

    @field_validator("index", "local_key", "foreign_key")
    @classmethod
    def _ident(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(f"非法标识符: {v}")
        return v


class QueryIR(BaseModel):
    version: str = "1.0"
    from_index: str = Field(alias="from")
    select: list[str] = Field(default_factory=lambda: ["*"])
    where: list[Pred] = Field(default_factory=list)
    semi_joins: list[SemiJoin] = Field(default_factory=list)
    limit: int = 100
    order_by: list[str] = Field(default_factory=list)
    reason: str = ""

    model_config = {"populate_by_name": True}

    @field_validator("from_index")
    @classmethod
    def _from_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(f"非法 from: {v}")
        return v

    @field_validator("limit")
    @classmethod
    def _limit_ok(cls, v: int) -> int:
        return max(1, min(int(v), 100))


def parse_ir(data: dict[str, Any]) -> QueryIR:
    """从 LLM JSON 解析 IR；兼容 query 嵌套或顶层字段。"""
    raw = dict(data)
    if isinstance(raw.get("query"), dict) and ("from" in raw["query"] or "semi_joins" in raw["query"]):
        nested = dict(raw["query"])
        if raw.get("reason") and not nested.get("reason"):
            nested["reason"] = raw["reason"]
        raw = nested
    allowed = {"version", "from", "select", "where", "semi_joins", "limit", "order_by", "reason"}
    cleaned = {k: v for k, v in raw.items() if k in allowed}
    if "from" not in cleaned and raw.get("index"):
        cleaned["from"] = raw["index"]
    ir = QueryIR.model_validate(cleaned)
    return merge_or_semi_joins(ir)


def _join_preds(sj: SemiJoin) -> list[Pred]:
    if sj.where_or_groups:
        out: list[Pred] = []
        for g in sj.where_or_groups:
            out.extend(g)
        return out
    return list(sj.where or [])


def _should_merge_group_as_or(group: list[SemiJoin]) -> bool:
    """
    仅当连续半连接像「同一维度的模式备选」(like/in) 时合并为 OR。

    等值条件（如 tag_name='A' 与 tag_name='B'）必须保留为多次求交（AND），
    不能并成 OR。
    """
    if len(group) <= 1:
        return False
    for sj in group:
        preds = _join_preds(sj)
        if not preds:
            # 空 where 不参与 OR 合并
            return False
        ops = {(p.op or "=").lower() for p in preds}
        if not ops.issubset({"like", "in"}):
            return False
    return True


def merge_or_semi_joins(ir: QueryIR) -> QueryIR:
    """
    合并「同 index + 同关联键、且均为 like/in 备选」的连续半连接为 where_op=or。
    等值多值半连接保持独立（求交），避免双标签等被误并成 OR。
    """
    if len(ir.semi_joins) <= 1:
        return ir
    merged: list[SemiJoin] = []
    i = 0
    joins = list(ir.semi_joins)
    while i < len(joins):
        cur = joins[i]
        group = [cur]
        j = i + 1
        while j < len(joins):
            nxt = joins[j]
            if (
                nxt.index == cur.index
                and nxt.local_key == cur.local_key
                and nxt.foreign_key == cur.foreign_key
            ):
                group.append(nxt)
                j += 1
            else:
                break
        if len(group) == 1 or not _should_merge_group_as_or(group):
            merged.extend(group)
        else:
            groups = [list(g.where) for g in group if g.where]
            if not groups:
                merged.extend(group)
            else:
                merged.append(
                    SemiJoin(
                        index=cur.index,
                        local_key=cur.local_key,
                        foreign_key=cur.foreign_key,
                        where=[],
                        where_op="or",
                        where_or_groups=groups,
                        limit=max(g.limit for g in group),
                    )
                )
        i = j if len(group) > 1 else i + 1
    return ir.model_copy(update={"semi_joins": merged})
