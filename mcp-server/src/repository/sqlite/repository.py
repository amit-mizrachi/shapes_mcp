from __future__ import annotations

import logging

import aiosqlite

from repository.models import ColumnInfo, QueryResult, TableSchema

logger = logging.getLogger(__name__)

FILTER_SUFFIX_TO_SQL_OPERATOR = {
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

    async def _open_readonly_connection(self) -> aiosqlite.Connection:
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
            for suffix, sql_op in FILTER_SUFFIX_TO_SQL_OPERATOR.items():
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
        where_clause = (" WHERE " + " AND ".join(parts)) if parts else ""
        return where_clause, params

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
            for field_name in fields:
                if field_name not in self._valid_columns:
                    raise ValueError(
                        f"Column '{field_name}' not found. Valid columns: {sorted(self._valid_columns)}"
                    )
            select_cols = ", ".join(f'"{field_name}"' for field_name in fields)
        else:
            select_cols = "*"

        where_clause, params = self._build_where(filters)
        sql = f'SELECT {select_cols} FROM "{self._table_name}"{where_clause} LIMIT ?'
        params.append(limit)

        conn = await self._open_readonly_connection()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            row_dicts = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
        except Exception:
            logger.error("select_rows query failed (sql=%s)", sql, exc_info=True)
            raise
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
        sql_operation = op.upper()
        if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(
                f"Unsupported aggregation op: {op}. Use count, sum, avg, min, or max."
            )

        if sql_operation != "COUNT" and (not field or field not in self._valid_columns):
            raise ValueError(
                f"'field' is required for {op} and must be a valid column. "
                f"Valid columns: {sorted(self._valid_columns)}"
            )

        if group_by and group_by not in self._valid_columns:
            raise ValueError(
                f"Column '{group_by}' not found. Valid columns: {sorted(self._valid_columns)}"
            )

        where_clause, params = self._build_where(filters)

        if sql_operation == "COUNT":
            aggregation_expression = "COUNT(*)"
        else:
            aggregation_expression = f'{sql_operation}(CAST("{field}" AS REAL))'

        if group_by:
            sql = (
                f'SELECT "{group_by}", {aggregation_expression} AS result '
                f'FROM "{self._table_name}"{where_clause} '
                f'GROUP BY "{group_by}" ORDER BY result DESC LIMIT ?'
            )
            params.append(limit)
        else:
            sql = f'SELECT {aggregation_expression} AS result FROM "{self._table_name}"{where_clause}'

        conn = await self._open_readonly_connection()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            row_dicts = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
        except Exception:
            logger.error("aggregate query failed (sql=%s)", sql, exc_info=True)
            raise
        finally:
            await conn.close()
