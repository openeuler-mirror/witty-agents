from __future__ import annotations

import json
import re
from typing import Any

from nl2sql_core.ir.schema import parse_ir
from nl2sql_core.llm.client import LLMClient
from nl2sql_core.rules.store import normalize_dialect


# 引擎无关的输出格式约束；方言/业务一律来自 rag-core 召回（含固定注入的 scope=dialect）。
SYSTEM_BASE = """你是 NL2SQL 助手。

根据「用户问题 + 召回规则 + Schema提示 + 目标方言」生成可执行查询计划。
- 召回规则是权威来源：字段含义、索引/表选择、方言语法只能使用规则中的信息。
- 禁止编造规则未出现的字段/索引；禁止忽略 scope=dialect 的方言硬约束。
- 不要依赖「某句自然语言对应某条固定 SQL」的记忆；按规则与 Schema 推理。

通用约束：
- 只读查询。
- LIMIT 遵循召回规则；未说明时默认不超过 50。
- 列名必须以 Schema/召回规则为准。
- 默认返回全部字段（select 用 ["*"]），仅当用户明确只要某几列时才投影。
"""

SYSTEM_IR = """
【本引擎请输出查询计划 IR（不要直接输出多表 SQL）】
输出必须是严格 JSON，不要 Markdown：
{
  "mode": "ir",
  "from": "主索引名",
  "select": ["*"],
  "where": [ {"field":"列名","op":"=|!=|>|>=|<|<=|like|in|between","value": ...} ],
  "semi_joins": [
    {
      "index": "从表索引",
      "local_key": "主表关联字段",
      "foreign_key": "从表关联字段",
      "where": [ {"field":"...","op":"=","value":"..."} ],
      "where_op": "and",
      "limit": 10000
    }
  ],
  "limit": 50,
  "reason": "简短说明（引用规则要点）"
}

IR 语义：
- from = 结果主表（通常是人员主档）。
- where = 只作用于主表的条件（如年龄 csrq、性别 xb）。
- semi_joins = 半连接：主表.local_key 必须出现在「从表 where 过滤后的 foreign_key 集合」中；
  **多个 semi_joins 之间是 AND（交集）**。
- 同一 semi_join 内多个 where：默认 and；若为「或」关系（如车次 G% 或 D% 或 K%）必须放在 **同一个** semi_join，并设 "where_op":"or"。
- **严禁**把本应 OR 的条件拆成多个 semi_joins（那会变成错误的 AND 交集，结果常为空）。
- between 的 value 必须是二元数组，如 ["1976-07-20","1996-07-20"]。
- in 的 value 必须是数组。
- 跨索引关联一律用 semi_joins，禁止写 JOIN / EXISTS / IN (SELECT ...)。
- 本库无酒店/航班等表时：忽略该条件，但保留其它有效条件。
- 购票表 ticket_sales 本身就是火车售票：问「坐火车」时可只约束站点，不必再拆多个车次前缀；
  若要约束车次，用同一个 semi_join + where_op=or + 多条 like 'G%'/'D%'/'C%'/'Z%'/'T%'/'K%'。
- 问「坐飞机/大巴」：忽略交通方式，只保留城市等有效条件。
"""

SYSTEM_SQL = """
【本引擎请直接输出 SQL 或 DSL】
输出必须是严格 JSON，不要 Markdown：
{
  "mode": "sql" 或 "dsl",
  "index": "目标表/索引",
  "query": "SQL字符串 或 DSL对象",
  "reason": "简短说明"
}
- 只读；SQL 只能是 SELECT。
- 可使用该方言支持的 JOIN / EXISTS 等（以召回 dialect 规则为准）。
"""


SYSTEM_HBASE = """
【本引擎请输出 HBase Scan 计划（不要输出 SQL）】
输出必须是严格 JSON，不要 Markdown：
{
  "mode": "scan",
  "query": {
    "table": "namespace:table 或 table",
    "families": ["cf"],
    "prefix": null,
    "filters": [ {"col":"cf:qualifier","op":"=|!=|like","value":"..."} ],
    "limit": 50
  },
  "reason": "简短说明"
}
- 只读 Scan/Get。禁止 put/delete/admin。
- 不要写 JOIN / SELECT。
"""


def _system_for_dialect(dialect: str) -> str:
    d = normalize_dialect(dialect)
    if d in ("elasticsearch", "es"):
        return SYSTEM_BASE + SYSTEM_IR
    if d == "hbase":
        return SYSTEM_BASE + SYSTEM_HBASE
    return SYSTEM_BASE + SYSTEM_SQL


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
    system = _system_for_dialect(dialect)
    raw = await client.chat(system, user)
    data = _parse_json(raw)
    mode = (data.get("mode") or "").lower().strip()
    dial = normalize_dialect(dialect)

    # ES：强制走 IR（若模型误输出 sql，尝试从常见结构挽救，否则报错重试）
    if dial in ("elasticsearch", "es"):
        if mode != "ir":
            # 兼容：若看起来像 IR 字段
            if "from" in data or "semi_joins" in data:
                mode = "ir"
            else:
                raise ValueError(
                    f"Elasticsearch 需要 mode=ir 的查询计划，但模型返回 mode={mode or '空'}。"
                    "请只输出 IR JSON（from/where/semi_joins）。"
                )
        ir = parse_ir(data)
        return {
            "mode": "ir",
            "query": ir.model_dump(by_alias=True),
            "index": ir.from_index,
            "reason": ir.reason or data.get("reason", ""),
            "ir": ir,
            "raw": raw,
        }

    if dial == "hbase":
        query = data.get("query")
        if isinstance(query, str):
            try:
                query = json.loads(query)
            except json.JSONDecodeError:
                pass
        if not isinstance(query, dict):
            query = {
                k: data[k]
                for k in ("table", "families", "filters", "limit", "prefix")
                if k in data
            }
        return {
            "mode": "scan",
            "query": query,
            "index": (query or {}).get("table") if isinstance(query, dict) else "",
            "reason": data.get("reason", ""),
            "raw": raw,
        }

    mode = mode or "sql"
    query = data.get("query")
    index = data.get("index") or data.get("table") or data.get("from") or ""
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
