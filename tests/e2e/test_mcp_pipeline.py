"""E2E: CSV → SQLite → DataStore → Tools (real, no mocks)."""

import json
from unittest.mock import MagicMock

import pytest

from data_store.csv_parser import CSVParser
from data_store.sqlite.sqlite_ingester import SqliteIngester
from data_store.sqlite.sqlite_data_store import SqliteDataStore
from shared.modules.data.filter_condition import FilterCondition
import tool_handlers


@pytest.fixture()
def real_pipeline(sample_csv_path, tmp_path):
    """Full real pipeline: parse CSV, ingest to SQLite file, create data store."""
    db_path = str(tmp_path / "e2e.db")

    ingester = SqliteIngester(db_path)
    table_schema = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
    store = SqliteDataStore(db_path, table_schema)

    yield store, table_schema


@pytest.fixture()
def real_ctx(real_pipeline):
    """Create a mock MCP Context pointing to the real data store."""
    store, _ = real_pipeline
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"data_store": store}
    return ctx


@pytest.mark.e2e
class TestMCPPipelineE2E:
    async def test_full_ingest_and_schema(self, real_pipeline):
        store,result = real_pipeline
        assert result.table_name == "sample_data"
        assert len(result.columns) == 5

        schema = await store.get_schema()
        assert schema.table_name == "sample_data"
        col_names = [c.name for c in schema.columns]
        assert "name" in col_names
        assert "age" in col_names

    async def test_select_all_rows(self, real_pipeline):
        store,_ = real_pipeline
        result = await store.select_rows()
        assert result.count == 5
        names = {r["name"] for r in result.rows}
        assert names == {"Alice", "Bob", "Charlie", "Diana", "Eve"}

    async def test_select_with_filter(self, real_pipeline):
        store,_ = real_pipeline
        filters = [FilterCondition(column="city", operator="=", value="London")]
        result = await store.select_rows(filters=filters)
        assert result.count == 1
        assert result.rows[0]["name"] == "Bob"

    async def test_select_with_numeric_filter(self, real_pipeline):
        store,_ = real_pipeline
        filters = [FilterCondition(column="age", operator=">", value=30)]
        result = await store.select_rows(filters=filters)
        names = {r["name"] for r in result.rows}
        assert "Charlie" in names
        assert "Eve" in names
        assert "Alice" not in names

    async def test_aggregate_count(self, real_pipeline):
        store,_ = real_pipeline
        result = await store.aggregate(operation="count")
        assert result.rows[0]["result"] == 5

    async def test_aggregate_avg(self, real_pipeline):
        store,_ = real_pipeline
        result = await store.aggregate(operation="avg", field="score")
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(87.96, abs=0.01)

    async def test_aggregate_group_by(self, real_pipeline):
        store,_ = real_pipeline
        result = await store.aggregate(operation="count", group_by="active")
        groups = {str(r["active"]): r["result"] for r in result.rows}
        assert groups["true"] == 3
        assert groups["false"] == 2

    async def test_aggregate_with_filter(self, real_pipeline):
        store,_ = real_pipeline
        filters = [FilterCondition(column="active", operator="=", value="true")]
        result = await store.aggregate(operation="avg", field="score", filters=filters)
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(91.97, abs=0.01)  # (95.5+92.3+88.1)/3


@pytest.mark.e2e
class TestToolsE2E:
    async def test_get_schema_tool(self, real_ctx):
        result = json.loads(await tool_handlers.get_schema(real_ctx))
        assert result["table"] == "sample_data"
        assert len(result["columns"]) == 5

    async def test_select_rows_tool(self, real_ctx):
        result = json.loads(await tool_handlers.select_rows(context=real_ctx))
        assert result["count"] == 5

    async def test_select_rows_with_filters(self, real_ctx):
        filters = [FilterCondition(column="name", operator="=", value="Alice")]
        result = json.loads(await tool_handlers.select_rows(filters=filters, context=real_ctx))
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Alice"

    async def test_select_rows_with_fields(self, real_ctx):
        result = json.loads(await tool_handlers.select_rows(fields=["name", "city"], context=real_ctx))
        row = result["data"][0]
        assert "name" in row
        assert "city" in row

    async def test_aggregate_tool(self, real_ctx):
        result = json.loads(await tool_handlers.aggregate(operation="count", context=real_ctx))
        assert result["data"][0]["result"] == 5

    async def test_aggregate_with_group_by(self, real_ctx):
        result = json.loads(await tool_handlers.aggregate(operation="count", group_by="active", context=real_ctx))
        assert result["count"] >= 2

    async def test_invalid_filter_returns_error(self, real_ctx):
        filters = [FilterCondition(column="bad_col", operator="=", value="x")]
        result = json.loads(await tool_handlers.select_rows(filters=filters, context=real_ctx))
        assert "error" in result

    async def test_invalid_aggregate_returns_error(self, real_ctx):
        result = json.loads(await tool_handlers.aggregate(operation="median", field="age", context=real_ctx))
        assert "error" in result
