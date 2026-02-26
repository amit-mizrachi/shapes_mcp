"""Tests for mcp-server/src/mcp_tools.py — MCP tool handlers + filter parsing."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.query_result import QueryResult
from shared.modules.data.table_schema import TableSchema
import mcp_tools


def _make_mock_ctx(repository=None):
    """Create a mock MCP Context with a repository in lifespan context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"repository": repository}
    return ctx


def _make_mock_repository():
    """Create a mock DataRepository with async methods."""
    repo = AsyncMock()
    repo.get_schema = AsyncMock(return_value=TableSchema(
        table_name="test_table",
        columns=[
            ColumnInfo(name="name", detected_type="text", samples=["Alice", "Bob"]),
            ColumnInfo(name="age", detected_type="numeric", samples=["30", "25"]),
        ],
    ))
    repo.select_rows = AsyncMock(return_value=QueryResult(
        columns=["name", "age"],
        rows=[{"name": "Alice", "age": "30"}],
        count=1,
    ))
    repo.aggregate = AsyncMock(return_value=QueryResult(
        columns=["result"],
        rows=[{"result": 5}],
        count=1,
    ))
    return repo


class TestParseFilters:
    def test_none_input(self):
        assert tools._parse_filters(None) is None

    def test_empty_list(self):
        assert tools._parse_filters([]) is None

    def test_valid_filter(self):
        raw = [{"column": "age", "op": ">", "value": 30}]
        result = tools._parse_filters(raw)
        assert len(result) == 1
        assert result[0].column == "age"
        assert result[0].op == ">"
        assert result[0].value == 30

    def test_default_op_and_value(self):
        raw = [{"column": "name"}]
        result = tools._parse_filters(raw)
        assert result[0].op == "="
        assert result[0].value == ""

    def test_multiple_filters(self):
        raw = [
            {"column": "age", "op": ">=", "value": 18},
            {"column": "city", "value": "London"},
        ]
        result = mcp_tools._parse_filters(raw)
        assert len(result) == 2

    def test_missing_column_raises(self):
        with pytest.raises((ValueError, ValidationError)):
            mcp_tools._parse_filters([{"op": "=", "value": "x"}])

    def test_non_string_column_raises(self):
        with pytest.raises((ValueError, ValidationError)):
            mcp_tools._parse_filters([{"column": 123}])

    def test_invalid_op_raises(self):
        with pytest.raises((ValueError, ValidationError)):
            mcp_tools._parse_filters([{"column": "age", "op": "!="}])


class TestGetSchema:
    async def test_returns_schema_json(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        result = json.loads(await tools.get_schema(ctx))
        assert result["table"] == "test_table"
        assert len(result["columns"]) == 2
        assert result["columns"][0]["name"] == "name"

    async def test_no_data_loaded(self):
        repo = AsyncMock()
        repo.get_schema = AsyncMock(return_value=None)
        ctx = _make_mock_ctx(repo)
        result = json.loads(await tools.get_schema(ctx))
        assert "error" in result

    async def test_no_repository_raises(self):
        ctx = _make_mock_ctx(None)
        with pytest.raises(RuntimeError, match="Repository not initialized"):
            await mcp_tools.get_schema(ctx)


class TestSelectRows:
    async def test_basic_select(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        result = json.loads(await mcp_tools.select_rows(context=ctx))
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Alice"

    async def test_with_filters(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        raw_filters = [{"column": "age", "op": ">", "value": 25}]
        await tools.select_rows(filters=raw_filters, context=ctx)
        repo.select_rows.assert_called_once()
        call_filters = repo.select_rows.call_args.kwargs["filters"]
        assert call_filters[0].column == "age"

    async def test_with_fields_and_limit(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        await tools.select_rows(fields=["name"], limit=5, context=ctx)
        repo.select_rows.assert_called_once_with(
            filters=None, fields=["name"], limit=5,
            order_by=None, order="asc", distinct=False,
        )

    async def test_invalid_filter_returns_error(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        raw_filters = [{"column": "age", "op": "INVALID"}]
        result = json.loads(await tools.select_rows(filters=raw_filters, context=ctx))
        assert "error" in result


class TestAggregate:
    async def test_basic_count(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        result = json.loads(await mcp_tools.aggregate(operation="count", context=ctx))
        assert result["count"] == 1

    async def test_with_group_by(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        await mcp_tools.aggregate(operation="count", group_by="city", context=ctx)
        repo.aggregate.assert_called_once()
        assert repo.aggregate.call_args.kwargs["group_by"] == "city"

    async def test_with_filters(self):
        repo = _make_mock_repository()
        ctx = _make_mock_ctx(repo)
        raw_filters = [{"column": "age", "op": ">=", "value": 18}]
        await tools.aggregate(operation="sum", field="score", filters=raw_filters, context=ctx)
        call_filters = repo.aggregate.call_args.kwargs["filters"]
        assert call_filters[0].op == ">="

    async def test_invalid_op_returns_error(self):
        repo = _make_mock_repository()
        repo.aggregate = AsyncMock(side_effect=ValueError("Unsupported aggregation op"))
        ctx = _make_mock_ctx(repo)
        result = json.loads(await tools.aggregate(operation="median", field="age", context=ctx))
        assert "error" in result
