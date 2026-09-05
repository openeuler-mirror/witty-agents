from __future__ import annotations

from typing import Any

from nl2sql_core.models import QueryResult, SchemaField, SchemaIndex, SchemaSummary


class MockEngine:
    """无 ES 时用于前端演示。"""

    id = "mock"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        return True

    async def ping(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "via": "mock"}

    async def sample_values(
        self,
        config: dict[str, Any],
        *,
        names: list[str],
        sample_rows: int = 5,
        top_terms: int = 20,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        return {
            "person_info_es": {
                "rows": [{"XM": "张三", "XB": "男", "SFZH": "110101199001011234"}],
                "terms": {"XB": ["男", "女"]},
            }
        }

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        return SchemaSummary(
            indexes=[
                SchemaIndex(
                    name="person_info_es",
                    fields=[
                        SchemaField(name="XM", type="text", description="姓名"),
                        SchemaField(name="XB", type="keyword", description="性别"),
                        SchemaField(name="SFZH", type="keyword", description="身份证号"),
                    ],
                )
            ],
            notes=["这是 mock schema，仅用于无 ES 时演示"],
        )

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        return QueryResult(
            columns=["XM", "XB", "SFZH"],
            rows=[["张三", "男", "110101199001011234"]],
            row_count=1,
            raw={"mock": True, "query": query},
            latency_ms=1.0,
            warnings=["使用 mock 引擎，非真实数据"],
            mode="mock",
            query=query,
        )
