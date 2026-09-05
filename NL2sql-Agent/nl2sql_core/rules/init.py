"""从真实数据源拉取 schema + 抽样，生成规则包 JSON（默认不写 rag-core）。"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nl2sql_core.config import DATA_DIR, LLMSettings, ensure_data_dir, load_datasources
from nl2sql_core.engines.registry import get_engine
from nl2sql_core.llm.client import LLMClient
from nl2sql_core.models import SchemaSummary
from nl2sql_core.rules.bootstrap import load_rule_files
from nl2sql_core.rules.nl_generate import generate_domain_from_schema
from nl2sql_core.rules.schema import Dialect, Rule
from nl2sql_core.rules.store import RuleStore, normalize_dialect

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = DATA_DIR / "rules" / "init_bundles"

DEFAULT_LIMITS = {
    "max_objects": 80,
    "sample_rows": 5,
    "top_terms": 20,
    "sample_timeout_sec": 90,
    "schema_hint_max_chars": 24000,
    "max_examples": 12,
    "max_domain": 40,
    "keyword_fields_per_object": 8,
}

_SYSTEM_PREFIXES = (".",)
_SYSTEM_NAMES = {"kibana_sample_data_logs"}


def load_init_limits() -> dict[str, Any]:
    from nl2sql_core.config import _load_yaml

    raw = (_load_yaml("app.yaml") or {}).get("rules_init") or {}
    out = dict(DEFAULT_LIMITS)
    for k, v in raw.items():
        if k in out and v is not None:
            out[k] = type(out[k])(v)
    return out


def _runtime_settings() -> dict[str, Any]:
    path = DATA_DIR / "runtime_settings.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def datasource_config(database_id: str) -> dict[str, Any]:
    from nl2sql_core.config import merge_datasource_config

    ds = load_datasources().get(database_id)
    if not ds:
        if database_id == "mock":
            return {"id": "mock", "type": "mock"}
        raise KeyError(f"未知数据源: {database_id}")
    return merge_datasource_config(ds)


def llm_from_runtime() -> LLMClient:
    runtime = _runtime_settings()
    base = LLMSettings()
    return LLMClient(
        LLMSettings(
            base_url=runtime.get("llm_base_url") or base.base_url,
            api_key=runtime.get("llm_api_key") or base.api_key,
            model=runtime.get("llm_model") or base.model,
        )
    )


def is_system_object(name: str, engine_type: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if n.startswith(_SYSTEM_PREFIXES):
        return True
    if n in _SYSTEM_NAMES:
        return True
    eng = (engine_type or "").lower()
    if eng in ("opengauss", "postgres", "postgresql"):
        if n.startswith("pg_") or n in ("information_schema",):
            return True
    if eng == "hbase" and (n.startswith("hbase:") or n == "hbase"):
        return True
    return False


def _as_rule_dialect(engine_type: str) -> Dialect:
    d = normalize_dialect(engine_type)
    if d in ("elasticsearch", "opengauss", "hbase", "shared"):
        return d  # type: ignore[return-value]
    return "shared"


def _kind_label(engine_type: str) -> str:
    if (engine_type or "").lower() in ("elasticsearch", "es"):
        return "INDEX"
    return "TABLE"


def build_schema_rules_from_summary(
    database_id: str,
    engine_type: str,
    summary: SchemaSummary,
    samples: dict[str, Any],
) -> list[dict[str, Any]]:
    dial = _as_rule_dialect(engine_type)
    kind = _kind_label(engine_type)
    rules: list[dict[str, Any]] = []
    for idx in summary.indexes:
        sample = samples.get(idx.name) or {}
        terms: dict[str, list[str]] = sample.get("terms") or {}
        lines = [f"{kind} {idx.name}"]
        for f in idx.fields[:80]:
            extra = ""
            tv = terms.get(f.name) or []
            if tv:
                extra = f"；样例：{'/'.join(tv[:8])}"
            meaning = (f.description or "").strip() or "（从库结构读取，无业务注释）"
            lines.append(f"- {f.name} ({f.type}): {meaning}{extra}")
        rules.append(
            Rule(
                id=str(uuid.uuid4()),
                database_id=database_id,
                rule_type="ddl",
                scope="schema",
                dialect=dial,
                table=idx.name,
                ddl="\n".join(lines),
                description=f"{kind.lower()} {idx.name} 的字段结构摘要",
            ).to_content()
        )
        for f in idx.fields:
            tv = terms.get(f.name) or []
            sample_txt = f"；样例：{'/'.join(tv[:12])}" if tv else ""
            meaning = (f.description or "").strip() or "库内字段"
            rules.append(
                Rule(
                    id=str(uuid.uuid4()),
                    database_id=database_id,
                    rule_type="mapping",
                    scope="schema",
                    dialect=dial,
                    mapping_type="correspondence",
                    table=idx.name,
                    col=f.name,
                    description=f"{f.name} 表示「{meaning}」（类型 {f.type}）{sample_txt}",
                ).to_content()
            )
    return rules


def compact_schema_hint(
    summary: SchemaSummary,
    samples: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    def build(max_fields: int, max_terms: int, max_rows: int, max_indexes: int | None = None) -> str:
        indexes = list(summary.indexes)
        if max_indexes is not None:
            indexes = indexes[:max_indexes]
        compact: list[dict[str, Any]] = []
        for idx in indexes:
            sample = samples.get(idx.name) or {}
            terms = sample.get("terms") or {}
            fields = []
            for f in idx.fields[:max_fields]:
                item: dict[str, Any] = {"name": f.name, "type": f.type}
                if max_terms and terms.get(f.name):
                    item["samples"] = terms[f.name][:max_terms]
                fields.append(item)
            rec: dict[str, Any] = {"name": idx.name, "fields": fields}
            rows = (sample.get("rows") or [])[:max_rows]
            if rows:
                rec["row_samples"] = rows
            compact.append(rec)
        return json.dumps(compact, ensure_ascii=False)

    for max_fields, max_terms, max_rows, max_indexes in (
        (40, 10, 2, None),
        (20, 6, 1, None),
        (12, 4, 0, None),
        (8, 3, 0, 40),
        (6, 2, 0, 20),
        (4, 0, 0, 15),
    ):
        text = build(max_fields, max_terms, max_rows, max_indexes)
        if len(text) <= max_chars:
            return text
    names = [{"name": i.name, "fields": [f.name for f in i.fields[:6]]} for i in summary.indexes[:12]]
    return json.dumps(names, ensure_ascii=False)


def write_bundle(bundle: dict[str, Any], path: str | Path | None = None) -> Path:
    ensure_data_dir()
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        db = str(bundle.get("database_id") or "ds")
        path = BUNDLE_DIR / f"init_{db}_{ts}.json"
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def load_bundle(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"rules": raw, "database_id": "", "engine": ""}
    if not isinstance(raw, dict):
        raise ValueError("规则包须为 JSON 对象或规则数组")
    return raw


async def init_from_datasource(
    database_id: str,
    *,
    include_llm_domain: bool = True,
    limits: dict[str, Any] | None = None,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    lim = {**DEFAULT_LIMITS, **(limits or load_init_limits())}
    cfg = datasource_config(database_id)
    engine_type = str(cfg.get("type") or "elasticsearch")
    engine = get_engine(engine_type)
    warnings: list[str] = []

    summary = await engine.fetch_schema(cfg)
    kept = []
    skipped_system = 0
    for idx in summary.indexes:
        if is_system_object(idx.name, engine_type):
            skipped_system += 1
            continue
        kept.append(idx)
    if skipped_system:
        warnings.append(f"skipped_system_objects={skipped_system}")
    max_obj = int(lim["max_objects"])
    if len(kept) > max_obj:
        warnings.append(f"truncated_to_{max_obj}_objects (had {len(kept)})")
        kept = kept[:max_obj]
    summary = SchemaSummary(indexes=kept, notes=list(summary.notes or []))

    cfg = dict(cfg)
    cfg["keyword_fields_per_object"] = int(lim["keyword_fields_per_object"])
    deadline = time.monotonic() + float(lim["sample_timeout_sec"])
    samples: dict[str, Any] = {}
    sample_fn = getattr(engine, "sample_values", None)
    if callable(sample_fn) and kept:
        try:
            samples = await sample_fn(
                cfg,
                names=[i.name for i in kept],
                sample_rows=int(lim["sample_rows"]),
                top_terms=int(lim["top_terms"]),
                deadline_monotonic=deadline,
            )
            if time.monotonic() >= deadline:
                warnings.append("sample_timeout_partial")
        except Exception as e:
            warnings.append(f"sample_failed: {e}")
            samples = {}

    schema_rules = build_schema_rules_from_summary(database_id, engine_type, summary, samples)
    dialect_out: list[dict[str, Any]] = []
    for r in load_rule_files(database_id, engine_type):
        dialect_out.append(r.to_content() if hasattr(r, "to_content") else dict(r))

    domain_rules: list[dict[str, Any]] = []
    hint_text = compact_schema_hint(
        summary, samples, max_chars=int(lim["schema_hint_max_chars"])
    )
    if include_llm_domain:
        client = llm or llm_from_runtime()
        if not (client.settings.api_key or "").strip():
            warnings.append("llm_skipped_no_api_key")
        else:
            try:
                domain_rules = await generate_domain_from_schema(
                    database_id=database_id,
                    dialect=engine_type,
                    schema_hint=hint_text,
                    llm=client,
                    max_domain=int(lim["max_domain"]),
                    max_examples=int(lim["max_examples"]),
                )
            except Exception as e:
                warnings.append(f"llm_domain_failed: {e}")

    rules = schema_rules + dialect_out + domain_rules
    hint_obj: Any
    try:
        hint_obj = json.loads(hint_text)
    except json.JSONDecodeError:
        hint_obj = {"raw": hint_text[:2000], "truncated": True}
    return {
        "ok": True,
        "database_id": database_id,
        "engine": engine_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "counts": {
            "objects": len(kept),
            "schema": len(schema_rules),
            "dialect_domain_files": len(dialect_out),
            "llm_domain": len(domain_rules),
            "total": len(rules),
        },
        "schema_hint": hint_obj,
        "rules": rules,
    }


async def commit_bundle(
    bundle: dict[str, Any] | str | Path,
    *,
    recreate_kb: bool = True,
    persist_kb: bool = True,
    kb_name: str | None = None,
    concurrency: int = 8,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        bundle = load_bundle(bundle)
    database_id = str(bundle.get("database_id") or "").strip()
    if not database_id:
        raise ValueError("规则包缺少 database_id")
    rules = bundle.get("rules") or []
    if not rules:
        raise ValueError("规则包 rules 为空")
    store = RuleStore(database_id)
    store._save([dict(r) for r in rules])
    result = await store.sync_to_rag(
        kb_name=kb_name,
        concurrency=concurrency,
        persist_kb=persist_kb,
        recreate_kb=recreate_kb,
    )
    result["database_id"] = database_id
    result["committed"] = len(rules)
    return result
