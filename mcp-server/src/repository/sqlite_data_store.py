from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite

from shared.config import Config
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.query_result import QueryResult
from shared.modules.data.table_schema import TableSchema
from repository.data_store import DataStore

logger = logging.getLogger(__name__)

class SqliteDataStore(DataStore):
    def __init__(self, table_schema: TableSchema) -> None:
        self._db_uri = Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._valid_columns = {c.name for c in table_schema.columns}

    async def get_schema(self) -> Optional[TableSchema]:
        if not self._table_schema.columns:
            return None
        return self._table_schema

    async def select_rows(
        self,
        filters: Optional[list[FilterCondition]] = None,
        fields: Optional[list[str]] = None,
        limit: int = Config.get("mcp_server.default_query_limit"),
        order_by: Optional[str] = None,
        order: str = "asc",
        distinct: bool = False,
    ) -> QueryResult:
        distinct_keyword = "DISTINCT " if distinct else ""
        select_columns = self._build_select_columns(fields)
        where_clause, params = self._build_where_clause(filters)
        order_clause = self._build_order_clause(order_by, order)

        sql_query = f'SELECT {distinct_keyword}{select_columns} FROM "{self._table_schema.table_name}"{where_clause}{order_clause} LIMIT ?'
        params.append(limit)

        return await self._run_query(sql_query, params)

    async def aggregate(
        self,
        operation: str,
        field: Optional[str] = None,
        group_by: Optional[str] = None,
        filters: Optional[list[FilterCondition]] = None,
        limit: int = Config.get("mcp_server.default_query_limit"),
        order_by: Optional[str] = None,
        order: str = "desc",
    ) -> QueryResult:
        validated_sql_operation = self._validate_aggregation_args(operation, field, group_by)
        aggregation_expression = self._build_aggregation_expression(validated_sql_operation, field)

        where_clause, params = self._build_where_clause(filters)
        sql_query, params = self._build_aggregated_sql_query(aggregation_expression, where_clause, params, group_by, limit, order_by, order)

        return await self._run_query(sql_query, params)

    def _build_select_columns(self, fields: Optional[list[str]]) -> str:
        if not fields:
            return "*"
        for field_name in fields:
            self._validate_column(field_name)
        return ", ".join(f'"{field_name}"' for field_name in fields)

    def _build_where_clause(self, filter_conditions: Optional[list[FilterCondition]],) -> tuple[str, list]:
        if not filter_conditions:
            return "", []
        parts: list[str] = []
        params: list = []
        for filter_condition in filter_conditions:
            self._validate_column(filter_condition.column)
            parts.append(self._filter_to_sql_expression(filter_condition))
            if filter_condition.operator == "IN":
                params.extend(filter_condition.value)
            else:
                params.append(filter_condition.value)
        where_clause = " WHERE " + " AND ".join(parts)
        return where_clause, params

    def _filter_to_sql_expression(self, filter_condition: FilterCondition) -> str:
        if filter_condition.operator == "LIKE":
            return f'"{filter_condition.column}" LIKE ?'
        if filter_condition.operator == "IN":
            placeholders = ",".join("?" * len(filter_condition.value))
            return f'"{filter_condition.column}" IN ({placeholders})'
        return f'"{filter_condition.column}" {filter_condition.operator} ?'

    def _build_order_clause(self, order_by: Optional[str], order: str) -> str:
        if order_by is None:
            return ""
        self._validate_column(order_by)
        normalized = order.upper()
        if normalized not in ("ASC", "DESC"):
            raise ValueError(f"order must be 'asc' or 'desc', got: {order!r}")
        return f' ORDER BY "{order_by}" {normalized}'

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
        return f'{sql_operation}("{field}")'

    def _build_aggregated_sql_query(self, aggregation_expression, where_clause, params, group_by, limit, order_by, order):
        if not group_by:
            sql_query = f'SELECT {aggregation_expression} AS result FROM "{self._table_schema.table_name}"{where_clause}'
            return sql_query, params

        order_clause = self._build_order_clause(order_by, order)
        sql_query = (
            f'SELECT "{group_by}", {aggregation_expression} AS result '
            f'FROM "{self._table_schema.table_name}"{where_clause} '
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
                logger.error("query failed | sql=%s params=%s", sql_query, params, exc_info=True)
                raise

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self._db_uri)
        await connection.execute("PRAGMA query_only = ON")
        connection.row_factory = aiosqlite.Row
        try:
            yield connection
        finally:
            await connection.close()

    async def _execute_query(self, connection: aiosqlite.Connection, sql_query: str, params: list) -> QueryResult:
        cursor = await connection.execute(sql_query, params)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        row_dicts = [dict(zip(columns, row)) for row in rows]
        return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
