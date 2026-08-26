from __future__ import annotations

from typing import Any

from nl2sql_core.models import QueryResult, SchemaSummary


class KafkaEngine:
    """占位：Kafka 非查询库，本期仅占位。"""

    id = "kafka"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        return False

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        return SchemaSummary(notes=["Kafka 引擎尚未实现（通常不作 NL 查询目标）"])

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        raise NotImplementedError("Kafka 引擎尚未实现")
