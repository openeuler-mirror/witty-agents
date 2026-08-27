from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


RuleType = Literal["ddl", "mapping", "example", "experience"]
Dialect = Literal["elasticsearch", "opengauss", "shared"]
RuleScope = Literal["schema", "dialect", "domain"]


class Rule(BaseModel):
    id: str = ""
    database_id: str
    rule_type: RuleType
    description: str = ""
    # 引擎方言：检索时只保留当前引擎 + shared
    dialect: Dialect = "shared"
    # schema=ddl/mapping；dialect=引擎语法；domain=业务常识（非问句 SQL 板子）
    scope: RuleScope = "schema"
    # ddl
    table: Optional[str] = None
    ddl: Optional[str] = None
    # mapping
    mapping_type: Optional[str] = None
    col: Optional[str] = None
    # example
    query: Optional[str] = None
    sql: Optional[str] = None
    # experience / shared
    tables: Optional[list[dict[str, Any]]] = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_content(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True, exclude={"extra"})
        data.update(self.extra)
        return data
