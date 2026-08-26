"""一致性测试：同问句多次执行，比对最终结果集。"""
from __future__ import annotations

from typing import Any

from nl2sql_core.pipeline import NL2SQLPipeline


def _row_key(columns: list[str], row: list[Any]) -> str:
    """整行规范化作为行身份（不绑定具体业务证件字段名）。"""
    parts = []
    for i, c in enumerate(columns):
        v = row[i] if i < len(row) else None
        parts.append(f"{c}={'' if v is None else v}")
    return "|".join(parts)


def _keyset(columns: list[str], rows: list[list[Any]]) -> set[str]:
    return {_row_key(columns, r) for r in rows if r}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 1.0


def pairwise_mean_jaccard(sets: list[set[str]]) -> float:
    if len(sets) < 2:
        return 1.0 if sets else 0.0
    scores = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            scores.append(jaccard(sets[i], sets[j]))
    return sum(scores) / len(scores) if scores else 0.0


def project_rows(
    columns: list[str],
    rows: list[list[Any]],
    keep: list[str] | None,
) -> tuple[list[str], list[list[Any]]]:
    if not keep:
        return columns, rows
    idxs = [i for i, c in enumerate(columns) if c in keep]
    if not idxs:
        return columns, rows
    new_cols = [columns[i] for i in idxs]
    new_rows = [[row[i] if i < len(row) else None for i in idxs] for row in rows]
    return new_cols, new_rows


async def run_consistency(
    query: str,
    *,
    datasource_id: str = "local-es",
    repeats: int = 3,
    mode: str = "auto",
) -> dict[str, Any]:
    """跳过澄清；多次跑 Pipeline；报错轮次不参与；0 行可互相比。"""
    repeats = max(1, min(int(repeats), 10))
    pipe = NL2SQLPipeline()
    runs: list[dict[str, Any]] = []
    valid_sets: list[set[str]] = []
    common_cols: set[str] | None = None

    for k in range(1, repeats + 1):
        info: dict[str, Any] = {"run": k}
        try:
            out = await pipe.run(
                query,
                datasource_id=datasource_id,
                mode=mode,
                use_llm=True,
            )
            if out.error:
                info["ok"] = False
                info["error"] = out.error
                info["invalid"] = True
            else:
                result = out.result
                cols = list(result.columns) if result else []
                rows = list(result.rows) if result else []
                info["ok"] = True
                info["row_count"] = result.row_count if result else 0
                info["columns"] = cols
                info["rows_preview"] = rows[:20]
                info["generated_query"] = out.generated_query
                info["invalid"] = False
                if common_cols is None:
                    common_cols = set(cols)
                else:
                    common_cols &= set(cols)
                info["_cols"] = cols
                info["_rows"] = rows
        except Exception as e:
            info["ok"] = False
            info["error"] = str(e)
            info["invalid"] = True
        runs.append(info)

    keep = sorted(common_cols) if common_cols else None
    for info in runs:
        if info.get("invalid") or not info.get("ok"):
            continue
        cols, rows = project_rows(info.pop("_cols"), info.pop("_rows"), keep)
        ks = _keyset(cols, rows)
        info["key_count"] = len(ks)
        valid_sets.append(ks)

    consistency = pairwise_mean_jaccard(valid_sets)
    return {
        "query": query,
        "repeats": repeats,
        "valid_runs": len(valid_sets),
        "invalid_runs": sum(1 for r in runs if r.get("invalid")),
        "result_consistency": round(consistency, 4),
        "runs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in runs],
    }
