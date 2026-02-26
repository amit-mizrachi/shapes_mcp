from __future__ import annotations

import logging

import aiosqlite

from config import Config
from shared.modules.column_info import ColumnInfo
from shared.modules.query_result import QueryResult
from shared.modules.table_schema import TableSchema

logger = logging.getLogger(__name__)

FILTER_SUFFIX_TO_SQL_OPERATOR = {
    "_gt": ">",
    "_gte": ">=",
    "_lt": "<",
    "_lte": "<=",
}


class SqliteRepository:
    def __init__(self, db_uri: str, table_name: str, columns: list[ColumnInfo]) -> None:
        self._db_uri = db_uri
        self._table_name = table_name
        self._columns = columns
        self._valid_columns = {c.name for c in columns}
        self._column_types = {c.name: c.detected_type for c in columns}

    async def _open_read_only_connection(self) -> aiosqlite.Connection:
        # Shared-cache in-memory connections must be read-write; query_only pragma provides read-only safety
        connection = await aiosqlite.connect(self._db_uri, uri=True)
        await connection.execute("PRAGMA query_only = ON")
        connection.row_factory = aiosqlite.Row
        return connection

    def _build_where_clause(
        self,
        filters: dict[str, str | int | float] | None,
    ) -> tuple[str, list]:
        """Build a WHERE clause. Raises ValueError on invalid column names."""
        if not filters:
            return "", []
        parts: list[str] = []
        params: list[str | int | float] = []
        for key, value in filters.items():
            column, operation = key, "="
            for suffix, sql_operation in FILTER_SUFFIX_TO_SQL_OPERATOR.items():
                if key.endswith(suffix):
                    column, operation = key[: -len(suffix)], sql_operation
                    break
            if column not in self._valid_columns:
                raise ValueError(
                    f"Column '{column}' not found. Valid columns: {sorted(self._valid_columns)}"
                )
            if self._column_types.get(column) == "numeric" and operation != "=":
                parts.append(f'CAST("{column}" AS REAL) {operation} ?')
            else:
                parts.append(f'"{column}" {operation} ?')
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
        limit: int = Config.get("shared.default_query_limit"),
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

        where_clause, params = self._build_where_clause(filters)
        sql = f'SELECT {select_cols} FROM "{self._table_name}"{where_clause} LIMIT ?'
        params.append(limit)

        conn = await self._open_read_only_connection()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            row_dicts = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
        except Exception:
            logger.error("select_rows query failed", exc_info=True)
            raise
        finally:
            await conn.close()

    async def aggregate(
        self,
        op: str,
        field: str | None = None,
        group_by: str | None = None,
        filters: dict[str, str | int | float] | None = None,
        limit: int = Config.get("shared.default_query_limit"),
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

        where_clause, params = self._build_where_clause(filters)

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

        conn = await self._open_read_only_connection()
        try:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            row_dicts = [dict(zip(columns, row)) for row in rows]
            return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
        except Exception:
            logger.error("aggregate query failed", exc_info=True)
            raise
        finally:
            await conn.close()
