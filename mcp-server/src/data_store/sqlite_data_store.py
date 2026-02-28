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
from data_store.data_store import DataStore

logger = logging.getLogger(__name__)

RESULT_ORDER_SENTINEL = "@result"
_AGG_RESULT_ALIAS = "result"

class SqliteDataStore(DataStore):
    def __init__(self, database_path: str | None = None, table_schema: TableSchema = None) -> None:
        self._db_uri = database_path or Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._valid_columns = {column.name for column in table_schema.columns}

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
        distinct_keyword = "DISTINCT " if distinct else ""
        select_columns = self._build_select_columns(fields)
        where_clause, where_params = self._build_where_clause(filters, filter_logic)

        if transform:
            self._validate_transform_columns(transform)
            case_sql, case_params = self._build_case_expression(transform)
            computed_col = f', {case_sql} AS "{transform.alias}"'
            transform_order = order_by == transform.alias
        else:
            computed_col = ""
            case_params = []
            transform_order = False

        if transform_order:
            normalized_order = self._validate_order_direction(order)
            order_clause = f' ORDER BY "{transform.alias}" {normalized_order}'
        else:
            order_clause = self._build_order_clause(order_by, order)

        count_sql = f'SELECT COUNT(*) FROM (SELECT {distinct_keyword}{select_columns} FROM "{self._table_schema.table_name}"{where_clause})'
        count_params = list(where_params)

        params = case_params + where_params
        sql_query = f'SELECT {distinct_keyword}{select_columns}{computed_col} FROM "{self._table_schema.table_name}"{where_clause}{order_clause} LIMIT ?'
        params.append(limit)

        return await self._run_query_with_total(sql_query, params, count_sql, count_params)

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
        group_by_columns = self._normalize_group_by(group_by)

        if transform:
            self._validate_transform_columns(transform)
            case_sql, case_params = self._build_case_expression(transform)
            validated_sql_operation = self._validate_aggregation_op(operation)
            aggregation_expression = f'{validated_sql_operation}({case_sql})'
        else:
            validated_sql_operation = self._validate_aggregation_args(operation, field, group_by_columns)
            aggregation_expression = self._build_aggregation_expression(validated_sql_operation, field)
            case_params = []

        where_clause, where_params = self._build_where_clause(filters, filter_logic)
        having_clause, having_params = self._build_having_clause(having_operator, having_value, group_by_columns)

        params = case_params + where_params
        sql_query, params = self._build_aggregated_sql_query(
            aggregation_expression, where_clause, params, group_by_columns, limit, order_by, order,
            having_clause, having_params,
        )

        return await self._run_query(sql_query, params)

    def _build_select_columns(self, fields: Optional[list[str]]) -> str:
        if not fields:
            return "*"

        for field_name in fields:
            self._validate_column(field_name)

        return ", ".join(f'"{field_name}"' for field_name in fields)

    def _build_where_clause(self, filter_conditions: Optional[list[FilterCondition]], filter_logic: str = "AND") -> tuple[str, list]:
        if not filter_conditions:
            return "", []

        joiner = filter_logic.upper()
        if joiner not in ("AND", "OR"):
            raise ValueError(f"filter_logic must be 'AND' or 'OR', got: {filter_logic!r}")

        parts: list[str] = []
        params: list = []

        for filter_condition in filter_conditions:
            self._validate_column(filter_condition.column)
            parts.append(self._filter_to_sql_expression(filter_condition))
            self._collect_filter_params(filter_condition, params)

        where_clause = " WHERE " + f" {joiner} ".join(parts)
        return where_clause, params

    def _filter_to_sql_expression(self, filter_condition: FilterCondition) -> str:
        column_reference = f'"{filter_condition.column}"'

        if filter_condition.operator in ("LIKE", "NOT LIKE"):
            return f'{column_reference} {filter_condition.operator} ?'

        if filter_condition.operator in ("IN", "NOT IN"):
            placeholders = ",".join("?" * len(filter_condition.value))
            return f'{column_reference} {filter_condition.operator} ({placeholders})'

        if filter_condition.operator == "IS NULL":
            return f'{column_reference} IS NULL'

        if filter_condition.operator == "IS NOT NULL":
            return f'{column_reference} IS NOT NULL'

        return f'{column_reference} {filter_condition.operator} ?'

    def _build_order_clause(self, order_by: Optional[str], order: str) -> str:
        if order_by is None:
            return ""

        self._validate_column(order_by)
        normalized_order = self._validate_order_direction(order)
        return f' ORDER BY "{order_by}" {normalized_order}'

    def _normalize_group_by(self, group_by: Optional[str | list[str]]) -> list[str]:
        if group_by is None:
            return []
        if isinstance(group_by, str):
            return [group_by]
        return list(group_by)

    def _validate_aggregation_args(self, operation: str, field: Optional[str], group_by_columns: list[str]) -> str:
        sql_operation = operation.upper()
        if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(f"Unsupported aggregation op: {operation}. Use count, sum, avg, min, or max.")

        if sql_operation != "COUNT":
            if not field:
                raise ValueError(f"'field' is required for {operation}.")
            self._validate_column(field)

        for column in group_by_columns:
            self._validate_column(column)

        return sql_operation

    def _validate_aggregation_op(self, operation: str) -> str:
        sql_operation = operation.upper()
        if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError(f"Unsupported aggregation op: {operation}. Use count, sum, avg, min, or max.")
        return sql_operation

    def _validate_transform_columns(self, transform: TransformExpression) -> None:
        self._validate_column(transform.source_column)
        for case in transform.cases:
            for filter_condition in case.when:
                self._validate_column(filter_condition.column)

    def _build_case_expression(self, transform: TransformExpression) -> tuple[str, list]:
        parts: list[str] = []
        params: list = []
        column_reference = f'"{transform.source_column}"'

        for case in transform.cases:
            when_parts: list[str] = []
            for filter_condition in case.when:
                when_parts.append(self._filter_to_sql_expression(filter_condition))
                self._collect_filter_params(filter_condition, params)

            condition = " AND ".join(when_parts)
            if case.then_multiply is not None:
                parts.append(f'WHEN {condition} THEN {column_reference} * ?')
                params.append(case.then_multiply)
            else:
                parts.append(f'WHEN {condition} THEN ?')
                params.append(case.then_value)

        if transform.else_multiply is not None:
            else_clause = f'ELSE {column_reference} * ?'
            params.append(transform.else_multiply)
        elif transform.else_value is not None:
            else_clause = 'ELSE ?'
            params.append(transform.else_value)
        else:
            else_clause = f'ELSE {column_reference}'

        case_sql = f'CASE {" ".join(parts)} {else_clause} END'
        return case_sql, params

    def _build_aggregation_expression(self, sql_operation: str, field: Optional[str]) -> str:
        if sql_operation == "COUNT":
            return "COUNT(*)"

        return f'{sql_operation}("{field}")'

    def _build_having_clause(self, having_operator: Optional[str], having_value: Optional[float], group_by_columns: list[str]) -> tuple[str, list]:
        if having_value is None:
            return "", []
        if not group_by_columns:
            raise ValueError("having_operator/having_value require group_by to be set.")
        valid_having_ops = {"=", "!=", ">", ">=", "<", "<="}
        operator = having_operator or ">="
        if operator not in valid_having_ops:
            raise ValueError(f"having_operator must be one of {sorted(valid_having_ops)}, got: {operator!r}")
        return f' HAVING {_AGG_RESULT_ALIAS} {operator} ?', [having_value]

    def _build_aggregated_sql_query(self, aggregation_expression, where_clause, params, group_by_columns, limit, order_by, order, having_clause="", having_params=None):
        if not group_by_columns:
            sql_query = f'SELECT {aggregation_expression} AS {_AGG_RESULT_ALIAS} FROM "{self._table_schema.table_name}"{where_clause}'
            return sql_query, list(params)

        if order_by == RESULT_ORDER_SENTINEL:
            normalized_order = self._validate_order_direction(order)
            order_clause = f' ORDER BY {_AGG_RESULT_ALIAS} {normalized_order}'
        else:
            order_clause = self._build_order_clause(order_by, order)

        group_by_sql = ", ".join(f'"{column}"' for column in group_by_columns)
        select_columns = ", ".join(f'"{column}"' for column in group_by_columns)

        sql_query = (
            f'SELECT {select_columns}, {aggregation_expression} AS {_AGG_RESULT_ALIAS} '
            f'FROM "{self._table_schema.table_name}"{where_clause} '
            f'GROUP BY {group_by_sql}{having_clause}{order_clause} LIMIT ?'
        )
        all_params = list(params) + (having_params or []) + [limit]
        return sql_query, all_params

    def _collect_filter_params(self, filter_condition: FilterCondition, params: list) -> None:
        if filter_condition.operator in ("IN", "NOT IN"):
            params.extend(filter_condition.value)
        elif filter_condition.operator not in ("IS NULL", "IS NOT NULL"):
            params.append(filter_condition.value)

    def _validate_order_direction(self, order: str) -> str:
        normalized = order.upper()
        if normalized not in ("ASC", "DESC"):
            raise ValueError(f"order must be 'asc' or 'desc', got: {order!r}")
        return normalized

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
