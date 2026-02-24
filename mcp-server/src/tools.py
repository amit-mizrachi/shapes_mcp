from __future__ import annotations

import json
from db import get_column_info, get_read_connection, get_table_name


def _valid_columns() -> set[str]:
    return {c["name"] for c in get_column_info()}


FILTER_OPS = {
    "_gt": ">",
    "_gte": ">=",
    "_lt": "<",
    "_lte": "<=",
}


def _build_where(
    filters: dict[str, str | int | float] | None,
    valid_columns: set[str],
    col_types: dict[str, str],
) -> tuple[str, list] | str:
    """Returns (where_sql, params) on success, or error JSON string on failure."""
    if not filters:
        return "", []
    parts: list[str] = []
    params: list[str | int | float] = []
    for key, value in filters.items():
        col, op = key, "="
        for suffix, sql_op in FILTER_OPS.items():
            if key.endswith(suffix):
                col, op = key[: -len(suffix)], sql_op
                break
        if col not in valid_columns:
            return json.dumps(
                {"error": f"Column '{col}' not found. Valid columns: {sorted(valid_columns)}"}
            )
        if col_types.get(col) == "numeric" and op != "=":
            parts.append(f'CAST("{col}" AS REAL) {op} ?')
        else:
            parts.append(f'"{col}" {op} ?')
        params.append(value)
    where_sql = (" WHERE " + " AND ".join(parts)) if parts else ""
    return where_sql, params


async def get_schema() -> str:
    """Return the database schema: table name, column names, detected types, and sample values.

    Use this tool FIRST to understand what data is available before querying.
    Takes no parameters.
    """
    info = get_column_info()
    table = get_table_name()
    if not info:
        return json.dumps({"error": "No data loaded"})
    return json.dumps({"table": table, "columns": info}, indent=2)


async def select_rows(
    filters: dict[str, str | int | float] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Retrieve rows from the data table.

    - fields: list of column names to return (default: all columns).
    - filters: dict of conditions. Key is a column name, optionally with a
      suffix _gt, _lt, _gte, or _lte for comparison operators.
      Example: {"age_gt": 30, "city": "London"}
    - limit: max rows to return (default 20, max 100).
    """
    valid = _valid_columns()
    table = get_table_name()
    if not valid:
        return json.dumps({"error": "No data loaded"})

    limit = min(max(1, limit), 100)
    col_types = {c["name"]: c["detected_type"] for c in get_column_info()}

    result = _build_where(filters, valid, col_types)
    if isinstance(result, str):
        return result
    where_sql, params = result

    if fields:
        for f in fields:
            if f not in valid:
                return json.dumps(
                    {"error": f"Column '{f}' not found. Valid columns: {sorted(valid)}"}
                )
        select_cols = ", ".join(f'"{f}"' for f in fields)
    else:
        select_cols = "*"

    sql = f'SELECT {select_cols} FROM "{table}"{where_sql} LIMIT ?'
    params.append(limit)

    conn = await get_read_connection()
    try:
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        data = [dict(zip(columns, row)) for row in rows]
        return json.dumps({"data": data, "count": len(data)})
    finally:
        await conn.close()


async def aggregate(
    op: str,
    field: str | None = None,
    group_by: str | None = None,
    filters: dict[str, str | int | float] | None = None,
    limit: int = 20,
) -> str:
    """Run an aggregation on the data table.

    - op: one of "count", "sum", "avg", "min", "max".
    - field: column to aggregate (not required for "count").
    - group_by: optional column to group results by.
    - filters: dict of conditions, same syntax as select_rows.
    - limit: max groups to return when using group_by (default 20, max 100).
    """
    valid = _valid_columns()
    table = get_table_name()
    if not valid:
        return json.dumps({"error": "No data loaded"})

    agg_op = op.upper()
    if agg_op not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
        return json.dumps({"error": f"Unsupported aggregation op: {op}. Use count, sum, avg, min, or max."})

    if agg_op != "COUNT" and (not field or field not in valid):
        return json.dumps(
            {"error": f"'field' is required for {op} and must be a valid column. Valid columns: {sorted(valid)}"}
        )

    if group_by and group_by not in valid:
        return json.dumps(
            {"error": f"Column '{group_by}' not found. Valid columns: {sorted(valid)}"}
        )

    limit = min(max(1, limit), 100)
    col_types = {c["name"]: c["detected_type"] for c in get_column_info()}

    result = _build_where(filters, valid, col_types)
    if isinstance(result, str):
        return result
    where_sql, params = result

    if agg_op == "COUNT":
        select_expr = "COUNT(*)"
    else:
        select_expr = f'{agg_op}(CAST("{field}" AS REAL))'

    if group_by:
        sql = f'SELECT "{group_by}", {select_expr} AS result FROM "{table}"{where_sql} GROUP BY "{group_by}" ORDER BY result DESC LIMIT ?'
        params.append(limit)
    else:
        sql = f'SELECT {select_expr} AS result FROM "{table}"{where_sql}'

    conn = await get_read_connection()
    try:
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        data = [dict(zip(columns, row)) for row in rows]
        return json.dumps({"data": data, "count": len(data)})
    finally:
        await conn.close()
