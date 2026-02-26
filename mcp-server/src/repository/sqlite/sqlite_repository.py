from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from shared.config import Config
from shared.modules.column_info import ColumnInfo
from shared.modules.filter_condition import FilterCondition
from shared.modules.query_result import QueryResult
from shared.modules.table_schema import TableSchema

logger = logging.getLogger(__name__)

VALID_SQL_OPS = {"=", ">", ">=", "<", "<="}


class SqliteRepository:
    def __init__(self, db_uri: str, table_name: str, columns: list[ColumnInfo]) -> None:
        self._db_uri = db_uri
        self._table_name = table_name
        self._columns = columns
        self._valid_columns = {c.name for c in columns}
        self._column_types = {c.name: c.detected_type for c in columns}

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        # Shared-cache in-memory connections must be read-write; query_only pragma provides read-only safety
        conn = await aiosqlite.connect(self._db_uri, uri=True)
        await conn.execute("PRAGMA query_only = ON")
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def _execute_query(self, conn: aiosqlite.Connection, sql: str, params: list) -> QueryResult:
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        row_dicts = [dict(zip(columns, row)) for row in rows]
        return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))

    def _validate_column(self, column: str) -> None:
        if column not in self._valid_columns:
            raise ValueError(f"Column '{column}' not found. Valid columns: {sorted(self._valid_columns)}")

    def _build_where_clause(
        self,
        filters: list[FilterCondition] | None,
    ) -> tuple[str, list]:
        """Build a WHERE clause from pre-parsed FilterCondition objects."""
        if not filters:
            return "", []
        parts: list[str] = []
        params: list[str | int | float] = []
        for f in filters:
            self._validate_column(f.column)
            if f.op not in VALID_SQL_OPS:
                raise ValueError(f"Unknown filter operator '{f.op}'")
            if self._column_types.get(f.column) == "numeric" and f.op != "=":
                parts.append(f'CAST("{f.column}" AS REAL) {f.op} ?')
            else:
                parts.append(f'"{f.column}" {f.op} ?')
            params.append(f.value)
        where_clause = " WHERE " + " AND ".join(parts)
        return where_clause, params

    async def get_schema(self) -> TableSchema | None:
        if not self._columns:
            return None
        return TableSchema(table_name=self._table_name, columns=self._columns)

    async def select_rows(
        self,
        filters: list[FilterCondition] | None = None,
        fields: list[str] | None = None,
        limit: int = Config.get("shared.default_query_limit"),
    ) -> QueryResult:
        if fields:
            for field_name in fields:
                self._validate_column(field_name)
            select_cols = ", ".join(f'"{field_name}"' for field_name in fields)
        else:
            select_cols = "*"

        where_clause, params = self._build_where_clause(filters)
        sql = f'SELECT {select_cols} FROM "{self._table_name}"{where_clause} LIMIT ?'
        params.append(limit)

        async with self._connection() as conn:
            try:
                return await self._execute_query(conn, sql, params)
            except Exception:
                logger.error("select_rows query failed", exc_info=True)
                raise

    async def aggregate(
        self,
        operation: str,
        field: str | None = None,
        group_by: str | None = None,
        filters: list[FilterCondition] | None = None,
        limit: int = Config.get("shared.default_query_limit"),
    ) -> QueryResult:
        sql_operation = operation.upper()
        if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(
                f"Unsupported aggregation op: {operation}. Use count, sum, avg, min, or max."
            )

        if sql_operation != "COUNT":
            if not field:
                raise ValueError(f"'field' is required for {operation}.")
            self._validate_column(field)

        if group_by:
            self._validate_column(group_by)

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

        async with self._connection() as conn:
            try:
                return await self._execute_query(conn, sql, params)
            except Exception:
                logger.error("aggregate query failed", exc_info=True)
                raise
