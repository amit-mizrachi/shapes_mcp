from __future__ import annotations

import aiosqlite

from repository.protocol import ColumnInfo, QueryResult, TableSchema

FILTER_OPS = {
    "_gt": ">",
    "_gte": ">=",
    "_lt": "<",
    "_lte": "<=",
}


class SqliteRepository:
    def __init__(self, db_path: str, table_name: str, columns: list[ColumnInfo]) -> None:
        self._db_path = db_path
        self._table_name = table_name
        self._columns = columns
        self._valid_columns = {c.name for c in columns}
        self._col_types = {c.name: c.detected_type for c in columns}

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = aiosqlite.Row
        return conn

    def _build_where(
        self,
        filters: dict[str, str | int | float] | None,
    ) -> tuple[str, list]:
        """Build a WHERE clause. Raises ValueError on invalid column names."""
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
            if col not in self._valid_columns:
                raise ValueError(
                    f"Column '{col}' not found. Valid columns: {sorted(self._valid_columns)}"
                )
            if self._col_types.get(col) == "numeric" and op != "=":
                parts.append(f'CAST("{col}" AS REAL) {op} ?')
            else:
                parts.append(f'"{col}" {op} ?')
            params.append(value)
        where_sql = (" WHERE " + " AND ".join(parts)) if parts else ""
        return where_sql, params

    async def get_schema(self) -> TableSchema | None:
        if not self._columns:
            return None
        return TableSchema(table_name=self._table_name, columns=self._columns)

    async def select_rows(
        self,
        filters: dict[str, str | int | float] | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
    ) -> QueryResult:
        if fields:
            for f in fields:
                if f not in self._valid_columns:
                    raise ValueError(
                        f"Column '{f}' not found. Valid columns: {sorted(self._valid_columns)}"
                    )
            select_cols = ", ".join(f'"{f}"' for f in fields)
        else:
            select_cols = "*"

        where_sql, params = self._build_where(filters)
        sql = f'SELECT {select_cols} FROM "{self._table_name}"{where_sql} LIMIT ?'
        params.append(limit)

        conn = await self._connect()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            data = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=data, count=len(data))
        finally:
            await conn.close()

    async def aggregate(
        self,
        op: str,
        field: str | None = None,
        group_by: str | None = None,
        filters: dict[str, str | int | float] | None = None,
        limit: int = 20,
    ) -> QueryResult:
        agg_op = op.upper()
        if agg_op not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(
                f"Unsupported aggregation op: {op}. Use count, sum, avg, min, or max."
            )

        if agg_op != "COUNT" and (not field or field not in self._valid_columns):
            raise ValueError(
                f"'field' is required for {op} and must be a valid column. "
                f"Valid columns: {sorted(self._valid_columns)}"
            )

        if group_by and group_by not in self._valid_columns:
            raise ValueError(
                f"Column '{group_by}' not found. Valid columns: {sorted(self._valid_columns)}"
            )

        where_sql, params = self._build_where(filters)

        if agg_op == "COUNT":
            select_expr = "COUNT(*)"
        else:
            select_expr = f'{agg_op}(CAST("{field}" AS REAL))'

        if group_by:
            sql = (
                f'SELECT "{group_by}", {select_expr} AS result '
                f'FROM "{self._table_name}"{where_sql} '
                f'GROUP BY "{group_by}" ORDER BY result DESC LIMIT ?'
            )
            params.append(limit)
        else:
            sql = f'SELECT {select_expr} AS result FROM "{self._table_name}"{where_sql}'

        conn = await self._connect()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            data = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=data, count=len(data))
        finally:
            await conn.close()
