"""从自然语言生成 F1 规则候选（domain/dialect/别名），不含海量字段 mapping。"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from nl2sql_core.llm.client import LLMClient
from nl2sql_core.rules.store import normalize_dialect

SYSTEM = """你是 NL2SQL 规则编写助手。根据用户业务描述与可选 Schema 摘要，生成 JSON 规则数组。

只生成以下类型（F1，不要为每个字段生成 mapping）：
- rule_type=experience, scope=dialect：引擎方言硬约束
- rule_type=experience, scope=domain：索引职责、业务约定、跨表关联
- rule_type=mapping, scope=domain, mapping_type=station_alias|tag_alias：城市/标签别名

每条必须含：rule_type, scope, dialect, description；可选 table, mapping_type, col。
dialect 必须是给定引擎名或 shared。
禁止编造 Schema 中不存在的索引/表名。
禁止输出问句→SQL 的 example 板子。
只输出 JSON 数组，不要 Markdown。
"""


async def generate_rules_from_nl(
    user_text: str,
    *,
    database_id: str,
    dialect: str,
    schema_hint: str = "",
    llm: LLMClient | None = None,
) -> list[dict[str, Any]]:
    dial = normalize_dialect(dialect) or "elasticsearch"
    client = llm or LLMClient()
    user = (
        f"database_id={database_id}\n"
        f"dialect={dial}\n\n"
        f"用户业务描述：\n{user_text}\n\n"
        f"Schema摘要（可选参考）：\n{schema_hint[:8000] or '(无)'}\n"
    )
    raw = await client.chat(SYSTEM, user)
    rules = _parse_list(raw)
    out: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        r = dict(item)
        r.setdefault("id", str(uuid.uuid4()))
        r["database_id"] = database_id
        r["dialect"] = normalize_dialect(str(r.get("dialect") or dial)) or dial
        r.setdefault("scope", "domain")
        r.setdefault("rule_type", "experience")
        r.setdefault("description", "")
        out.append(r)
    return out


def _parse_list(text: str) -> list[Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            return data["rules"]
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if m:
            return json.loads(m.group(0))
    return []
