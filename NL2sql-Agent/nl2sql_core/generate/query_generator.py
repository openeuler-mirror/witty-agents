from __future__ import annotations

import json
import re
from typing import Any

from nl2sql_core.llm.client import LLMClient


# 引擎无关的输出格式约束；方言/业务一律来自 rag-core 召回（含固定注入的 scope=dialect）。
SYSTEM = """你是 NL2SQL 助手。

根据「用户问题 + 召回规则 + Schema提示 + 目标方言」生成可执行查询。
- 召回规则是权威来源：字段含义、索引/表选择、方言语法（DISTINCT/EXISTS/JOIN 等）只能使用规则中的信息。
- 禁止编造规则未出现的字段/索引/语法；禁止忽略 scope=dialect 的方言硬约束。
- 不要依赖「某句自然语言对应某条固定 SQL」的记忆；按规则与 Schema 推理。

输出必须是严格 JSON，不要 Markdown：
{
  "mode": "sql" 或 "dsl",
  "index": "目标索引或表名（dsl 必填；sql 应与 FROM 一致）",
  "query": "SQL字符串 或 DSL对象",
  "reason": "简短说明（引用用到的规则要点，尤其是 dialect）"
}

通用约束：
- 只读；SQL 只能是 SELECT。
- size/LIMIT 遵循召回规则；未说明时默认不超过 50。
- 若召回规则含 keyword/精确匹配提示，优先 term / 等值条件。
- **默认返回全部字段**：单表查询优先 `SELECT *`（或等价全字段）；DSL 不要随意收窄 `_source`（省略 `_source` 即返回全部）。仅当用户明确只要某几列时才投影。
- 列名必须以 Schema/召回规则为准，禁止用其他表的字段名冒充（否则会出现整列为空）。
"""


def build_user_prompt(
    natural_query: str,
    rules: list[dict[str, Any]],
    schema_hint: str = "",
    *,
    dialect: str = "",
) -> str:
    rule_text = json.dumps(rules, ensure_ascii=False, indent=2)
    dial = dialect or "unknown"
    return (
        f"目标方言/引擎：{dial}\n"
        f"用户问题：{natural_query}\n\n"
        f"Schema提示（仅辅助校验字段是否存在）：\n{schema_hint}\n\n"
        f"召回规则（权威，来自 rag-core；含当前引擎 dialect 经验）：\n{rule_text}\n"
    )


async def generate_query(
    natural_query: str,
    rules: list[dict[str, Any]],
    *,
    schema_hint: str = "",
    dialect: str = "",
    llm: LLMClient | None = None,
    retry_feedback: str = "",
) -> dict[str, Any]:
    if not rules:
        raise ValueError("未召回到任何规则：请检查 rag-core 是否可用且已同步规则")
    client = llm or LLMClient()
    user = build_user_prompt(natural_query, rules, schema_hint, dialect=dialect)
    if retry_feedback.strip():
        user = (
            user
            + "\n\n【上次执行反馈 — 必须据此修正，不要重复同样错误】\n"
            + retry_feedback.strip()
            + "\n"
        )
    raw = await client.chat(SYSTEM, user)
    data = _parse_json(raw)
    mode = (data.get("mode") or "dsl").lower()
    query = data.get("query")
    index = data.get("index") or data.get("table") or ""
    if mode == "sql" and not isinstance(query, str):
        query = str(query)
    if mode == "dsl":
        if isinstance(query, str):
            try:
                query = json.loads(query)
            except json.JSONDecodeError:
                pass
        if isinstance(query, dict) and index:
            query = {**query, "index": index}
    return {
        "mode": mode,
        "query": query,
        "index": index,
        "reason": data.get("reason", ""),
        "raw": raw,
    }


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise
