from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nl2sql_core.clarify.session import (
    auto_resolve_query,
    get_session,
    reply_clarify,
    start_clarify,
)
from nl2sql_core.config import (
    LLMSettings,
    ensure_data_dir,
    load_app_settings,
    load_datasources,
    load_rag_settings,
    merge_datasource_config,
)
from nl2sql_core.engines.registry import get_engine, list_engines
from nl2sql_core.eval.consistency import run_consistency
from nl2sql_core.llm.client import LLMClient
from nl2sql_core.pipeline import NL2SQLPipeline
from nl2sql_core.rag_client import RagClient
from nl2sql_core.rules.bootstrap import bootstrap
from nl2sql_core.rules.init import commit_bundle, init_from_datasource, write_bundle
from nl2sql_core.rules.nl_generate import generate_rules_from_nl
from nl2sql_core.rules.schema import Rule
from nl2sql_core.rules.store import RuleStore, normalize_dialect

STATIC_DIR = Path(__file__).resolve().parent / "static"
SETTINGS_FILE = ensure_data_dir() / "runtime_settings.json"

app = FastAPI(title="NL2SQL Web", version="0.3.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class QueryRequest(BaseModel):
    query: str
    datasource_id: str = "local-es"
    execute_query: str | dict[str, Any] | None = None
    mode: str = "auto"
    use_llm: bool = True
    skip_clarify: bool = False
    # True=多轮追问；False=静默单次改写 query（不向用户提问）
    interactive_clarify: bool = True
    clarify_session_id: str | None = None
    clarify_message: str | None = None


class DatasourceTestRequest(BaseModel):
    datasource_id: str = "local-es"


class RuntimeSettings(BaseModel):
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    rag_base_url: str = ""
    rag_access_key: str = ""
    rag_kb_id: str = ""
    es_hosts: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:9200"])
    es_username: str = ""
    es_password: str = ""
    es_default_index: str = "*"
    og_host: str = "127.0.0.1"
    og_port: int = 5434
    og_database: str = "postgres"
    og_username: str = "gaussdb"
    og_password: str = ""
    hbase_host: str = "127.0.0.1"
    hbase_rest_port: int = 16080
    hbase_thrift_port: int = 9090
    hbase_rest_url: str = ""


class RuleUpsertRequest(BaseModel):
    database_id: str = "local-es"
    rule: dict[str, Any]


class RuleSearchRequest(BaseModel):
    database_id: str = "local-es"
    query: str = ""
    rule_type: Optional[str] = None
    top_k: int = 20


class ClarifyStartRequest(BaseModel):
    query: str
    max_rounds: int = 3


class ClarifyReplyRequest(BaseModel):
    session_id: str
    message: str


class RulesGenerateRequest(BaseModel):
    database_id: str = "local-es"
    user_text: str
    include_schema: bool = True


class RulesImportRequest(BaseModel):
    database_id: str = "local-es"
    rules: list[dict[str, Any]]
    sync_rag: bool = True


class ConsistencyRequest(BaseModel):
    query: str
    datasource_id: str = "local-es"
    repeats: int = 3
    mode: str = "auto"


class RulesInitPreviewRequest(BaseModel):
    database_id: str = "local-es"
    include_llm_domain: bool = True


class RulesInitCommitRequest(BaseModel):
    database_id: str = ""
    from_file: str = ""
    bundle: dict[str, Any] | None = None
    recreate_kb: bool = True
    persist_kb: bool = True
    kb_name: str = ""


def _load_runtime() -> dict[str, Any]:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_runtime(data: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _llm() -> LLMClient:
    runtime = _load_runtime()
    base = LLMSettings()
    return LLMClient(
        LLMSettings(
            base_url=runtime.get("llm_base_url") or base.base_url,
            api_key=runtime.get("llm_api_key") or base.api_key,
            model=runtime.get("llm_model") or base.model,
        )
    )


def _es_cfg(ds: dict[str, Any]) -> dict[str, Any]:
    """兼容旧名：合并运行时连接配置。"""
    return merge_datasource_config(ds, _load_runtime())


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


async def _ping_datasource(ds_id: str, ds: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    et = str(ds.get("type") or "mock")
    item: dict[str, Any] = {"id": ds_id, "type": et, "ok": False}
    try:
        engine = get_engine(et)
        ping = getattr(engine, "ping", None)
        cfg = merge_datasource_config(ds, runtime)
        cfg = dict(cfg)
        cfg["timeout_sec"] = min(int(cfg.get("timeout_sec") or 8), 5)
        if callable(ping):
            detail = await asyncio.wait_for(ping(cfg), timeout=6)
            item.update(detail if isinstance(detail, dict) else {"ok": bool(detail)})
        else:
            item["ok"] = bool(await asyncio.wait_for(engine.test_connection(cfg), timeout=6))
    except Exception as e:
        item["ok"] = False
        item["error"] = str(e)
    return item


@app.get("/api/health")
async def health(datasource_id: str = Query("", description="只探测当前数据源；空则不测业务库")):
    app_s = load_app_settings()
    rag_s = load_rag_settings()
    runtime = _load_runtime()
    if runtime.get("rag_base_url"):
        rag_s.base_url = runtime["rag_base_url"]
    if runtime.get("rag_access_key"):
        rag_s.access_key = runtime["rag_access_key"]
    rag = RagClient(rag_s)
    rag_h = await rag.health()

    current: dict[str, Any] | None = None
    ds_id = (datasource_id or "").strip()
    if ds_id:
        if ds_id == "mock":
            current = {"id": "mock", "type": "mock", "ok": True, "via": "mock"}
        else:
            ds = (load_datasources() or {}).get(ds_id)
            if not ds:
                raise HTTPException(404, f"未知数据源: {ds_id}")
            current = await _ping_datasource(ds_id, ds, runtime)

    return {
        "ok": True,
        "app": {"name": app_s.name, "port": app_s.port, "kg_enabled": app_s.kg_enabled},
        "engines": list_engines(),
        "rag_core": {"base_url": rag_s.base_url, **rag_h},
        "datasource_id": ds_id or None,
        "current": current,
        "runtime_settings_loaded": bool(runtime),
        "local_rules": (ensure_data_dir() / "rules" / "local-es.json").exists(),
    }


@app.get("/api/settings")
async def get_settings():
    llm = LLMSettings()
    rag = load_rag_settings()
    runtime = _load_runtime()
    return {
        "llm_base_url": runtime.get("llm_base_url") or llm.base_url,
        "llm_api_key": runtime.get("llm_api_key") or llm.api_key,
        "llm_model": runtime.get("llm_model") or llm.model,
        "rag_base_url": runtime.get("rag_base_url") or rag.base_url,
        "rag_access_key": runtime.get("rag_access_key") or rag.access_key,
        "rag_kb_id": runtime.get("rag_kb_id") or rag.default_kb_id,
        "es_hosts": runtime.get("es_hosts") or ["http://127.0.0.1:9200"],
        "es_username": runtime.get("es_username") or "",
        "es_password": runtime.get("es_password") or "",
        "es_default_index": runtime.get("es_default_index") or "*",
        "og_host": runtime.get("og_host") or "127.0.0.1",
        "og_port": runtime.get("og_port") or 5434,
        "og_database": runtime.get("og_database") or "postgres",
        "og_username": runtime.get("og_username") or "gaussdb",
        "og_password": runtime.get("og_password") or "",
        "hbase_host": runtime.get("hbase_host") or "127.0.0.1",
        "hbase_rest_port": runtime.get("hbase_rest_port") or 16080,
        "hbase_thrift_port": runtime.get("hbase_thrift_port") or 9090,
        "hbase_rest_url": runtime.get("hbase_rest_url") or "",
    }


@app.post("/api/settings")
async def save_settings(body: RuntimeSettings):
    prev = _load_runtime()
    data = {**prev, **body.model_dump()}
    _save_runtime(data)
    return {"ok": True}


@app.get("/api/datasources")
async def list_datasources():
    return {"datasources": load_datasources(), "engines": list_engines()}


@app.post("/api/datasources/test")
async def test_datasource(body: DatasourceTestRequest):
    if body.datasource_id == "mock":
        ok = await get_engine("mock").test_connection({})
        return {"ok": ok, "type": "mock"}
    ds = load_datasources().get(body.datasource_id)
    if not ds:
        raise HTTPException(404, f"未知数据源: {body.datasource_id}")
    cfg = merge_datasource_config(ds, _load_runtime())
    engine = get_engine(cfg.get("type", "mock"))
    try:
        ping = getattr(engine, "ping", None)
        if callable(ping):
            detail = await ping(cfg)
            if isinstance(detail, dict):
                return {"type": cfg.get("type"), **detail}
        ok = await engine.test_connection(cfg)
        return {"ok": ok, "type": cfg.get("type")}
    except NotImplementedError as e:
        return {"ok": False, "type": cfg.get("type"), "error": str(e)}
    except Exception as e:
        return {"ok": False, "type": cfg.get("type"), "error": str(e)}


async def _prepare_query(body: QueryRequest) -> tuple[str, Any | None, bool]:
    """返回 (resolved_query, clarify_session|None, need_clarify)。"""
    q = body.query
    if body.skip_clarify or body.execute_query is not None or not body.use_llm:
        return q, None, False

    llm = _llm()
    # 续答始终走交互澄清
    if body.clarify_session_id and body.clarify_message is not None:
        session = await reply_clarify(body.clarify_session_id, body.clarify_message, llm)
        if not session.done:
            return body.query, session, True
        return session.resolved_query or body.query, session, False

    if body.interactive_clarify:
        session = await start_clarify(body.query, llm, max_rounds=3)
        if not session.done:
            return body.query, session, True
        return session.resolved_query or body.query, session, False

    session = await auto_resolve_query(body.query, llm)
    return session.resolved_query or body.query, session, False


@app.post("/api/query")
async def query(body: QueryRequest):
    """非流式：可选跳过澄清；需交互澄清时请用 /api/query/stream。"""
    q, session, need = await _prepare_query(body)
    if need and session is not None:
        return {
            "need_clarify": True,
            "clarify_session": session.model_dump(),
            "query": body.query,
        }

    pipe = NL2SQLPipeline()
    result = await pipe.run(
        q,
        datasource_id=body.datasource_id,
        execute_query=body.execute_query,
        mode=body.mode,
        use_llm=body.use_llm and body.execute_query is None,
    )
    data = result.model_dump()
    data["resolved_query"] = q
    data["interactive_clarify"] = body.interactive_clarify
    if session is not None:
        data["clarify_session_id"] = session.id
    return data


@app.post("/api/query/stream")
async def query_stream(body: QueryRequest):
    """步骤级 SSE。交互澄清可 need_clarify；关闭则静默改写后直接跑。"""

    async def gen():
        q = body.query
        try:
            if not body.skip_clarify and body.execute_query is None and body.use_llm:
                mode_msg = "多轮澄清中…" if body.interactive_clarify else "自动理解问句…"
                yield _sse("status", {"message": mode_msg, "interactive_clarify": body.interactive_clarify})
                q, session, need = await _prepare_query(body)
                if need and session is not None:
                    yield _sse(
                        "need_clarify",
                        {
                            "clarify_session": session.model_dump(),
                            "question": (session.messages[-1].content if session.messages else ""),
                        },
                    )
                    yield _sse("done", {"ok": False, "need_clarify": True})
                    return
                yield _sse(
                    "resolved_query",
                    {
                        "resolved_query": q,
                        "clarify_session_id": session.id if session else None,
                        "interactive_clarify": body.interactive_clarify,
                        "auto": not body.interactive_clarify,
                        "note": (session.messages[-1].content if session and session.messages else ""),
                    },
                )

            queue: asyncio.Queue = asyncio.Queue()

            async def on_event(event: str, payload: dict[str, Any]) -> None:
                await queue.put((event, payload))

            async def run_pipe() -> None:
                try:
                    pipe = NL2SQLPipeline()
                    await pipe.run(
                        q,
                        datasource_id=body.datasource_id,
                        execute_query=body.execute_query,
                        mode=body.mode,
                        use_llm=body.use_llm and body.execute_query is None,
                        on_event=on_event,
                    )
                except Exception as e:
                    await queue.put(("error", {"message": str(e)}))
                    await queue.put(("done", {"ok": False}))
                finally:
                    await queue.put((None, None))

            task = asyncio.create_task(run_pipe())
            while True:
                event, payload = await queue.get()
                if event is None:
                    break
                yield _sse(event, payload or {})
            await task
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            yield _sse("done", {"ok": False})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/schema/{datasource_id}")
async def schema(datasource_id: str):
    if datasource_id == "mock":
        summary = await get_engine("mock").fetch_schema({})
        return summary.model_dump()
    ds = load_datasources().get(datasource_id)
    if not ds:
        raise HTTPException(404, f"未知数据源: {datasource_id}")
    engine = get_engine(ds.get("type", "mock"))
    try:
        summary = await engine.fetch_schema(_es_cfg(ds))
        return summary.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.get("/api/rules")
async def list_rules(database_id: str = "local-es", rule_type: Optional[str] = None):
    store = RuleStore(database_id)
    rules = store.list_rules(rule_type)
    return {"count": len(rules), "rules": rules[:500]}


@app.post("/api/rules")
async def upsert_rule(body: RuleUpsertRequest):
    store = RuleStore(body.database_id)
    try:
        rule = Rule.model_validate(body.rule)
    except Exception:
        rule = body.rule
    saved = store.upsert(rule)
    return {"ok": True, "rule": saved}


@app.post("/api/rules/search")
async def search_rules(body: RuleSearchRequest):
    store = RuleStore(body.database_id)
    rules = await store.search(body.query, rule_type=body.rule_type, top_k=body.top_k)
    return {"count": len(rules), "rules": rules}


@app.post("/api/rules/bootstrap")
async def rules_bootstrap(database_id: str = "local-es"):
    return bootstrap(database_id)


@app.post("/api/rules/init/preview")
async def rules_init_preview(body: RulesInitPreviewRequest):
    try:
        bundle = await init_from_datasource(
            body.database_id,
            include_llm_domain=body.include_llm_domain,
            llm=_llm(),
        )
        path = write_bundle(bundle)
        return {
            "ok": True,
            "bundle_path": str(path),
            "counts": bundle.get("counts"),
            "warnings": bundle.get("warnings"),
            "engine": bundle.get("engine"),
            "database_id": bundle.get("database_id"),
            "generated_at": bundle.get("generated_at"),
            "rules": bundle.get("rules") or [],
        }
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/rules/init/commit")
async def rules_init_commit(body: RulesInitCommitRequest):
    try:
        src: Any = body.bundle
        if body.from_file:
            src = body.from_file
        if src is None:
            raise HTTPException(400, "需要 from_file 或 bundle")
        if isinstance(src, dict) and body.database_id:
            src = dict(src)
            src.setdefault("database_id", body.database_id)
        result = await commit_bundle(
            src,
            recreate_kb=body.recreate_kb,
            persist_kb=body.persist_kb,
            kb_name=body.kb_name or None,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/rules/generate_from_nl")
async def rules_generate_from_nl(body: RulesGenerateRequest):
    ds = load_datasources().get(body.database_id) or {"type": "elasticsearch"}
    dialect = normalize_dialect(str(ds.get("type") or "elasticsearch"))
    schema_hint = ""
    if body.include_schema:
        try:
            engine = get_engine(ds.get("type", "elasticsearch"))
            summary = await engine.fetch_schema(_es_cfg(ds))
            compact = []
            for idx in summary.indexes[:12]:
                fields = [f"{f.name}:{f.type}" for f in idx.fields[:30]]
                compact.append({"index": idx.name, "fields": fields})
            schema_hint = json.dumps(compact, ensure_ascii=False)
        except Exception as e:
            schema_hint = f"(schema 拉取失败: {e})"
    try:
        rules = await generate_rules_from_nl(
            body.user_text,
            database_id=body.database_id,
            dialect=dialect,
            schema_hint=schema_hint,
            llm=_llm(),
        )
        return {
            "ok": True,
            "count": len(rules),
            "rules": rules,
            "schema_hint_used": bool(schema_hint),
        }
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/rules/import")
async def rules_import(body: RulesImportRequest):
    """增量：勾选规则写入本地，并 upsert 到现有 rag KB。"""
    if not body.rules:
        raise HTTPException(400, "rules 为空")
    store = RuleStore(body.database_id)
    saved = []
    for r in body.rules:
        item = dict(r)
        item.setdefault("id", str(uuid.uuid4()))
        item.setdefault("database_id", body.database_id)
        saved.append(store.upsert(item))

    rag_result: dict[str, Any] = {"skipped": True}
    if body.sync_rag:
        try:
            rag_s = load_rag_settings()
            store.rag = RagClient(rag_s)
            kb_id = store.resolve_kb_id()
            if not kb_id:
                rag_result = await store.sync_to_rag(recreate_kb=True)
            else:
                ok = 0
                errors: list[str] = []
                for r in saved:
                    name = str(r.get("id") or r.get("description") or "rule")[:120]
                    try:
                        await store.rag.upsert_rule(kb_id, name=name, content=r, immediate=True)
                        ok += 1
                    except Exception as e:
                        errors.append(f"{name}: {e}")
                rag_result = {
                    "ok": not errors,
                    "kb_id": kb_id,
                    "synced": ok,
                    "total": len(saved),
                    "errors": errors[:8],
                    "recreate_kb": False,
                }
        except Exception as e:
            rag_result = {"ok": False, "error": str(e)}

    return {"ok": True, "imported_local": len(saved), "rag": rag_result, "rules": saved}


@app.post("/api/consistency/run")
async def consistency_run(body: ConsistencyRequest):
    try:
        return await run_consistency(
            body.query,
            datasource_id=body.datasource_id,
            repeats=body.repeats,
            mode=body.mode,
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/clarify/start")
async def clarify_start(body: ClarifyStartRequest):
    try:
        session = await start_clarify(body.query, _llm(), max_rounds=body.max_rounds or 3)
        return session.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/clarify/reply")
async def clarify_reply_api(body: ClarifyReplyRequest):
    try:
        session = await reply_clarify(body.session_id, body.message, _llm())
        return session.model_dump()
    except KeyError:
        raise HTTPException(404, "会话不存在")
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.get("/api/clarify/{session_id}")
async def clarify_get(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s.model_dump()
