from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite

from shared.config import Config
from shared.modules.column_info import ColumnInfo
from shared.modules.filter_condition import FilterCondition
from shared.modules.query_result import QueryResult
from shared.modules.table_schema import TableSchema

logger = logging.getLogger(__name__)

VALID_SQL_OPS = {"=", ">", ">=", "<", "<=", "LIKE", "IN"}


class SqliteRepository:
    def __init__(self, db_uri: str, table_name: str, columns: list[ColumnInfo]) -> None:
        self._db_uri = db_uri
        self._table_name = table_name
        self._columns = columns
        self._valid_columns = {c.name for c in columns}
        self._column_types = {c.name: c.detected_type for c in columns}

    async def get_schema(self) -> Optional[TableSchema]:
        if not self._columns:
            return None
        return TableSchema(table_name=self._table_name, columns=self._columns)

    async def select_rows(
        self,
        filters: Optional[list[FilterCondition]] = None,
        fields: Optional[list[str]] = None,
        limit: int = Config.get("shared.default_query_limit"),
        order_by: Optional[str] = None,
        order: str = "asc",
        distinct: bool = False,
    ) -> QueryResult:
        select_columns = self._build_select_columns(fields)
        where_clause, params = self._build_where_clause(filters)
        order_clause = self._build_order_clause(order_by, order)
        distinct_keyword = "DISTINCT " if distinct else ""
        sql_query = f'SELECT {distinct_keyword}{select_columns} FROM "{self._table_name}"{where_clause}{order_clause} LIMIT ?'
        params.append(limit)

        return await self._run_query(sql_query, params)

    async def aggregate(
        self,
        operation: str,
        field: Optional[str] = None,
        group_by: Optional[str] = None,
        filters: Optional[list[FilterCondition]] = None,
        limit: int = Config.get("shared.default_query_limit"),
        order_by: Optional[str] = None,
        order: str = "desc",
    ) -> QueryResult:
        operation = self._validate_aggregation_args(operation, field, group_by)
        where_clause, params = self._build_where_clause(filters)
        aggregation_expression = self._build_aggregation_expression(operation, field)
        sql_query, params = self._build_aggregated_sql_query(
            aggregation_expression, where_clause, params, group_by, limit, order_by, order,
        )

        return await self._run_query(sql_query, params)

    def _build_select_columns(self, fields: Optional[list[str]]) -> str:
        if not fields:
            return "*"
        for field_name in fields:
            self._validate_column(field_name)
        return ", ".join(f'"{field_name}"' for field_name in fields)

    def _build_where_clause(
        self,
        filters: Optional[list[FilterCondition]],
    ) -> tuple[str, list]:
        if not filters:
            return "", []
        parts: list[str] = []
        params: list = []
        for filter in filters:
            self._validate_filter(filter)
            parts.append(self._filter_to_sql_expression(filter))
            if filter.op == "IN":
                params.extend(filter.value)
            else:
                params.append(filter.value)
        where_clause = " WHERE " + " AND ".join(parts)
        return where_clause, params

    def _validate_filter(self, f: FilterCondition) -> None:
        self._validate_column(f.column)
        if f.op not in VALID_SQL_OPS:
            raise ValueError(f"Unknown filter operator '{f.op}'")

    def _filter_to_sql_expression(self, f: FilterCondition) -> str:
        if f.op == "LIKE":
            return f'"{f.column}" LIKE ?'
        if f.op == "IN":
            placeholders = ",".join("?" * len(f.value))
            return f'"{f.column}" IN ({placeholders})'
        if self._column_types.get(f.column) == "numeric" and f.op != "=":
            return f'CAST("{f.column}" AS REAL) {f.op} ?'
        return f'"{f.column}" {f.op} ?'

    def _build_order_clause(self, order_by: Optional[str], order: str) -> str:
        if order_by is None:
            return ""
        self._validate_column(order_by)
        return f' ORDER BY "{order_by}" {order.upper()}'

    def _validate_aggregation_args(self, operation: str, field: Optional[str], group_by: Optional[str]) -> str:
        sql_operation = operation.upper()
        if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(f"Unsupported aggregation op: {operation}. Use count, sum, avg, min, or max.")
        if sql_operation != "COUNT":
            if not field:
                raise ValueError(f"'field' is required for {operation}.")
            self._validate_column(field)
        if group_by:
            self._validate_column(group_by)
        return sql_operation

    def _build_aggregation_expression(self, sql_operation: str, field: Optional[str]) -> str:
        if sql_operation == "COUNT":
            return "COUNT(*)"
        return f'{sql_operation}(CAST("{field}" AS REAL))'

    def _build_aggregated_sql_query(self, aggregation_expression, where_clause, params, group_by, limit, order_by, order):
        if not group_by:
            sql_query = f'SELECT {aggregation_expression} AS result FROM "{self._table_name}"{where_clause}'
            return sql_query, params

        order_clause = self._build_order_clause(order_by, order)
        sql_query = (
            f'SELECT "{group_by}", {aggregation_expression} AS result '
            f'FROM "{self._table_name}"{where_clause} '
            f'GROUP BY "{group_by}"{order_clause} LIMIT ?'
        )
        params.append(limit)
        return sql_query, params

    def _validate_column(self, column: str) -> None:
        if column not in self._valid_columns:
            raise ValueError(f"Column '{column}' not found. Valid columns: {sorted(self._valid_columns)}")

    async def _run_query(self, sql_query: str, params: list) -> QueryResult:
        async with self._connection() as connection:
            try:
                return await self._execute_query(connection, sql_query, params)
            except Exception:
                logger.error("query failed")
                raise

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        # Shared-cache in-memory connections must be read-write; query_only pragma provides read-only safety
        connection = await aiosqlite.connect(self._db_uri, uri=True)
        await connection.execute("PRAGMA query_only = ON")
        connection.row_factory = aiosqlite.Row
        try:
            yield connection
        finally:
            await connection.close()

    async def _execute_query(self, connection: aiosqlite.Connection, sql: str, params: list) -> QueryResult:
        cursor = await connection.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        row_dicts = [dict(zip(columns, row)) for row in rows]
        return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
