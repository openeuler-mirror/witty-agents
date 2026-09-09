from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any
from urllib.parse import quote

import httpx

from nl2sql_core.models import QueryResult, SchemaField, SchemaIndex, SchemaSummary


def _host(config: dict[str, Any]) -> str:
    return str(config.get("host") or "127.0.0.1")


def rest_base(config: dict[str, Any]) -> str:
    if config.get("rest_url"):
        return str(config["rest_url"]).rstrip("/")
    return f"http://{_host(config)}:{int(config.get('rest_port') or 8080)}"


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class HBaseEngine:
    """原生 HBase：优先 REST（8080），否则探测 Thrift/Master 端口是否可连。"""

    id = "hbase"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        detail = await self.ping(config)
        return bool(detail.get("ok"))

    async def ping(self, config: dict[str, Any]) -> dict[str, Any]:
        timeout = float(config.get("timeout_sec") or 8)
        host = _host(config)
        base = rest_base(config)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{base}/version")
                if r.status_code < 400 and "html" not in (r.headers.get("content-type") or "").lower():
                    return {"ok": True, "via": "rest", "version": (r.text or "").splitlines()[0][:160]}
                r2 = await client.get(base + "/", headers={"Accept": "text/plain"})
                if r2.status_code < 400 and "html" not in (r2.text[:80].lower()):
                    return {"ok": True, "via": "rest-root"}
        except Exception as e:
            rest_err = str(e)
        else:
            rest_err = f"REST {base} 不是 HBase（HTTP {getattr(r, 'status_code', '?')}）"

        thrift_port = int(config.get("thrift_port") or 9090)
        master_port = int(config.get("master_ipc_port") or 16000)
        zk_port = int(config.get("zookeeper_port") or 2181)
        if await asyncio.to_thread(_tcp_open, host, thrift_port):
            return {"ok": True, "via": f"thrift:{thrift_port}", "warning": "Thrift 端口可连，REST 不可用，schema/scan 需 REST"}
        if await asyncio.to_thread(_tcp_open, host, master_port):
            return {"ok": True, "via": f"master:{master_port}", "warning": "Master 端口可连，REST 不可用"}
        if await asyncio.to_thread(_tcp_open, host, zk_port):
            return {"ok": True, "via": f"zk:{zk_port}", "warning": "ZooKeeper 可连，HBase REST 不可用"}
        return {"ok": False, "error": rest_err}

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        timeout = float(config.get("timeout_sec") or 15)
        base = rest_base(config)
        notes: list[str] = []
        tables: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(base + "/", headers={"Accept": "text/plain"})
                r.raise_for_status()
                if "<html" in r.text[:80].lower():
                    raise RuntimeError("REST 根路径返回 HTML，不是 HBase REST")
                tables = [ln.strip() for ln in r.text.splitlines() if ln.strip() and not ln.startswith("<")]
                indexes: list[SchemaIndex] = []
                for name in tables[:80]:
                    fields: list[SchemaField] = []
                    try:
                        sr = await client.get(
                            f"{base}/{quote(name, safe=':')}/schema",
                            headers={"Accept": "application/json"},
                        )
                        if sr.status_code < 300:
                            body = sr.json()
                            cfs = body.get("ColumnSchema") or body.get("column_schema") or []
                            if isinstance(cfs, dict):
                                cfs = [cfs]
                            for cf in cfs:
                                if isinstance(cf, dict):
                                    n = cf.get("name") or cf.get("id") or "cf"
                                    fields.append(SchemaField(name=str(n), type="column_family", description="HBase column family"))
                    except Exception:
                        pass
                    if not fields:
                        fields = [SchemaField(name="rowkey", type="bytes", description="行键")]
                    else:
                        fields = [SchemaField(name="rowkey", type="bytes", description="行键")] + fields
                    indexes.append(SchemaIndex(name=name, fields=fields))
                return SchemaSummary(indexes=indexes, notes=notes)
        except Exception as e:
            ping = await self.ping(config)
            if ping.get("ok"):
                notes.append(f"端口可连（{ping.get('via')}），但无法拉表结构: {e}")
                return SchemaSummary(notes=notes)
            raise

    async def sample_values(
        self,
        config: dict[str, Any],
        *,
        names: list[str],
        sample_rows: int = 5,
        top_terms: int = 20,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        timeout = float(config.get("timeout_sec") or 15)
        base = rest_base(config)
        out: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                for table in names:
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        break
                    rows: list[dict[str, Any]] = []
                    terms: dict[str, list[str]] = {}
                    try:
                        r = await client.get(
                            f"{base}/{quote(table, safe=':')}/*",
                            params={"limit": max(1, sample_rows)},
                            headers={"Accept": "application/json"},
                        )
                        if r.status_code < 300:
                            data = r.json()
                            rows = self._rows_from_rest(data)[:sample_rows]
                            for rec in rows:
                                for k, v in rec.items():
                                    if k == "rowkey":
                                        continue
                                    terms.setdefault(k, [])
                                    if str(v) not in terms[k]:
                                        terms[k].append(str(v))
                                    terms[k] = terms[k][:top_terms]
                    except Exception:
                        pass
                    out[table] = {"rows": rows, "terms": terms}
        except Exception:
            pass
        return out

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        start = time.time()
        plan = query
        if isinstance(plan, str):
            plan = json.loads(plan)
        if not isinstance(plan, dict):
            raise ValueError("HBase 需要 JSON scan 计划（table/filters/limit）")
        table = str(plan.get("table") or "").strip()
        if not table:
            raise ValueError("scan 计划缺少 table")
        limit = int(plan.get("limit") or config.get("max_size") or 100)
        timeout = float(config.get("timeout_sec") or 30)
        base = rest_base(config)
        prefix = plan.get("prefix") or plan.get("row_prefix") or "*"
        path = f"{base}/{quote(table, safe=':')}/{quote(str(prefix), safe='*:')}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                path,
                params={"limit": max(1, min(limit, 500))},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            recs = self._rows_from_rest(r.json())
        recs = self._apply_filters(recs, plan.get("filters") or [])
        recs = recs[: max(1, min(limit, 500))]
        cols: list[str] = []
        for rec in recs:
            for k in rec:
                if k not in cols:
                    cols.append(k)
        rows = [[rec.get(c) for c in cols] for rec in recs]
        return QueryResult(
            columns=cols,
            rows=rows,
            row_count=len(rows),
            latency_ms=(time.time() - start) * 1000,
            mode="scan",
            query=plan,
            raw={"rest": path},
        )

    @staticmethod
    def _rows_from_rest(data: Any) -> list[dict[str, Any]]:
        rows_in = []
        if isinstance(data, dict):
            rows_in = data.get("Row") or data.get("row") or []
        elif isinstance(data, list):
            rows_in = data
        out: list[dict[str, Any]] = []
        for row in rows_in:
            if not isinstance(row, dict):
                continue
            rec: dict[str, Any] = {"rowkey": row.get("key") or row.get("row")}
            cells = row.get("Cell") or row.get("cell") or []
            if isinstance(cells, dict):
                cells = [cells]
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                col = cell.get("column") or cell.get("qualifier") or "cf"
                rec[str(col)] = cell.get("$") or cell.get("value")
            out.append(rec)
        return out

    @staticmethod
    def _apply_filters(rows: list[dict[str, Any]], filters: list[Any]) -> list[dict[str, Any]]:
        if not filters:
            return rows
        kept = []
        for rec in rows:
            ok = True
            for f in filters:
                if not isinstance(f, dict):
                    continue
                col = str(f.get("col") or f.get("column") or "")
                op = str(f.get("op") or "=")
                val = str(f.get("value") or "")
                got = "" if rec.get(col) is None else str(rec.get(col))
                if op == "=" and got != val:
                    ok = False
                    break
                if op == "!=" and got == val:
                    ok = False
                    break
                if op == "like" and val.replace("%", "") not in got:
                    ok = False
                    break
            if ok:
                kept.append(rec)
        return kept
