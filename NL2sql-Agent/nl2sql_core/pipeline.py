from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

from nl2sql_core.config import LLMSettings, load_app_settings, load_datasources
from nl2sql_core.engines.registry import get_engine
from nl2sql_core.generate.query_generator import generate_query
from nl2sql_core.generate.retry_feedback import build_retry_feedback, should_retry
from nl2sql_core.kg import verify as kg_verify
from nl2sql_core.llm.client import LLMClient
from nl2sql_core.models import PipelineResult, PipelineStep, QueryResult
from nl2sql_core.rules.store import RuleStore, normalize_dialect
from nl2sql_core.safety import assert_readonly_sql


def _rule_type_histogram(rules: list[dict[str, Any]]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for r in rules:
        t = str(r.get("rule_type") or "unknown")
        hist[t] = hist.get(t, 0) + 1
    return hist


def _scope_histogram(rules: list[dict[str, Any]]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for r in rules:
        t = str(r.get("scope") or "unknown")
        hist[t] = hist.get(t, 0) + 1
    return hist


def normalize_dialect_label(engine_type: str) -> str:
    return normalize_dialect(engine_type)


def _runtime_settings() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "data" / "runtime_settings.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _merge_es_config(cfg: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_settings()
    out = dict(cfg)
    if out.get("type") != "elasticsearch":
        return out
    if runtime.get("es_hosts"):
        out["hosts"] = runtime["es_hosts"]
    if "es_username" in runtime:
        out["username"] = runtime.get("es_username") or ""
        out["password"] = runtime.get("es_password") or ""
    if runtime.get("es_default_index"):
        out["default_index"] = runtime["es_default_index"]
    return out


def _llm_from_runtime() -> LLMClient:
    runtime = _runtime_settings()
    base = LLMSettings()
    return LLMClient(
        LLMSettings(
            base_url=runtime.get("llm_base_url") or base.base_url,
            api_key=runtime.get("llm_api_key") or base.api_key,
            model=runtime.get("llm_model") or base.model,
        )
    )


class NL2SQLPipeline:
    def __init__(self):
        self.app = load_app_settings()

    async def run(
        self,
        natural_query: str,
        *,
        datasource_id: str = "local-es",
        execute_query: str | dict[str, Any] | None = None,
        mode: str = "auto",
        use_llm: bool = True,
        on_event: EventCallback | None = None,
    ) -> PipelineResult:
        async def emit(event: str, **payload: Any) -> None:
            if on_event:
                maybe = on_event(event, payload)
                if maybe is not None and hasattr(maybe, "__await__"):
                    await maybe

        steps: list[PipelineStep] = []
        ds_map = load_datasources()
        config = _merge_es_config(dict(ds_map.get(datasource_id) or {}))
        if not config:
            # 允许 mock
            if datasource_id == "mock":
                config = {"type": "mock", "max_size": 100}
            else:
                err = f"未知数据源: {datasource_id}"
                await emit("error", message=err)
                return PipelineResult(query=natural_query, error=err, steps=steps)

        engine_type = config.get("type", "elasticsearch")
        engine = get_engine(engine_type)
        steps.append(PipelineStep(name="resolve_engine", status="done", message=f"engine={engine_type}"))
        await emit("step", step=steps[-1].model_dump())

        store = RuleStore(datasource_id if datasource_id != "mock" else "local-es")
        dialect = engine_type if engine_type not in ("mock",) else "elasticsearch"
        steps.append(PipelineStep(name="retrieve_rules", status="running", message="rag-core 召回规则"))
        await emit("step", step=steps[-1].model_dump())
        try:
            kb_id = str(config.get("rules_kb_id") or "").strip() or None
            rules_top_k = int(getattr(self.app, "rules_top_k", 50) or 50)
            rules = await store.search(
                natural_query,
                dialect=dialect,
                kb_id=kb_id,
                top_k=rules_top_k,
            )
            steps[-1].status = "done"
            steps[-1].message = f"rag-core 召回 {len(rules)} 条 · dialect={normalize_dialect_label(dialect)}"
            steps[-1].detail = {
                "count": len(rules),
                "source": "rag-core",
                "dialect": dialect,
                "kb_id": kb_id or store.resolve_kb_id(),
                "top_k": rules_top_k,
                "types": _rule_type_histogram(rules),
                "scopes": _scope_histogram(rules),
                "rules_preview": [
                    {
                        "id": r.get("id"),
                        "rule_type": r.get("rule_type"),
                        "scope": r.get("scope"),
                        "dialect": r.get("dialect"),
                        "table": r.get("table"),
                        "description": (r.get("description") or "")[:160],
                        "query": r.get("query"),
                        "sql": (r.get("sql") or "")[:240] if isinstance(r.get("sql"), str) else r.get("sql"),
                    }
                    for r in rules[:rules_top_k]
                ],
            }
            await emit("step", step=steps[-1].model_dump())
            await emit("rules", count=len(rules), types=steps[-1].detail["types"])
        except Exception as e:
            steps[-1].status = "error"
            steps[-1].message = str(e)
            await emit("step", step=steps[-1].model_dump())
            await emit("error", message=str(e))
            return PipelineResult(query=natural_query, steps=steps, error=str(e))

        generated: str | dict[str, Any] | None = execute_query
        gen_mode = mode
        result: QueryResult | None = None
        last_exec_error: str | None = None

        if generated is None and use_llm:
            llm = _llm_from_runtime()
            if not (llm.settings.api_key or "").strip():
                steps.append(PipelineStep(name="generate", status="error", message="未配置 LLM API Key（请到设置页填写）"))
                await emit("step", step=steps[-1].model_dump())
                await emit("error", message=steps[-1].message)
                return PipelineResult(
                    query=natural_query,
                    rules=rules,
                    steps=steps,
                    error=steps[-1].message,
                )
            schema_hint = ""
            try:
                summary = await engine.fetch_schema(config)
                compact = []
                for idx in summary.indexes:
                    fields = [f"{f.name}:{f.type}" for f in idx.fields[:40]]
                    compact.append({"index": idx.name, "fields": fields})
                schema_hint = json.dumps(compact, ensure_ascii=False)[:6000]
            except Exception:
                schema_hint = ""

            max_attempts = max(1, int(self.app.max_query_attempts))
            retry_feedback = ""
            attempt_records: list[dict[str, Any]] = []

            for attempt in range(1, max_attempts + 1):
                gen_name = "generate" if attempt == 1 else f"generate_retry_{attempt}"
                steps.append(PipelineStep(name=gen_name, status="running", message=f"LLM 生成中（第 {attempt}/{max_attempts} 次）"))
                await emit("step", step=steps[-1].model_dump())
                try:
                    gen = await generate_query(
                        natural_query,
                        rules,
                        schema_hint=schema_hint,
                        dialect=dialect,
                        llm=llm,
                        retry_feedback=retry_feedback,
                    )
                    generated = gen["query"]
                    if mode == "auto":
                        gen_mode = gen.get("mode") or "auto"
                    if gen.get("index") and isinstance(generated, dict):
                        generated.setdefault("index", gen["index"])
                    if gen.get("index"):
                        config = dict(config)
                        config["target_index"] = gen["index"]
                    steps[-1].status = "done"
                    steps[-1].message = gen.get("reason") or f"mode={gen_mode}"
                    steps[-1].detail = {
                        "attempt": attempt,
                        "mode": gen.get("mode"),
                        "index": gen.get("index"),
                        "reason": gen.get("reason"),
                        "retry_feedback_used": bool(retry_feedback),
                    }
                    await emit("step", step=steps[-1].model_dump())
                    await emit("sql", query=generated, mode=gen_mode, index=gen.get("index"))
                except Exception as e:
                    steps[-1].status = "error"
                    steps[-1].message = str(e)
                    await emit("step", step=steps[-1].model_dump())
                    await emit("error", message=str(e))
                    return PipelineResult(query=natural_query, rules=rules, steps=steps, error=str(e))

                steps.append(PipelineStep(name="safety", status="running", message=f"只读检查（第 {attempt} 次）"))
                await emit("step", step=steps[-1].model_dump())
                try:
                    if isinstance(generated, str) and gen_mode in ("auto", "sql"):
                        if not generated.strip().startswith("{"):
                            assert_readonly_sql(generated)
                    steps[-1].status = "done"
                    steps[-1].message = "只读检查通过"
                    await emit("step", step=steps[-1].model_dump())
                except Exception as e:
                    steps[-1].status = "error"
                    steps[-1].message = str(e)
                    last_exec_error = str(e)
                    attempt_records.append({"attempt": attempt, "phase": "safety", "error": str(e)})
                    await emit("step", step=steps[-1].model_dump())
                    if attempt < max_attempts:
                        retry_feedback = build_retry_feedback(
                            natural_query=natural_query,
                            generated=generated or "",
                            error=str(e),
                            attempt=attempt,
                        )
                        await emit("retry", feedback=retry_feedback[:500], attempt=attempt)
                        continue
                    await emit("error", message=str(e))
                    return PipelineResult(
                        query=natural_query,
                        generated_query=generated,
                        rules=rules,
                        steps=steps,
                        error=str(e),
                    )

                exec_name = "execute" if attempt == 1 else f"execute_retry_{attempt}"
                steps.append(PipelineStep(name=exec_name, status="running", message="执行中"))
                await emit("step", step=steps[-1].model_dump())
                last_exec_error = None
                try:
                    exec_mode = gen_mode
                    if isinstance(generated, dict):
                        exec_mode = "dsl"
                    elif isinstance(generated, str) and generated.strip().startswith("{"):
                        exec_mode = "dsl"
                    result = await engine.execute(generated, config, mode=exec_mode)
                    steps[-1].status = "done"
                    steps[-1].message = f"返回 {result.row_count} 行，mode={result.mode}"
                    steps[-1].detail = {"attempt": attempt, "row_count": result.row_count}
                    await emit("step", step=steps[-1].model_dump())
                except Exception as e:
                    last_exec_error = str(e)
                    steps[-1].status = "error"
                    steps[-1].message = str(e)
                    result = None
                    attempt_records.append({"attempt": attempt, "phase": "execute", "error": str(e)})
                    await emit("step", step=steps[-1].model_dump())

                if should_retry(
                    error=last_exec_error,
                    result=result,
                    retry_on_empty=self.app.retry_on_empty,
                    attempt=attempt,
                    max_attempts=max_attempts,
                ):
                    retry_feedback = build_retry_feedback(
                        natural_query=natural_query,
                        generated=generated or "",
                        error=last_exec_error,
                        result=result,
                        attempt=attempt,
                    )
                    steps.append(
                        PipelineStep(
                            name=f"retry_plan_{attempt + 1}",
                            status="done",
                            message="将根据执行反馈重新生成查询",
                            detail={"feedback": retry_feedback[:800], "attempts": attempt_records},
                        )
                    )
                    await emit("step", step=steps[-1].model_dump())
                    await emit("retry", feedback=retry_feedback[:500], attempt=attempt)
                    continue
                break

            if last_exec_error and result is None:
                await emit("error", message=last_exec_error)
                return PipelineResult(
                    query=natural_query,
                    generated_query=generated,
                    mode=gen_mode,
                    rules=rules,
                    steps=steps,
                    error=last_exec_error,
                )
        elif generated is None:
            err = "无查询可执行：请开启 LLM 或传入 execute_query"
            await emit("error", message=err)
            return PipelineResult(
                query=natural_query,
                rules=rules,
                steps=steps,
                error=err,
            )
        else:
            steps.append(PipelineStep(name="generate", status="done", message="使用外部提供的查询"))
            await emit("step", step=steps[-1].model_dump())
            await emit("sql", query=generated, mode=gen_mode)
            steps.append(PipelineStep(name="safety", status="running"))
            await emit("step", step=steps[-1].model_dump())
            try:
                if isinstance(generated, str) and gen_mode in ("auto", "sql"):
                    if not generated.strip().startswith("{"):
                        assert_readonly_sql(generated)
                steps[-1].status = "done"
                steps[-1].message = "只读检查通过"
                await emit("step", step=steps[-1].model_dump())
            except Exception as e:
                steps[-1].status = "error"
                steps[-1].message = str(e)
                await emit("step", step=steps[-1].model_dump())
                await emit("error", message=str(e))
                return PipelineResult(
                    query=natural_query,
                    generated_query=generated,
                    rules=rules,
                    steps=steps,
                    error=str(e),
                )
            steps.append(PipelineStep(name="execute", status="running"))
            await emit("step", step=steps[-1].model_dump())
            try:
                exec_mode = gen_mode
                if isinstance(generated, dict):
                    exec_mode = "dsl"
                elif isinstance(generated, str) and generated.strip().startswith("{"):
                    exec_mode = "dsl"
                result = await engine.execute(generated, config, mode=exec_mode)
                steps[-1].status = "done"
                steps[-1].message = f"返回 {result.row_count} 行，mode={result.mode}"
                await emit("step", step=steps[-1].model_dump())
            except Exception as e:
                steps[-1].status = "error"
                steps[-1].message = str(e)
                await emit("step", step=steps[-1].model_dump())
                await emit("error", message=str(e))
                return PipelineResult(
                    query=natural_query,
                    generated_query=generated,
                    mode=gen_mode,
                    rules=rules,
                    steps=steps,
                    error=str(e),
                )

        assert result is not None
        kg_status = kg_verify(result, rules)
        steps.append(
            PipelineStep(
                name="kg_verify",
                status="skipped",
                message=kg_status.get("message", ""),
                detail=kg_status,
            )
        )
        await emit("step", step=steps[-1].model_dump())
        out = PipelineResult(
            query=natural_query,
            generated_query=generated,
            mode=result.mode,
            result=result,
            rules=rules,
            steps=steps,
        )
        await emit(
            "result",
            generated_query=generated,
            mode=result.mode,
            result=result.model_dump(),
            error=None,
        )
        await emit("done", ok=True)
        return out
