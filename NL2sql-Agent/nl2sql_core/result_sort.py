"""查询结果稳定排序：按列从左到右比较单元格，保证同结果每次行序一致。"""
from __future__ import annotations

from typing import Any

from nl2sql_core.models import QueryResult


def _cell_sort_key(v: Any) -> tuple:
    """None 最后；其余转 str，避免混类型比较报错。"""
    if v is None:
        return (1, "")
    return (0, str(v))


def sort_result_rows(result: QueryResult) -> QueryResult:
    """就地稳定排序 rows；无身份证等业务键时，按当前列顺序逐列比较。"""
    if not result.rows:
        result.row_count = 0
        return result
    ncols = len(result.columns)

    def row_key(row: list[Any]) -> tuple:
        cells = []
        for i in range(ncols):
            cells.append(_cell_sort_key(row[i] if i < len(row) else None))
        # 行长度异常时也纳入，保证全序
        if len(row) > ncols:
            cells.extend(_cell_sort_key(v) for v in row[ncols:])
        return tuple(cells)

    result.rows = sorted(result.rows, key=row_key)
    result.row_count = len(result.rows)
    return result
