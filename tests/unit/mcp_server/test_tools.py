"""Tests for mcp-server/src/tool_handlers.py — MCP tool handlers."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.query_result import QueryResult
from shared.modules.data.table_schema import TableSchema
import tool_handlers


def _make_mock_ctx(data_store=None):
    """Create a mock MCP Context with a data store in lifespan context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"data_store": data_store}
    return ctx


def _make_mock_data_store():
    """Create a mock DataStore with async methods."""
    mock_store = AsyncMock()
    mock_store.get_schema = AsyncMock(return_value=TableSchema(
        table_name="test_table",
        columns=[
            ColumnInfo(name="name", detected_type="text", samples=["Alice", "Bob"]),
            ColumnInfo(name="age", detected_type="numeric", samples=["30", "25"]),
        ],
    ))
    mock_store.select_rows = AsyncMock(return_value=QueryResult(
        columns=["name", "age"],
        rows=[{"name": "Alice", "age": "30"}],
        count=1,
    ))
    mock_store.aggregate = AsyncMock(return_value=QueryResult(
        columns=["result"],
        rows=[{"result": 5}],
        count=1,
    ))
    return mock_store


class TestGetSchema:
    async def test_returns_schema_json(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        result = json.loads(await tool_handlers.get_schema(ctx))
        assert result["table"] == "test_table"
        assert len(result["columns"]) == 2
        assert result["columns"][0]["name"] == "name"

    async def test_no_data_loaded(self):
        mock_store = AsyncMock()
        mock_store.get_schema = AsyncMock(return_value=None)
        ctx = _make_mock_ctx(mock_store)
        result = json.loads(await tool_handlers.get_schema(ctx))
        assert "error" in result

    async def test_no_data_store_returns_error(self):
        ctx = _make_mock_ctx(None)
        result = json.loads(await tool_handlers.get_schema(ctx))
        assert "error" in result
        assert "DataStore not initialized" in result["error"]


class TestSelectRows:
    async def test_basic_select(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        result = json.loads(await tool_handlers.select_rows(context=ctx))
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Alice"

    async def test_with_filters(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        filters = [FilterCondition(column="age", operator=">", value=25)]
        await tool_handlers.select_rows(filters=filters, context=ctx)
        mock_store.select_rows.assert_called_once()
        call_filters = mock_store.select_rows.call_args.kwargs["filters"]
        assert call_filters[0].column == "age"

    async def test_with_fields_and_limit(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        await tool_handlers.select_rows(fields=["name"], limit=5, context=ctx)
        mock_store.select_rows.assert_called_once_with(
            filters=None, fields=["name"], limit=5,
            order_by=None, order="asc", distinct=False,
        )


class TestAggregate:
    async def test_basic_count(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        result = json.loads(await tool_handlers.aggregate(operation="count", context=ctx))
        assert result["count"] == 1

    async def test_with_group_by(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        await tool_handlers.aggregate(operation="count", group_by="city", context=ctx)
        mock_store.aggregate.assert_called_once()
        assert mock_store.aggregate.call_args.kwargs["group_by"] == "city"

    async def test_with_filters(self):
        mock_store = _make_mock_data_store()
        ctx = _make_mock_ctx(mock_store)
        filters = [FilterCondition(column="age", operator=">=", value=18)]
        await tool_handlers.aggregate(operation="sum", field="score", filters=filters, context=ctx)
        call_filters = mock_store.aggregate.call_args.kwargs["filters"]
        assert call_filters[0].operator == ">="

    async def test_invalid_op_returns_error(self):
        mock_store = _make_mock_data_store()
        mock_store.aggregate = AsyncMock(side_effect=ValueError("Unsupported aggregation op"))
        ctx = _make_mock_ctx(mock_store)
        result = json.loads(await tool_handlers.aggregate(operation="median", field="age", context=ctx))
        assert "error" in result
