"""Tests for mcp-server/src/repository/sqlite/sqlite_repository.py — async queries, validation, SQL safety."""

import sqlite3

import pytest
from pydantic import ValidationError

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.filter_condition import FilterCondition
from repository.sqlite.sqlite_repository import SqliteRepository
from repository.sqlite.sqlite_ingester import SqliteIngester


@pytest.fixture()
def repo_with_data(test_db, sample_csv_path):
    """Ingest sample data and return a SqliteRepository."""
    ingester = SqliteIngester(test_db)
    result = ingester.ingest(str(sample_csv_path))
    repo = SqliteRepository(test_db, result.table_name, result.columns)
    return repo


class TestGetSchema:
    async def test_returns_schema(self, repo_with_data):
        schema = await repo_with_data.get_schema()
        assert schema is not None
        assert schema.table_name == "sample_data"
        assert len(schema.columns) == 5

    async def test_returns_none_when_no_columns(self, test_db):
        repo = SqliteRepository(test_db, "empty", [])
        schema = await repo.get_schema()
        assert schema is None

    async def test_schema_column_names(self, repo_with_data):
        schema = await repo_with_data.get_schema()
        names = [c.name for c in schema.columns]
        assert "name" in names
        assert "age" in names
        assert "score" in names


class TestSelectRows:
    async def test_select_all(self, repo_with_data):
        result = await repo_with_data.select_rows()
        assert result.count == 5
        assert len(result.rows) == 5

    async def test_select_with_limit(self, repo_with_data):
        result = await repo_with_data.select_rows(limit=2)
        assert result.count == 2

    async def test_select_specific_fields(self, repo_with_data):
        result = await repo_with_data.select_rows(fields=["name", "age"])
        assert set(result.columns) == {"name", "age"}
        assert "city" not in result.rows[0]

    async def test_select_with_equality_filter(self, repo_with_data):
        filters = [FilterCondition(column="name", op="=", value="Alice")]
        result = await repo_with_data.select_rows(filters=filters)
        assert result.count == 1
        assert result.rows[0]["name"] == "Alice"

    async def test_select_with_gt_filter(self, repo_with_data):
        filters = [FilterCondition(column="age", op=">", value=30)]
        result = await repo_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) > 30

    async def test_select_with_gte_filter(self, repo_with_data):
        filters = [FilterCondition(column="age", op=">=", value=35)]
        result = await repo_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) >= 35

    async def test_select_with_lt_filter(self, repo_with_data):
        filters = [FilterCondition(column="score", op="<", value=80)]
        result = await repo_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["score"]) < 80

    async def test_select_with_multiple_filters(self, repo_with_data):
        filters = [
            FilterCondition(column="age", op=">", value=25),
            FilterCondition(column="score", op=">=", value=90),
        ]
        result = await repo_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) > 25
            assert float(row["score"]) >= 90

    async def test_select_invalid_field_raises(self, repo_with_data):
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.select_rows(fields=["nonexistent"])

    async def test_select_invalid_filter_column_raises(self, repo_with_data):
        filters = [FilterCondition(column="bad_col", op="=", value="x")]
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.select_rows(filters=filters)

    async def test_select_invalid_filter_op_raises(self, repo_with_data):
        with pytest.raises(ValidationError, match="Invalid filter operator"):
            FilterCondition(column="name", op="!=", value="Alice")

    async def test_select_no_filters_returns_all(self, repo_with_data):
        result = await repo_with_data.select_rows(filters=None)
        assert result.count == 5

    async def test_select_empty_result(self, repo_with_data):
        filters = [FilterCondition(column="name", op="=", value="Nobody")]
        result = await repo_with_data.select_rows(filters=filters)
        assert result.count == 0
        assert result.rows == []


class TestAggregate:
    async def test_count_all(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="count")
        assert result.rows[0]["result"] == 5

    async def test_count_case_insensitive(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="COUNT")
        assert result.rows[0]["result"] == 5

    async def test_sum(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="sum", field="age")
        total = result.rows[0]["result"]
        assert total == pytest.approx(160.0)  # 30+25+35+28+42

    async def test_avg(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="avg", field="age")
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(32.0)  # 160/5

    async def test_min(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="min", field="score")
        assert result.rows[0]["result"] == pytest.approx(76.9)

    async def test_max(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="max", field="score")
        assert result.rows[0]["result"] == pytest.approx(95.5)

    async def test_group_by(self, repo_with_data):
        result = await repo_with_data.aggregate(operation="count", group_by="active")
        assert result.count >= 1
        groups = {str(r["active"]): r["result"] for r in result.rows}
        assert groups.get("true", 0) + groups.get("false", 0) == 5

    async def test_aggregate_with_filter(self, repo_with_data):
        filters = [FilterCondition(column="active", op="=", value="true")]
        result = await repo_with_data.aggregate(operation="count", filters=filters)
        assert result.rows[0]["result"] == 3

    async def test_invalid_operation_raises(self, repo_with_data):
        with pytest.raises(ValueError, match="Unsupported aggregation"):
            await repo_with_data.aggregate(operation="MEDIAN", field="age")

    async def test_missing_field_for_sum_raises(self, repo_with_data):
        with pytest.raises(ValueError, match="field.*required"):
            await repo_with_data.aggregate(operation="sum")

    async def test_invalid_field_raises(self, repo_with_data):
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.aggregate(operation="sum", field="nonexistent")

    async def test_invalid_group_by_raises(self, repo_with_data):
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.aggregate(operation="count", group_by="nonexistent")


class TestSQLSafety:
    async def test_sql_injection_in_filter_column(self, repo_with_data):
        """Column name injection is blocked by validation against known columns."""
        filters = [FilterCondition(column='"; DROP TABLE sample_data; --', op="=", value="x")]
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.select_rows(filters=filters)

    async def test_sql_injection_in_filter_op(self, repo_with_data):
        """Operator injection is blocked by allowlist."""
        with pytest.raises(ValidationError, match="Invalid filter operator"):
            FilterCondition(column="name", op="= 1; DROP TABLE sample_data; --", value="x")

    async def test_sql_injection_in_field_name(self, repo_with_data):
        with pytest.raises(ValueError, match="not found"):
            await repo_with_data.select_rows(fields=['"; DROP TABLE sample_data; --'])
