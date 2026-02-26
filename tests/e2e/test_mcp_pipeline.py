"""E2E: CSV → SQLite → Repository → Tools (real, no mocks)."""

import json
import sqlite3
import uuid
from unittest.mock import MagicMock

import pytest

from repository.csv_parser import CSVParser
from repository.sqlite.sqlite_ingester import SqliteIngester
from repository.sqlite.sqlite_repository import SqliteRepository
from shared.modules.filter_condition import FilterCondition
import tools


@pytest.fixture()
def real_pipeline(sample_csv_path):
    """Full real pipeline: parse CSV, ingest to SQLite, create repository."""
    db_name = f"e2e_{uuid.uuid4().hex[:8]}"
    db_uri = f"file:{db_name}?mode=memory&cache=shared"
    keeper = sqlite3.connect(db_uri, uri=True)

    ingester = SqliteIngester(db_uri)
    result = ingester.ingest(str(sample_csv_path))
    repo = SqliteRepository(db_uri, result.table_name, result.columns)

    yield repo, result

    keeper.close()


@pytest.fixture()
def real_ctx(real_pipeline):
    """Create a mock MCP Context pointing to the real repository."""
    repo, _ = real_pipeline
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"repository": repo}
    return ctx


@pytest.mark.e2e
class TestMCPPipelineE2E:
    async def test_full_ingest_and_schema(self, real_pipeline):
        repo, result = real_pipeline
        assert result.table_name == "sample_data"
        assert len(result.columns) == 5

        schema = await repo.get_schema()
        assert schema.table_name == "sample_data"
        col_names = [c.name for c in schema.columns]
        assert "name" in col_names
        assert "age" in col_names

    async def test_select_all_rows(self, real_pipeline):
        repo, _ = real_pipeline
        result = await repo.select_rows()
        assert result.count == 5
        names = {r["name"] for r in result.rows}
        assert names == {"Alice", "Bob", "Charlie", "Diana", "Eve"}

    async def test_select_with_filter(self, real_pipeline):
        repo, _ = real_pipeline
        filters = [FilterCondition(column="city", op="=", value="London")]
        result = await repo.select_rows(filters=filters)
        assert result.count == 1
        assert result.rows[0]["name"] == "Bob"

    async def test_select_with_numeric_filter(self, real_pipeline):
        repo, _ = real_pipeline
        filters = [FilterCondition(column="age", op=">", value=30)]
        result = await repo.select_rows(filters=filters)
        names = {r["name"] for r in result.rows}
        assert "Charlie" in names
        assert "Eve" in names
        assert "Alice" not in names

    async def test_aggregate_count(self, real_pipeline):
        repo, _ = real_pipeline
        result = await repo.aggregate(operation="count")
        assert result.rows[0]["result"] == 5

    async def test_aggregate_avg(self, real_pipeline):
        repo, _ = real_pipeline
        result = await repo.aggregate(operation="avg", field="score")
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(87.96, abs=0.01)

    async def test_aggregate_group_by(self, real_pipeline):
        repo, _ = real_pipeline
        result = await repo.aggregate(operation="count", group_by="active")
        groups = {str(r["active"]): r["result"] for r in result.rows}
        assert groups["true"] == 3
        assert groups["false"] == 2

    async def test_aggregate_with_filter(self, real_pipeline):
        repo, _ = real_pipeline
        filters = [FilterCondition(column="active", op="=", value="true")]
        result = await repo.aggregate(operation="avg", field="score", filters=filters)
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(91.97, abs=0.01)  # (95.5+92.3+88.1)/3


@pytest.mark.e2e
class TestToolsE2E:
    async def test_get_schema_tool(self, real_ctx):
        result = json.loads(await tools.get_schema(real_ctx))
        assert result["table"] == "sample_data"
        assert len(result["columns"]) == 5

    async def test_select_rows_tool(self, real_ctx):
        result = json.loads(await tools.select_rows(ctx=real_ctx))
        assert result["count"] == 5

    async def test_select_rows_with_filters(self, real_ctx):
        filters = [{"column": "name", "op": "=", "value": "Alice"}]
        result = json.loads(await tools.select_rows(filters=filters, ctx=real_ctx))
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Alice"

    async def test_select_rows_with_fields(self, real_ctx):
        result = json.loads(await tools.select_rows(fields=["name", "city"], ctx=real_ctx))
        row = result["data"][0]
        assert "name" in row
        assert "city" in row

    async def test_aggregate_tool(self, real_ctx):
        result = json.loads(await tools.aggregate(op="count", ctx=real_ctx))
        assert result["data"][0]["result"] == 5

    async def test_aggregate_with_group_by(self, real_ctx):
        result = json.loads(await tools.aggregate(op="count", group_by="active", ctx=real_ctx))
        assert result["count"] >= 2

    async def test_invalid_filter_returns_error(self, real_ctx):
        filters = [{"column": "bad_col", "op": "=", "value": "x"}]
        result = json.loads(await tools.select_rows(filters=filters, ctx=real_ctx))
        assert "error" in result

    async def test_invalid_aggregate_returns_error(self, real_ctx):
        result = json.loads(await tools.aggregate(op="median", field="age", ctx=real_ctx))
        assert "error" in result
