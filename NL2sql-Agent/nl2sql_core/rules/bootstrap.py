from __future__ import annotations

import gzip
import json
import uuid
from pathlib import Path
from typing import Any

from nl2sql_core.rules.schema import Dialect, Rule, RuleScope
from nl2sql_core.rules.store import RuleStore


ROOT = Path(__file__).resolve().parents[2]
FIELD_GUIDE = ROOT / "fixtures" / "field_guide" / "FIELD-GUIDE.md"
DUMP_DIR = ROOT / "fixtures" / "es_dump"
RULES_FIXTURES = ROOT / "fixtures" / "rules"


def parse_field_guide(text: str) -> dict[str, list[dict[str, str]]]:
    """解析 FIELD-GUIDE.md -> {index: [{name, type, meaning}]}"""
    result: dict[str, list[dict[str, str]]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("###"):
            current = line[3:].strip()
            result.setdefault(current, [])
            continue
        if current and line.startswith("|") and "字段名" not in line and "---" not in line:
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 3:
                result[current].append(
                    {"name": parts[0], "type": parts[1], "meaning": parts[2]}
                )
    return result


def load_mapping_props(index: str) -> dict[str, Any]:
    for cand in [
        DUMP_DIR / f"{index}.mapping.json.gz",
        DUMP_DIR / f"{index}.mapping.json",
    ]:
        if not cand.exists():
            continue
        if str(cand).endswith(".gz"):
            with gzip.open(cand, "rt", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = json.loads(cand.read_text(encoding="utf-8"))
        body = raw.get(index) or next(iter(raw.values()))
        return body.get("mappings", {}).get("properties") or {}
    return {}


def _engine_for_database(database_id: str) -> str:
    from nl2sql_core.config import load_datasources

    ds = load_datasources().get(database_id) or {}
    return str(ds.get("type") or "elasticsearch").lower().strip()


def _as_dialect(value: str | None, fallback: str) -> Dialect:
    v = (value or fallback or "shared").lower().strip()
    if v in ("elasticsearch", "es"):
        return "elasticsearch"
    if v in ("opengauss", "postgres", "postgresql"):
        return "opengauss"
    if v == "hbase":
        return "hbase"
    if v == "shared":
        return "shared"
    # 未知引擎：按 shared，避免误打成 ES
    return "shared"


def _as_scope(value: str | None, fallback: RuleScope) -> RuleScope:
    v = (value or fallback).lower().strip()
    if v in ("schema", "dialect", "domain"):
        return v  # type: ignore[return-value]
    return fallback


def load_json_rules(
    path: Path,
    *,
    database_id: str,
    default_dialect: Dialect,
    default_scope: RuleScope,
) -> list[Rule]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"规则文件须为 JSON 数组: {path}")
    out: list[Rule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data["id"] = str(data.get("id") or uuid.uuid4())
        data["database_id"] = database_id
        data["dialect"] = _as_dialect(data.get("dialect"), default_dialect)
        data["scope"] = _as_scope(data.get("scope"), default_scope)
        data.setdefault("rule_type", "experience")
        data.setdefault("description", "")
        out.append(Rule.model_validate(data))
    return out


def load_rule_files(database_id: str, dialect: str | None = None) -> list[Rule]:
    """加载方言经验 + 该数据源 domain 经验（均进 rag-core，不进 system prompt）。"""
    eng = (dialect or _engine_for_database(database_id)).lower().strip()
    dial = _as_dialect(eng, "shared")
    rules: list[Rule] = []

    dialect_name = {
        "elasticsearch": "elasticsearch",
        "es": "elasticsearch",
        "opengauss": "opengauss",
        "postgres": "opengauss",
        "postgresql": "opengauss",
        "hbase": "hbase",
    }.get(eng, eng if eng in ("elasticsearch", "opengauss", "hbase") else "")
    if dialect_name:
        dialect_file = RULES_FIXTURES / "dialects" / f"{dialect_name}.json"
        default_dial: Dialect = {
            "elasticsearch": "elasticsearch",
            "opengauss": "opengauss",
            "hbase": "hbase",
        }.get(dialect_name) or "shared"
        rules.extend(
            load_json_rules(
                dialect_file,
                database_id=database_id,
                default_dialect=default_dial,
                default_scope="dialect",
            )
        )

    domain_dir = RULES_FIXTURES / "datasources" / database_id
    if domain_dir.is_dir():
        for path in sorted(domain_dir.glob("*.json")):
            rules.extend(
                load_json_rules(
                    path,
                    database_id=database_id,
                    default_dialect=dial if dial != "shared" else "shared",
                    default_scope="domain",
                )
            )
    return rules


def build_schema_rules(database_id: str, dialect: str | None = None) -> list[Rule]:
    """仅从 FIELD-GUIDE / mapping 生成 ddl + mapping。"""
    eng = (dialect or _engine_for_database(database_id)).lower().strip()
    dial = _as_dialect(eng, "elasticsearch")
    if dial == "shared":
        dial = "elasticsearch"

    guide: dict[str, list[dict[str, str]]] = {}
    if FIELD_GUIDE.exists():
        guide = parse_field_guide(FIELD_GUIDE.read_text(encoding="utf-8"))

    indexes = sorted(guide.keys()) or [
        p.name.split(".")[0] for p in DUMP_DIR.glob("*.mapping.json*")
    ]

    rules: list[Rule] = []
    for index in indexes:
        fields = guide.get(index) or []
        props = load_mapping_props(index)
        lines = [f"INDEX {index}"]
        for f in fields[:80]:
            lines.append(f"- {f['name']} ({f['type']}): {f['meaning']}")
        if not fields and props:
            for name, node in list(props.items())[:80]:
                t = node.get("type", "object") if isinstance(node, dict) else "object"
                lines.append(f"- {name} ({t})")
        rules.append(
            Rule(
                id=str(uuid.uuid4()),
                database_id=database_id,
                rule_type="ddl",
                scope="schema",
                dialect=dial,
                table=index,
                ddl="\n".join(lines),
                description=f"索引 {index} 的字段结构摘要",
            )
        )
        for f in fields:
            rules.append(
                Rule(
                    id=str(uuid.uuid4()),
                    database_id=database_id,
                    rule_type="mapping",
                    scope="schema",
                    dialect=dial,
                    mapping_type="correspondence",
                    table=index,
                    col=f["name"],
                    description=f"{f['name']} 表示「{f['meaning']}」（类型 {f['type']}）",
                )
            )
    return rules


def build_rules(database_id: str = "local-es", dialect: str | None = None) -> list[Rule]:
    """schema（自动）+ dialect/domain（fixtures JSON）→ 本地缓存，再 sync 到 rag-core。"""
    eng = dialect or _engine_for_database(database_id)
    rules = build_schema_rules(database_id, eng)
    rules.extend(load_rule_files(database_id, eng))
    return rules


def bootstrap(database_id: str = "local-es") -> dict[str, Any]:
    store = RuleStore(database_id)
    rules = build_rules(database_id)
    store._save([r.to_content() for r in rules])
    return {
        "ok": True,
        "count": len(rules),
        "path": str(store.path),
        "dialect": _engine_for_database(database_id),
        "by_scope": {
            "schema": sum(1 for r in rules if r.scope == "schema"),
            "dialect": sum(1 for r in rules if r.scope == "dialect"),
            "domain": sum(1 for r in rules if r.scope == "domain"),
        },
    }


if __name__ == "__main__":
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
