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


async def query_data(
    filters: dict[str, str | int | float] | None = None,
    fields: list[str] | None = None,
    aggregation: dict | None = None,
    limit: int = 20,
) -> str:
    """Query the data table. Two modes:

    **Select mode** (default): retrieves rows.
      - fields: list of column names to return (default: all columns)
      - filters: dict of conditions. Key is column name, optionally with suffix _gt, _lt, _gte, _lte.
        Example: {"age_gt": 30, "city": "London"}
      - limit: max rows to return (default 20, max 100)

    **Aggregation mode**: set the `aggregation` parameter.
      - aggregation.op: one of "count", "sum", "avg", "min", "max"
      - aggregation.field: column to aggregate (not needed for "count")
      - aggregation.group_by: optional column to group by
      - filters: optional, same as select mode

    All column names are validated against the actual schema.
    """
    valid = _valid_columns()
    table = get_table_name()
    if not valid:
        return json.dumps({"error": "No data loaded"})

    limit = min(max(1, limit), 100)
    where_parts: list[str] = []
    params: list[str | int | float] = []

    col_types = {c["name"]: c["detected_type"] for c in get_column_info()}

    if filters:
        for key, value in filters.items():
            col = key
            op = "="
            for suffix, sql_op in FILTER_OPS.items():
                if key.endswith(suffix):
                    col = key[: -len(suffix)]
                    op = sql_op
                    break
            if col not in valid:
                return json.dumps({
                    "error": f"Column '{col}' not found. Valid columns: {sorted(valid)}"
                })
            if col_types.get(col) == "numeric" and op != "=":
                where_parts.append(f'CAST("{col}" AS REAL) {op} ?')
            else:
                where_parts.append(f'"{col}" {op} ?')
            params.append(value)

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    conn = await get_read_connection()
    try:
        if aggregation:
            agg_op = aggregation.get("op", "count").upper()
            if agg_op not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                return json.dumps({"error": f"Unsupported aggregation: {agg_op}"})

            agg_field = aggregation.get("field")
            group_by = aggregation.get("group_by")

            if agg_op != "COUNT" and (not agg_field or agg_field not in valid):
                return json.dumps({
                    "error": f"aggregation.field required and must be a valid column. Valid columns: {sorted(valid)}"
                })
            if group_by and group_by not in valid:
                return json.dumps({
                    "error": f"Column '{group_by}' not found. Valid columns: {sorted(valid)}"
                })

            if agg_op == "COUNT":
                select_expr = "COUNT(*)"
            else:
                select_expr = f'{agg_op}(CAST("{agg_field}" AS REAL))'

            if group_by:
                sql = f'SELECT "{group_by}", {select_expr} AS result FROM "{table}"{where_sql} GROUP BY "{group_by}" ORDER BY result DESC LIMIT ?'
                params.append(limit)
            else:
                sql = f'SELECT {select_expr} AS result FROM "{table}"{where_sql}'

            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return json.dumps({"data": result, "count": len(result)})

        else:
            if fields:
                for f in fields:
                    if f not in valid:
                        return json.dumps({
                            "error": f"Column '{f}' not found. Valid columns: {sorted(valid)}"
                        })
                select_cols = ", ".join(f'"{f}"' for f in fields)
            else:
                select_cols = "*"

            sql = f'SELECT {select_cols} FROM "{table}"{where_sql} LIMIT ?'
            params.append(limit)

            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return json.dumps({"data": result, "count": len(result)})
    finally:
        await conn.close()
