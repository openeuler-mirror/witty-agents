from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nl2sql_core.models import QueryResult, SchemaSummary


@runtime_checkable
class QueryEngine(Protocol):
    id: str

    async def test_connection(self, config: dict[str, Any]) -> bool: ...

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult: ...

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary: ...

    async def sample_values(
        self,
        config: dict[str, Any],
        *,
        names: list[str],
        sample_rows: int = 5,
        top_terms: int = 20,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        """每表抽样行 + keyword 高频值。引擎未实现则返回空 dict。"""
        ...
