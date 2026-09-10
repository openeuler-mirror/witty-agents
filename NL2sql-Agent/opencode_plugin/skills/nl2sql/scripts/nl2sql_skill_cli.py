#!/usr/bin/env python3
"""
OpenCode Skill 本地入口：复用 nl2sql_core，不启动 Web 端口。
用法见同目录上级 SKILL.md。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import (  # noqa: E402
    PKG_ROOT,
    dump,
    llm_client,
    load_runtime,
    merge_ds,
    read_json_arg,
    save_runtime,
)


async def cmd_health(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import ensure_data_dir, load_app_settings, load_datasources, load_rag_settings
    from nl2sql_core.engines.registry import get_engine, list_engines
    from nl2sql_core.rag_client import RagClient

    app_s = load_app_settings()
    rag_s = load_rag_settings()
    runtime = load_runtime()
    if runtime.get("rag_base_url"):
        rag_s.base_url = runtime["rag_base_url"]
    if runtime.get("rag_access_key"):
        rag_s.access_key = runtime["rag_access_key"]
    rag_h = await RagClient(rag_s).health()

    current = None
    ds_id = (args.datasource_id or "").strip()
    if ds_id:
        if ds_id == "mock":
            current = {"id": "mock", "type": "mock", "ok": True, "via": "mock"}
        else:
            ds = (load_datasources() or {}).get(ds_id)
            if not ds:
                raise SystemExit(f"未知数据源: {ds_id}")
            et = str(ds.get("type") or "mock")
            item: dict[str, Any] = {"id": ds_id, "type": et, "ok": False}
            try:
                cfg = merge_ds(ds)
                engine = get_engine(et)
                ping = getattr(engine, "ping", None)
                if callable(ping):
                    detail = await ping(cfg)
                    if isinstance(detail, dict):
                        item.update(detail)
                    else:
                        item["ok"] = bool(detail)
                else:
                    item["ok"] = await engine.test_connection(cfg)
            except Exception as e:
                item["error"] = str(e)
            current = item

    return {
        "ok": True,
        "pkg_root": str(PKG_ROOT),
        "app": {"name": app_s.name, "port": app_s.port, "kg_enabled": app_s.kg_enabled},
        "engines": list_engines(),
        "rag_core": {"base_url": rag_s.base_url, **rag_h},
        "datasource_id": ds_id or None,
        "current": current,
        "runtime_settings_loaded": bool(runtime),
        "local_rules": (ensure_data_dir() / "rules" / "local-es.json").exists(),
        "note": "skill 本地模式，无需启动 Web :8199",
    }


def cmd_settings_get(_: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import LLMSettings, load_rag_settings

    llm = LLMSettings()
    rag = load_rag_settings()
    runtime = load_runtime()
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
        "settings_file": str(__import__("_common", fromlist=["SETTINGS_FILE"]).SETTINGS_FILE),
    }


def cmd_settings_set(args: argparse.Namespace) -> dict[str, Any]:
    prev = load_runtime()
    if args.file:
        patch = read_json_arg(args.file)
        if not isinstance(patch, dict):
            raise SystemExit("settings JSON 必须是对象")
        data = {**prev, **patch}
    else:
        data = dict(prev)
        for item in args.set or []:
            if "=" not in item:
                raise SystemExit(f"无效 --set {item}，应为 key=value")
            k, v = item.split("=", 1)
            k = k.strip()
            v = v.strip()
            if v.startswith("[") or v.startswith("{"):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    pass
            elif v.isdigit():
                v = int(v)
            data[k] = v
    save_runtime(data)
    return {"ok": True, "saved_keys": sorted(data.keys())}


def cmd_datasources(_: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import load_datasources
    from nl2sql_core.engines.registry import list_engines

    return {"datasources": load_datasources(), "engines": list_engines()}


async def cmd_datasources_test(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import load_datasources
    from nl2sql_core.engines.registry import get_engine

    if args.datasource_id == "mock":
        ok = await get_engine("mock").test_connection({})
        return {"ok": ok, "type": "mock"}
    ds = load_datasources().get(args.datasource_id)
    if not ds:
        raise SystemExit(f"未知数据源: {args.datasource_id}")
    cfg = merge_ds(ds)
    engine = get_engine(cfg.get("type", "mock"))
    try:
        ping = getattr(engine, "ping", None)
        if callable(ping):
            detail = await ping(cfg)
            if isinstance(detail, dict):
                return {"type": cfg.get("type"), **detail}
        ok = await engine.test_connection(cfg)
        return {"ok": ok, "type": cfg.get("type")}
    except Exception as e:
        return {"ok": False, "type": cfg.get("type"), "error": str(e)}


async def _prepare_query(
    *,
    query: str,
    execute_query: Any,
    use_llm: bool,
    skip_clarify: bool,
    interactive_clarify: bool,
    clarify_session_id: Optional[str],
    clarify_message: Optional[str],
) -> tuple[str, Any | None, bool]:
    from nl2sql_core.clarify.session import auto_resolve_query, reply_clarify, start_clarify

    if skip_clarify or execute_query is not None or not use_llm:
        return query, None, False
    llm = llm_client()
    if clarify_session_id and clarify_message is not None:
        session = await reply_clarify(clarify_session_id, clarify_message, llm)
        if not session.done:
            return query, session, True
        return session.resolved_query or query, session, False
    if interactive_clarify:
        session = await start_clarify(query, llm, max_rounds=3)
        if not session.done:
            return query, session, True
        return session.resolved_query or query, session, False
    session = await auto_resolve_query(query, llm)
    return session.resolved_query or query, session, False


async def cmd_ask(args: argparse.Namespace) -> dict[str, Any]:
    """问答：生成查询并执行（默认静默澄清，一次出结果）。"""
    from nl2sql_core.pipeline import NL2SQLPipeline

    execute_query = None
    if args.execute_query:
        raw = args.execute_query
        if raw.strip().startswith("{"):
            execute_query = json.loads(raw)
        else:
            execute_query = raw
    elif args.execute_file:
        execute_query = read_json_arg(args.execute_file)
        if isinstance(execute_query, dict) and "mode" not in execute_query and "sql" in execute_query:
            execute_query = execute_query.get("sql") or execute_query

    q, session, need = await _prepare_query(
        query=args.query,
        execute_query=execute_query,
        use_llm=not args.no_llm,
        skip_clarify=args.skip_clarify,
        interactive_clarify=args.interactive_clarify,
        clarify_session_id=args.clarify_session_id,
        clarify_message=args.clarify_message,
    )
    if need and session is not None:
        return {
            "need_clarify": True,
            "clarify_session": session.model_dump(),
            "query": args.query,
            "hint": "请用 clarify-reply --session-id ... --message ... 继续，或加 --skip-clarify / 去掉 --interactive-clarify",
        }

    pipe = NL2SQLPipeline()
    result = await pipe.run(
        q,
        datasource_id=args.datasource_id,
        execute_query=execute_query,
        mode=args.mode,
        use_llm=(not args.no_llm) and execute_query is None,
    )
    data = result.model_dump()
    data["resolved_query"] = q
    data["interactive_clarify"] = args.interactive_clarify
    if session is not None:
        data["clarify_session_id"] = session.id
    return data


async def cmd_clarify_start(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.clarify.session import start_clarify

    session = await start_clarify(args.query, llm_client(), max_rounds=args.max_rounds)
    return session.model_dump()


async def cmd_clarify_reply(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.clarify.session import reply_clarify

    session = await reply_clarify(args.session_id, args.message, llm_client())
    return session.model_dump()


async def cmd_schema(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import load_datasources
    from nl2sql_core.engines.registry import get_engine

    if args.datasource_id == "mock":
        summary = await get_engine("mock").fetch_schema({})
        return summary.model_dump()
    ds = load_datasources().get(args.datasource_id)
    if not ds:
        raise SystemExit(f"未知数据源: {args.datasource_id}")
    engine = get_engine(ds.get("type", "mock"))
    summary = await engine.fetch_schema(merge_ds(ds))
    return summary.model_dump()


def cmd_rules_list(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.store import RuleStore

    store = RuleStore(args.database_id)
    rules = store.list_rules(args.rule_type)
    return {"count": len(rules), "rules": rules[:500]}


def cmd_rules_upsert(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.schema import Rule
    from nl2sql_core.rules.store import RuleStore

    store = RuleStore(args.database_id)
    raw = read_json_arg(args.file)
    try:
        rule = Rule.model_validate(raw)
    except Exception:
        rule = raw
    saved = store.upsert(rule)
    return {"ok": True, "rule": saved}


async def cmd_rules_search(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.store import RuleStore

    store = RuleStore(args.database_id)
    rules = await store.search(args.query, rule_type=args.rule_type, top_k=args.top_k)
    return {"count": len(rules), "rules": rules}


def cmd_rules_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.bootstrap import bootstrap

    return bootstrap(args.database_id)


async def cmd_rules_init_preview(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.init import init_from_datasource, write_bundle

    bundle = await init_from_datasource(
        args.database_id,
        include_llm_domain=not args.no_llm_domain,
        llm=llm_client(),
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


async def cmd_rules_init_commit(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.rules.init import commit_bundle

    src: Any = None
    if args.from_file:
        src = args.from_file
    elif args.bundle:
        src = read_json_arg(args.bundle)
        if isinstance(src, dict) and args.database_id:
            src = dict(src)
            src.setdefault("database_id", args.database_id)
    else:
        raise SystemExit("需要 --from-file 或 --bundle")
    return await commit_bundle(
        src,
        recreate_kb=not args.no_recreate_kb,
        persist_kb=not args.no_persist_kb,
        kb_name=args.kb_name or None,
    )


async def cmd_rules_generate(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import load_datasources
    from nl2sql_core.engines.registry import get_engine
    from nl2sql_core.rules.nl_generate import generate_rules_from_nl
    from nl2sql_core.rules.store import normalize_dialect

    ds = load_datasources().get(args.database_id) or {"type": "elasticsearch"}
    dialect = normalize_dialect(str(ds.get("type") or "elasticsearch"))
    schema_hint = ""
    if not args.no_schema:
        try:
            engine = get_engine(ds.get("type", "elasticsearch"))
            summary = await engine.fetch_schema(merge_ds(ds))
            compact = []
            for idx in summary.indexes[:12]:
                fields = [f"{f.name}:{f.type}" for f in idx.fields[:30]]
                compact.append({"index": idx.name, "fields": fields})
            schema_hint = json.dumps(compact, ensure_ascii=False)
        except Exception as e:
            schema_hint = f"(schema 拉取失败: {e})"
    rules = await generate_rules_from_nl(
        args.text,
        database_id=args.database_id,
        dialect=dialect,
        schema_hint=schema_hint,
        llm=llm_client(),
    )
    return {
        "ok": True,
        "count": len(rules),
        "rules": rules,
        "schema_hint_used": bool(schema_hint),
    }


async def cmd_rules_import(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.config import load_rag_settings
    from nl2sql_core.rag_client import RagClient
    from nl2sql_core.rules.store import RuleStore

    raw = read_json_arg(args.file)
    if isinstance(raw, dict) and "rules" in raw:
        rules = raw["rules"]
    elif isinstance(raw, list):
        rules = raw
    else:
        raise SystemExit("规则文件应为数组或 {\"rules\": [...]}")
    if not rules:
        raise SystemExit("rules 为空")

    store = RuleStore(args.database_id)
    saved = []
    for r in rules:
        item = dict(r)
        item.setdefault("id", str(uuid.uuid4()))
        item.setdefault("database_id", args.database_id)
        saved.append(store.upsert(item))

    rag_result: dict[str, Any] = {"skipped": True}
    if not args.no_sync_rag:
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


async def cmd_consistency(args: argparse.Namespace) -> dict[str, Any]:
    from nl2sql_core.eval.consistency import run_consistency

    return await run_consistency(
        args.query,
        datasource_id=args.datasource_id,
        repeats=args.repeats,
        mode=args.mode,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nl2sql_skill_cli",
        description="NL2SQL OpenCode Skill 本地 CLI（无 Web 端口，复用 nl2sql_core）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("health", help="健康检查（rag + 可选数据源）")
    h.add_argument("--datasource-id", default="")
    h.set_defaults(func=cmd_health, is_async=True)

    sg = sub.add_parser("settings-get", help="读取运行时设置")
    sg.set_defaults(func=cmd_settings_get, is_async=False)

    ss = sub.add_parser("settings-set", help="写入 runtime_settings.json")
    ss.add_argument("--file", help="JSON 文件或 -（stdin）")
    ss.add_argument("--set", action="append", help="key=value，可重复")
    ss.set_defaults(func=cmd_settings_set, is_async=False)

    ds = sub.add_parser("datasources", help="列出数据源")
    ds.set_defaults(func=cmd_datasources, is_async=False)

    dt = sub.add_parser("datasources-test", help="测试单个数据源")
    dt.add_argument("--datasource-id", default="local-es")
    dt.set_defaults(func=cmd_datasources_test, is_async=True)

    ask = sub.add_parser("ask", help="自然语言问答：生成查询并执行")
    ask.add_argument("--query", "-q", required=True)
    ask.add_argument("--datasource-id", default="local-es")
    ask.add_argument("--mode", default="auto")
    ask.add_argument("--no-llm", action="store_true")
    ask.add_argument("--skip-clarify", action="store_true")
    ask.add_argument(
        "--interactive-clarify",
        action="store_true",
        help="多轮澄清；默认关闭（静默理解后直接生成+执行）",
    )
    ask.add_argument("--clarify-session-id", default=None)
    ask.add_argument("--clarify-message", default=None)
    ask.add_argument("--execute-query", default=None, help="直接执行 SQL/JSON，跳过 LLM 生成")
    ask.add_argument("--execute-file", default=None, help="从文件读 execute_query")
    ask.set_defaults(func=cmd_ask, is_async=True)

    cs = sub.add_parser("clarify-start", help="开始澄清会话")
    cs.add_argument("--query", "-q", required=True)
    cs.add_argument("--max-rounds", type=int, default=3)
    cs.set_defaults(func=cmd_clarify_start, is_async=True)

    cr = sub.add_parser("clarify-reply", help="澄清续答")
    cr.add_argument("--session-id", required=True)
    cr.add_argument("--message", "-m", required=True)
    cr.set_defaults(func=cmd_clarify_reply, is_async=True)

    sc = sub.add_parser("schema", help="拉取数据源 schema")
    sc.add_argument("--datasource-id", default="local-es")
    sc.set_defaults(func=cmd_schema, is_async=True)

    rl = sub.add_parser("rules-list", help="列出本地规则")
    rl.add_argument("--database-id", default="local-es")
    rl.add_argument("--rule-type", default=None)
    rl.set_defaults(func=cmd_rules_list, is_async=False)

    ru = sub.add_parser("rules-upsert", help="写入单条规则")
    ru.add_argument("--database-id", default="local-es")
    ru.add_argument("--file", required=True)
    ru.set_defaults(func=cmd_rules_upsert, is_async=False)

    rs = sub.add_parser("rules-search", help="检索规则")
    rs.add_argument("--database-id", default="local-es")
    rs.add_argument("--query", "-q", default="")
    rs.add_argument("--rule-type", default=None)
    rs.add_argument("--top-k", type=int, default=20)
    rs.set_defaults(func=cmd_rules_search, is_async=True)

    rb = sub.add_parser("rules-bootstrap", help="FIELD-GUIDE 初始化本地规则")
    rb.add_argument("--database-id", default="local-es")
    rb.set_defaults(func=cmd_rules_bootstrap, is_async=False)

    rip = sub.add_parser("rules-init-preview", help="从数据源生成规则包（不写 rag）")
    rip.add_argument("--database-id", default="local-es")
    rip.add_argument("--no-llm-domain", action="store_true")
    rip.set_defaults(func=cmd_rules_init_preview, is_async=True)

    ric = sub.add_parser("rules-init-commit", help="确认入库规则包到 rag")
    ric.add_argument("--from-file", default="")
    ric.add_argument("--bundle", default="")
    ric.add_argument("--database-id", default="")
    ric.add_argument("--kb-name", default="")
    ric.add_argument("--no-recreate-kb", action="store_true")
    ric.add_argument("--no-persist-kb", action="store_true")
    ric.set_defaults(func=cmd_rules_init_commit, is_async=True)

    rg = sub.add_parser("rules-generate", help="自然语言生成规则草稿")
    rg.add_argument("--database-id", default="local-es")
    rg.add_argument("--text", "-t", required=True)
    rg.add_argument("--no-schema", action="store_true")
    rg.set_defaults(func=cmd_rules_generate, is_async=True)

    ri = sub.add_parser("rules-import", help="导入规则到本地+RAG")
    ri.add_argument("--database-id", default="local-es")
    ri.add_argument("--file", required=True)
    ri.add_argument("--no-sync-rag", action="store_true")
    ri.set_defaults(func=cmd_rules_import, is_async=True)

    co = sub.add_parser("consistency", help="一致性测试")
    co.add_argument("--query", "-q", required=True)
    co.add_argument("--datasource-id", default="local-es")
    co.add_argument("--repeats", type=int, default=3)
    co.add_argument("--mode", default="auto")
    co.set_defaults(func=cmd_consistency, is_async=True)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if getattr(args, "is_async", False):
            out = asyncio.run(args.func(args))
        else:
            out = args.func(args)
        dump(out)
    except SystemExit:
        raise
    except Exception as e:
        dump({"ok": False, "error": str(e)})
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
