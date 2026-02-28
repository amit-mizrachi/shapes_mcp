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
from shared.modules.data.transform_expression import TransformExpression
from data_store.interfaces.data_store import DataStore
from data_store.sqlite_query_builder import SqliteQueryBuilder

logger = logging.getLogger(__name__)


class SqliteDataStore(DataStore):
    def __init__(self, database_path: str | None = None, table_schema: TableSchema = None) -> None:
        self._db_uri = database_path or Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._query_builder = SqliteQueryBuilder(table_schema)

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
        transform: Optional[TransformExpression] = None,
        filter_logic: str = "AND",
    ) -> QueryResult:
        query = self._query_builder.build_select(
            filters=filters, fields=fields, limit=limit,
            order_by=order_by, order=order, distinct=distinct,
            transform=transform, filter_logic=filter_logic,
        )
        return await self._run_query_with_total(query.sql, query.params, query.count_sql, query.count_params)

    async def aggregate(
        self,
        operation: str,
        field: Optional[str] = None,
        group_by: Optional[str | list[str]] = None,
        filters: Optional[list[FilterCondition]] = None,
        limit: int = Config.get("mcp_server.default_query_limit"),
        order_by: Optional[str] = None,
        order: str = "desc",
        having_operator: Optional[str] = None,
        having_value: Optional[float] = None,
        transform: Optional[TransformExpression] = None,
        filter_logic: str = "AND",
    ) -> QueryResult:
        query = self._query_builder.build_aggregate(
            operation=operation, field=field, group_by=group_by,
            filters=filters, limit=limit, order_by=order_by, order=order,
            having_operator=having_operator, having_value=having_value,
            transform=transform, filter_logic=filter_logic,
        )
        return await self._run_query(query.sql, query.params)

    async def _run_query_with_total(self, sql_query: str, params: list, count_sql: str, count_params: list) -> QueryResult:
        async with self._connection() as connection:
            try:
                cursor = await connection.execute(count_sql, count_params)
                total_count = (await cursor.fetchone())[0]
                result = await self._execute_query(connection, sql_query, params)
                return QueryResult(columns=result.columns, rows=result.rows, count=result.count, total_count=total_count)
            except Exception:
                logger.error("query failed | sql=%s params=%s", sql_query, params, exc_info=True)
                raise

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
        columns = [descriptor[0] for descriptor in cursor.description]
        row_dicts = [dict(zip(columns, row)) for row in rows]

        return QueryResult(columns=columns, rows=row_dicts, count=len(row_dicts))
