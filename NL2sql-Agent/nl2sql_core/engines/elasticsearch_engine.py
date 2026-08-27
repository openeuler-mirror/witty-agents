from __future__ import annotations

import re
import time
from typing import Any

import httpx

from nl2sql_core.models import QueryResult, SchemaField, SchemaIndex, SchemaSummary


def strip_unsupported_es_sql(sql: str) -> str:
    """去掉 Elasticsearch SQL 明确不支持的语法（方言兜底，与业务字段无关）。"""
    return re.sub(r"\bSELECT\s+DISTINCT\b", "SELECT", sql.strip(), flags=re.I)


def repair_sql(sql: str) -> str:
    """引擎方言兜底。业务字段别名/库表约定一律来自 rag-core 规则，此处不改写。"""
    return strip_unsupported_es_sql(sql)


class ElasticsearchEngine:
    id = "elasticsearch"

    async def test_connection(self, config: dict[str, Any]) -> bool:
        host = self._primary_host(config)
        async with httpx.AsyncClient(
            timeout=config.get("timeout_sec", 30), verify=config.get("verify_certs", False)
        ) as client:
            r = await client.get(f"{host}/", auth=self._auth(config))
            return r.status_code == 200

    async def fetch_schema(self, config: dict[str, Any]) -> SchemaSummary:
        host = self._primary_host(config)
        pattern = config.get("default_index") or "*"
        async with httpx.AsyncClient(
            timeout=config.get("timeout_sec", 30), verify=config.get("verify_certs", False)
        ) as client:
            r = await client.get(f"{host}/{pattern}/_mapping", auth=self._auth(config))
            r.raise_for_status()
            data = r.json()
        indexes: list[SchemaIndex] = []
        for idx_name, body in data.items():
            props = (
                body.get("mappings", {}).get("properties")
                or body.get("mappings", {}).get("doc", {}).get("properties")
                or {}
            )
            fields = [
                SchemaField(name=k, type=self._field_type(v), description="")
                for k, v in props.items()
            ]
            indexes.append(SchemaIndex(name=idx_name, fields=fields))
        return SchemaSummary(indexes=indexes)

    async def execute(
        self,
        query: str | dict[str, Any],
        config: dict[str, Any],
        *,
        mode: str = "auto",
    ) -> QueryResult:
        start = time.time()
        host = self._primary_host(config)
        max_size = int(config.get("max_size", 100))
        timeout = config.get("timeout_sec", 30)
        auth = self._auth(config)
        verify = config.get("verify_certs", False)
        warnings: list[str] = []

        resolved = mode
        if mode == "auto":
            resolved = "sql" if await self._sql_available(host, auth, verify, timeout) else "dsl"
            if resolved == "dsl":
                warnings.append("ES SQL 不可用或探测失败，已降级为 Query DSL")

        async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
            if resolved == "sql":
                if not isinstance(query, str):
                    raise ValueError("SQL 模式需要字符串查询")
                sql_raw = query.strip()
                sql = strip_unsupported_es_sql(sql_raw)
                if sql != sql_raw:
                    warnings.append("已去掉 ES SQL 不支持的 DISTINCT")
                # 含 IN(SELECT) 时先拆分再执行
                if re.search(r"\bIN\s*\(\s*SELECT\b", sql, re.I):
                    result = await self._execute_semi_join_sql(
                        client, host, sql, auth=auth, max_size=max_size, start=start
                    )
                    result.warnings = warnings + list(result.warnings or [])
                    return result
                repaired = repair_sql(sql)
                if repaired != sql:
                    warnings.append("已自动纠正字段别名")
                return await self._execute_sql(
                    client,
                    host,
                    repaired,
                    auth=auth,
                    max_size=max_size,
                    start=start,
                    warnings=warnings,
                )

            if isinstance(query, str):
                import json

                query = json.loads(query)
            dsl = dict(query)
            index = (
                dsl.pop("_index", None)
                or dsl.pop("index", None)
                or config.get("target_index")
                or config.get("default_index")
                or "*"
            )
            if isinstance(index, list):
                index = ",".join(str(x) for x in index)
            dsl.setdefault("size", max_size)
            # 不强制业务字段白名单；由 LLM/规则在 DSL 中自行指定 _source
            r = await client.post(f"{host}/{index}/_search", json=dsl, auth=auth)
            if r.status_code >= 400:
                raise ValueError(f"ES DSL 失败 ({index}): {r.text[:400]}")
            payload = r.json()
            hits = payload.get("hits", {}).get("hits", [])
            columns, rows = self._hits_to_table(hits)
            return QueryResult(
                columns=columns,
                rows=rows[:max_size],
                row_count=len(rows),
                raw=payload,
                latency_ms=round((time.time() - start) * 1000, 2),
                warnings=warnings,
                mode="dsl",
                query={"index": index, **dsl},
            )

    async def _execute_sql(
        self,
        client: httpx.AsyncClient,
        host: str,
        sql: str,
        *,
        auth,
        max_size: int,
        start: float,
        warnings: list[str],
    ) -> QueryResult:
        body = {"query": sql, "fetch_size": max_size}
        r = await client.post(f"{host}/_sql?format=json", json=body, auth=auth)
        if r.status_code >= 400:
            r2 = await client.post(f"{host}/_xpack/sql?format=json", json=body, auth=auth)
            if r2.status_code >= 400:
                err: Any = r2.text
                try:
                    payload = r2.json().get("error", r2.text)
                    if isinstance(payload, dict):
                        err = (
                            payload.get("reason")
                            or (payload.get("root_cause") or [{}])[0].get("reason")
                            or str(payload)
                        )
                    else:
                        err = payload
                except Exception:
                    pass
                raise ValueError(f"ES SQL 失败: {err}")
            r = r2
        payload = r.json()
        columns = [c.get("name", f"c{i}") for i, c in enumerate(payload.get("columns", []))]
        rows = payload.get("rows", [])
        return QueryResult(
            columns=columns,
            rows=rows[:max_size],
            row_count=len(rows),
            raw=payload,
            latency_ms=round((time.time() - start) * 1000, 2),
            warnings=warnings,
            mode="sql",
            query=sql,
        )

    async def _execute_semi_join_sql(
        self,
        client: httpx.AsyncClient,
        host: str,
        sql: str,
        *,
        auth,
        max_size: int,
        start: float,
    ) -> QueryResult:
        """ES SQL 不支持 IN (SELECT…)；拆成两段执行。

        外层已有 WHERE 业务过滤时优先「外层先取候选 ID → 再过滤内层」，
        避免内层大表 LIMIT 截断导致与外层几乎无交集而空结果。
        """
        parsed = self._parse_in_subquery(sql)
        if not parsed:
            raise ValueError(
                "ES SQL 不支持 IN 子查询，且无法自动拆分该 SQL；请改为单索引查询或简化条件"
            )
        idcol = parsed["idcol"]
        sub_sql = parsed["sub_sql"].strip()
        outer_prefix = parsed["outer_prefix"].strip()
        outer_rest = parsed["outer_rest"].strip()

        prefix = re.sub(rf"\b{re.escape(idcol)}\s*$", "", outer_prefix, flags=re.I).rstrip()
        prefix = re.sub(r"\b(AND|OR)\s*$", "", prefix, flags=re.I).rstrip()
        outer_has_filter = bool(re.search(r"\bWHERE\b", prefix, re.I)) and not re.search(
            r"\bWHERE\s*$", prefix, re.I
        )

        if outer_has_filter:
            return await self._semi_join_outer_first(
                client,
                host,
                sql,
                idcol=idcol,
                prefix=prefix,
                sub_sql=sub_sql,
                outer_rest=outer_rest,
                auth=auth,
                max_size=max_size,
                start=start,
            )
        return await self._semi_join_sub_first(
            client,
            host,
            sql,
            idcol=idcol,
            prefix=prefix,
            sub_sql=sub_sql,
            outer_rest=outer_rest,
            auth=auth,
            max_size=max_size,
            start=start,
        )

    async def _semi_join_outer_first(
        self,
        client: httpx.AsyncClient,
        host: str,
        sql: str,
        *,
        idcol: str,
        prefix: str,
        sub_sql: str,
        outer_rest: str,
        auth,
        max_size: int,
        start: float,
    ) -> QueryResult:
        probe_limit = 15000
        probe_sql = re.sub(r"\bWHERE\s*$", "", prefix, flags=re.I).rstrip()
        if not re.search(r"\bLIMIT\b", probe_sql, re.I):
            probe_sql = f"{probe_sql} LIMIT {probe_limit}"
        outer = await self._execute_sql(
            client,
            host,
            repair_sql(probe_sql),
            auth=auth,
            max_size=probe_limit,
            start=start,
            warnings=[],
        )
        try:
            id_idx = next(i for i, c in enumerate(outer.columns) if str(c).lower() == idcol.lower())
        except StopIteration as exc:
            raise ValueError(
                f"外层查询未选出关联字段 {idcol}，无法做半连接；请在 SELECT 中包含 {idcol}"
            ) from exc

        cand_ids: list[str] = []
        seen: set[str] = set()
        for row in outer.rows:
            if not row or row[id_idx] in (None, ""):
                continue
            vid = str(row[id_idx])
            if vid not in seen:
                seen.add(vid)
                cand_ids.append(vid)
        if not cand_ids:
            return QueryResult(
                columns=outer.columns,
                rows=[],
                row_count=0,
                raw={"probe": probe_sql, "ids": 0},
                latency_ms=round((time.time() - start) * 1000, 2),
                warnings=["外层过滤无候选关联键"],
                mode="sql",
                query=sql,
            )

        sub_id_expr = self._subquery_id_expr(sub_sql)
        hit_ids: set[str] = set()
        batch_size = 800
        for i in range(0, len(cand_ids), batch_size):
            batch = cand_ids[i : i + batch_size]
            id_list = ",".join("'" + x.replace("'", "''") + "'" for x in batch)
            injected = self._inject_in_filter(sub_sql, sub_id_expr, id_list)
            if not re.search(r"\bLIMIT\b", injected, re.I):
                injected = f"{injected} LIMIT {batch_size}"
            sub = await self._execute_sql(
                client, host, injected, auth=auth, max_size=batch_size, start=start, warnings=[]
            )
            for row in sub.rows:
                if row and row[0] not in (None, ""):
                    hit_ids.add(str(row[0]))

        lim = max_size
        m_lim = re.search(r"\bLIMIT\s+(\d+)", outer_rest, re.I)
        if m_lim:
            lim = int(m_lim.group(1))
        filtered = [row for row in outer.rows if row and str(row[id_idx]) in hit_ids][:lim]
        warnings = [
            "ES 不支持 IN(SELECT)，已按「外层候选 → 内层过滤」拆分执行",
            f"外层候选 {len(cand_ids)} 个关联键，内层命中 {len(hit_ids)} 个",
        ]
        if not filtered and cand_ids:
            warnings.append("内层条件与外层候选无交集")
        return QueryResult(
            columns=outer.columns,
            rows=filtered,
            row_count=len(filtered),
            raw={"probe": probe_sql, "candidates": len(cand_ids), "hits": len(hit_ids)},
            latency_ms=round((time.time() - start) * 1000, 2),
            warnings=warnings,
            mode="sql",
            query=sql,
        )

    async def _semi_join_sub_first(
        self,
        client: httpx.AsyncClient,
        host: str,
        sql: str,
        *,
        idcol: str,
        prefix: str,
        sub_sql: str,
        outer_rest: str,
        auth,
        max_size: int,
        start: float,
    ) -> QueryResult:
        run_sub = sub_sql
        if not re.search(r"\bLIMIT\b", run_sub, re.I):
            run_sub = f"{run_sub} LIMIT 5000"
        sub = await self._execute_sql(
            client, host, run_sub, auth=auth, max_size=5000, start=start, warnings=[]
        )
        ids = [str(row[0]) for row in sub.rows if row and row[0] not in (None, "")]
        # 去重保序
        uniq: list[str] = []
        seen: set[str] = set()
        for i in ids:
            if i not in seen:
                seen.add(i)
                uniq.append(i)
        ids = uniq
        if not ids:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                raw={"subquery": run_sub, "ids": 0},
                latency_ms=round((time.time() - start) * 1000, 2),
                warnings=["子查询无命中关联键（可能过滤过严、LIMIT 截断或数据无交集）"],
                mode="sql",
                query=sql,
            )
        id_list = ",".join("'" + i.replace("'", "''") + "'" for i in ids[:2000])
        if not re.search(r"\bWHERE\b", prefix, re.I):
            outer_sql = f"{prefix} WHERE {idcol} IN ({id_list})"
        elif re.search(r"\bWHERE\s*$", prefix, re.I) or re.search(r"\b(?:AND|OR)\s*$", prefix, re.I):
            outer_sql = f"{prefix} {idcol} IN ({id_list})"
        else:
            outer_sql = f"{prefix} AND {idcol} IN ({id_list})"
        if outer_rest:
            outer_sql = f"{outer_sql} {outer_rest}"
        elif not re.search(r"\bLIMIT\b", outer_sql, re.I):
            outer_sql = f"{outer_sql} LIMIT {max_size}"
        result = await self._execute_sql(
            client,
            host,
            repair_sql(outer_sql),
            auth=auth,
            max_size=max_size,
            start=start,
            warnings=[],
        )
        result.warnings = [
            f"ES 不支持 IN(SELECT)，已拆成两段执行（内层命中 {len(ids)} 个关联键）",
            f"subSQL: {run_sub[:200]}",
        ]
        if result.row_count == 0 and ids:
            result.warnings.append(
                "外层结果为 0：内层关联键与外层过滤条件无交集；"
                "请确认业务过滤是否写在外层 WHERE，并核对召回规则中的字段/别名"
            )
        result.query = sql
        return result

    @staticmethod
    def _subquery_id_expr(sub_sql: str) -> str:
        m = re.match(r"SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM\b", sub_sql, re.I | re.S)
        if not m:
            raise ValueError("无法从子查询解析关联键列，请在 SELECT 中显式写出关联字段")
        first = m.group(1).split(",")[0].strip()
        # 去掉 AS 别名
        first = re.split(r"\s+AS\s+", first, flags=re.I)[0].strip()
        if re.search(r"\(|\*", first) or not first:
            raise ValueError("子查询 SELECT 首列无法作为关联键，请显式写出关联字段")
        return first

    @staticmethod
    def _inject_in_filter(sub_sql: str, id_expr: str, id_list: str) -> str:
        clause = f"{id_expr} IN ({id_list})"
        m = re.search(r"\b(GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b", sub_sql, re.I)
        head = sub_sql[: m.start()] if m else sub_sql
        tail = sub_sql[m.start() :] if m else ""
        head = head.rstrip()
        where_m = re.search(r"\bWHERE\b", head, re.I)
        if where_m:
            before = head[: where_m.end()]
            cond = head[where_m.end() :].strip()
            # 必须给原 WHERE 加括号，否则 OR ... AND id IN 会因优先级漏掉关联键约束
            return f"{before} ({cond}) AND {clause} {tail}".strip()
        return f"{head} WHERE {clause} {tail}".strip()

    @staticmethod
    def _parse_in_subquery(sql: str) -> dict[str, str] | None:
        """解析 `... <idcol> IN ( SELECT ... ) ...`，子查询用括号深度匹配。"""
        m = re.search(r"\b([A-Za-z_][\w]*)\s+IN\s*\(\s*(SELECT\b)", sql, re.I)
        if not m:
            return None
        idcol = m.group(1)
        select_start = m.start(2)
        # 从 IN 后的 '(' 开始（select_start 前一个非空白应是 '('）
        open_paren = sql.rfind("(", 0, select_start)
        if open_paren < 0:
            return None
        depth = 0
        i = open_paren
        in_str = False
        str_ch = ""
        while i < len(sql):
            ch = sql[i]
            if in_str:
                if ch == str_ch:
                    # 处理 SQL 字符串内 '' 转义
                    if ch == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
                i += 1
                continue
            if ch in ("'", '"'):
                in_str = True
                str_ch = ch
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    sub_sql = sql[open_paren + 1 : i].strip()
                    outer_prefix = sql[: m.start(1)].rstrip()
                    outer_rest = sql[i + 1 :].strip()
                    return {
                        "idcol": idcol,
                        "sub_sql": sub_sql,
                        "outer_prefix": outer_prefix + " " + idcol,
                        "outer_rest": outer_rest,
                    }
            i += 1
        return None

    async def _sql_available(self, host: str, auth, verify, timeout) -> bool:
        try:
            async with httpx.AsyncClient(timeout=min(10, timeout), verify=verify) as client:
                r = await client.post(
                    f"{host}/_sql?format=json",
                    json={"query": "SELECT 1", "fetch_size": 1},
                    auth=auth,
                )
                if r.status_code < 500:
                    return r.status_code in (200, 400)
                r2 = await client.post(
                    f"{host}/_xpack/sql?format=json",
                    json={"query": "SELECT 1", "fetch_size": 1},
                    auth=auth,
                )
                return r2.status_code in (200, 400)
        except Exception:
            return False

    @staticmethod
    def _primary_host(config: dict[str, Any]) -> str:
        hosts = config.get("hosts") or ["http://127.0.0.1:9200"]
        if isinstance(hosts, str):
            return hosts.rstrip("/")
        return str(hosts[0]).rstrip("/")

    @staticmethod
    def _auth(config: dict[str, Any]):
        user = config.get("username") or ""
        password = config.get("password") or ""
        if user:
            return (user, password)
        return None

    @staticmethod
    def _field_type(node: dict[str, Any]) -> str:
        if not isinstance(node, dict):
            return "object"
        if "type" in node:
            return str(node["type"])
        if "properties" in node:
            return "object"
        return "text"

    @staticmethod
    def _hits_to_table(hits: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
        if not hits:
            return [], []
        src_keys: set[str] = set()
        for h in hits:
            src_keys.update((h.get("_source") or {}).keys())
        ordered = sorted(src_keys)

        # 若某列值与 _id 完全相同则不再重复展示 _id（不假设列名）
        include_id = True
        sample = hits[:20]
        for h in sample:
            src = h.get("_source") or {}
            _id = h.get("_id")
            if _id is None:
                continue
            if any(str(v) == str(_id) for v in src.values()):
                include_id = False
                break

        keys = (["_id"] if include_id else []) + ordered
        rows: list[list[Any]] = []
        for h in hits:
            src = h.get("_source") or {}
            row: list[Any] = []
            if include_id:
                row.append(h.get("_id"))
            row.extend(src.get(k) for k in ordered)
            rows.append(row)
        return keys, rows
