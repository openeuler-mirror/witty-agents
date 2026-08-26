from __future__ import annotations

from typing import Any

from nl2sql_core.models import QueryResult


def build_retry_feedback(
    *,
    natural_query: str,
    generated: str | dict[str, Any],
    error: str | None = None,
    result: QueryResult | None = None,
    attempt: int = 1,
) -> str:
    """把执行/校验结果整理成给 LLM 的纠错提示。

    仅描述本次失败事实；业务/方言修正依赖再次附带的召回规则，不在此写死库表字段。
    """
    lines = [f"第 {attempt} 次尝试未得到可用结果，请修正 SQL/DSL 后重试。"]

    if error:
        lines.append(f"执行错误：{error}")

    if isinstance(generated, str):
        sql = generated.strip()
        if sql:
            lines.append(f"上次查询：{sql[:1200]}")
    elif isinstance(generated, dict):
        lines.append(f"上次查询：{str(generated)[:1200]}")

    if result is not None:
        lines.append(f"返回行数：{result.row_count}")
        for w in result.warnings or []:
            lines.append(f"引擎提示：{w}")

    if result is not None and result.row_count == 0 and not error:
        lines.append(
            "结果为 0 行：请根据召回规则核对索引/字段/别名与过滤条件；"
            "若规则表明样例可能无交集，可在 reason 中说明。"
        )

    lines.append(
        "请严格依据召回规则（含 dialect/domain/mapping）修正，不要重复同样错误。"
    )
    lines.append(f"原始问题：{natural_query}")
    return "\n".join(lines)


def should_retry(
    *,
    error: str | None,
    result: QueryResult | None,
    retry_on_empty: bool,
    attempt: int,
    max_attempts: int,
) -> bool:
    if attempt >= max_attempts:
        return False
    if error:
        return True
    if retry_on_empty and result is not None and result.row_count == 0:
        return True
    return False
