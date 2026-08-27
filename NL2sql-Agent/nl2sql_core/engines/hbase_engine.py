from __future__ import annotations

from typing import Any

from nl2sql_core.models import QueryResult, SchemaSummary


class HBaseEngine:
    """占位：本期不实现真实查询。"""

    id = "hbase"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        return False

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        return SchemaSummary(notes=["HBase 引擎尚未实现"])

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        raise NotImplementedError("HBase 引擎尚未实现；请改用 elasticsearch 数据源")
