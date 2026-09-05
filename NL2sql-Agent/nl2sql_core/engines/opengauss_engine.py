from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from nl2sql_core.models import QueryResult, SchemaField, SchemaIndex, SchemaSummary
from nl2sql_core.safety import assert_readonly_sql, clamp_size


def _conn_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": config.get("host") or "127.0.0.1",
        "port": int(config.get("port") or 5432),
        "dbname": config.get("database") or "postgres",
        "user": config.get("username") or "gaussdb",
        "password": config.get("password") or "",
        "connect_timeout": int(min(10, config.get("timeout_sec") or 10)),
    }


def _connect(config: dict[str, Any]):
    import psycopg2

    return psycopg2.connect(**_conn_kwargs(config))


def _quote_ident(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        raise ValueError(f"非法标识符: {name}")
    return '"' + name.replace('"', '""') + '"'


class OpenGaussEngine:
    id = "opengauss"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        def _ping() -> bool:
            conn = _connect(config)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                return True
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_ping)
        except Exception:
            return False

    async def ping(self, config: dict[str, Any]) -> dict[str, Any]:
        def _ping() -> None:
            conn = _connect(config)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_ping)
            kw = _conn_kwargs(config)
            return {"ok": True, "via": f"{kw['host']}:{kw['port']}/{kw['dbname']}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        schema_name = config.get("schema") or "public"

        def _load() -> SchemaSummary:
            conn = _connect(config)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                    """,
                    (schema_name,),
                )
                by_table: dict[str, list[SchemaField]] = {}
                for table_name, column_name, data_type in cur.fetchall():
                    if str(table_name).startswith("pg_"):
                        continue
                    by_table.setdefault(str(table_name), []).append(
                        SchemaField(name=str(column_name), type=str(data_type), description="")
                    )
                indexes = [SchemaIndex(name=n, fields=fs) for n, fs in by_table.items()]
                return SchemaSummary(indexes=indexes)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def sample_values(
        self,
        config: dict[str, Any],
        *,
        names: list[str],
        sample_rows: int = 5,
        top_terms: int = 20,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        def _sample() -> dict[str, Any]:
            out: dict[str, Any] = {}
            conn = _connect(config)
            try:
                cur = conn.cursor()
                for table in names:
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        break
                    try:
                        ident = _quote_ident(table)
                        cur.execute(f"SELECT * FROM {ident} LIMIT %s", (max(1, sample_rows),))
                        cols = [d[0] for d in (cur.description or [])]
                        rows = []
                        for row in cur.fetchall():
                            rec = {}
                            for k, v in zip(cols, row):
                                if v is None:
                                    continue
                                s = v if isinstance(v, (int, float, bool)) else str(v)
                                if isinstance(s, str) and len(s) > 80:
                                    s = s[:80] + "…"
                                rec[k] = s
                            rows.append(rec)
                        terms: dict[str, list[str]] = {}
                        for col in cols[:8]:
                            try:
                                cur.execute(
                                    f"SELECT { _quote_ident(col) } AS v, COUNT(*) "
                                    f"FROM {ident} WHERE { _quote_ident(col) } IS NOT NULL "
                                    f"GROUP BY 1 ORDER BY 2 DESC LIMIT %s",
                                    (max(1, top_terms),),
                                )
                                vals = [str(r[0]) for r in cur.fetchall() if r[0] not in (None, "")]
                                if vals:
                                    terms[col] = vals
                            except Exception:
                                conn.rollback()
                        out[table] = {"rows": rows, "terms": terms}
                    except Exception:
                        conn.rollback()
                        out[table] = {"rows": [], "terms": {}}
                return out
            finally:
                conn.close()

        return await asyncio.to_thread(_sample)

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        if not isinstance(query, str):
            raise ValueError("OpenGauss 需要 SQL 字符串")
        sql = query.strip().rstrip(";")
        assert_readonly_sql(sql)
        if not re.search(r"\blimit\b", sql, re.I):
            sql = f"{sql} LIMIT {clamp_size(int(config.get('max_size') or 100))}"
        start = time.time()

        def _run() -> tuple[list[str], list[list[Any]]]:
            conn = _connect(config)
            try:
                conn.set_session(readonly=True, autocommit=True)
            except Exception:
                pass
            try:
                cur = conn.cursor()
                cur.execute(sql)
                cols = [d[0] for d in (cur.description or [])]
                rows = [list(r) for r in cur.fetchall()]
                return cols, rows
            finally:
                conn.close()

        cols, rows = await asyncio.to_thread(_run)
        return QueryResult(
            columns=cols,
            rows=rows,
            row_count=len(rows),
            latency_ms=(time.time() - start) * 1000,
            mode="sql",
            query=sql,
        )
