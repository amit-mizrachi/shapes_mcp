"""Tests for mcp-server/src/data_store/sqlite_data_store.py — async queries, validation, SQL safety."""

import sqlite3

import pytest
from pydantic import ValidationError

from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.table_schema import TableSchema
from data_store.csv_parser import CSVParser
from data_store.sqlite_data_store import SqliteDataStore
from data_store.sqlite_ingester import SqliteIngester


@pytest.fixture()
def data_store_with_data(test_db, sample_csv_path):
    """Ingest sample data and return a SqliteDataStore."""
    ingester = SqliteIngester(test_db)
    table_schema = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
    return SqliteDataStore(test_db, table_schema)


class TestGetSchema:
    async def test_returns_schema(self, data_store_with_data):
        schema = await data_store_with_data.get_schema()
        assert schema is not None
        assert schema.table_name == "sample_data"
        assert len(schema.columns) == 5

    async def test_returns_none_when_no_columns(self, test_db):
        store = SqliteDataStore(test_db, TableSchema(table_name="empty", columns=[]))
        schema = await store.get_schema()
        assert schema is None

    async def test_schema_column_names(self, data_store_with_data):
        schema = await data_store_with_data.get_schema()
        names = [c.name for c in schema.columns]
        assert "name" in names
        assert "age" in names
        assert "score" in names


class TestSelectRows:
    async def test_select_all(self, data_store_with_data):
        result = await data_store_with_data.select_rows()
        assert result.count == 5
        assert len(result.rows) == 5

    async def test_select_with_limit(self, data_store_with_data):
        result = await data_store_with_data.select_rows(limit=2)
        assert result.count == 2

    async def test_select_specific_fields(self, data_store_with_data):
        result = await data_store_with_data.select_rows(fields=["name", "age"])
        assert set(result.columns) == {"name", "age"}
        assert "city" not in result.rows[0]

    async def test_select_with_equality_filter(self, data_store_with_data):
        filters = [FilterCondition(column="name", operator="=", value="Alice")]
        result = await data_store_with_data.select_rows(filters=filters)
        assert result.count == 1
        assert result.rows[0]["name"] == "Alice"

    async def test_select_with_gt_filter(self, data_store_with_data):
        filters = [FilterCondition(column="age", operator=">", value=30)]
        result = await data_store_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) > 30

    async def test_select_with_gte_filter(self, data_store_with_data):
        filters = [FilterCondition(column="age", operator=">=", value=35)]
        result = await data_store_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) >= 35

    async def test_select_with_lt_filter(self, data_store_with_data):
        filters = [FilterCondition(column="score", operator="<", value=80)]
        result = await data_store_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["score"]) < 80

    async def test_select_with_multiple_filters(self, data_store_with_data):
        filters = [
            FilterCondition(column="age", operator=">", value=25),
            FilterCondition(column="score", operator=">=", value=90),
        ]
        result = await data_store_with_data.select_rows(filters=filters)
        for row in result.rows:
            assert float(row["age"]) > 25
            assert float(row["score"]) >= 90

    async def test_select_invalid_field_raises(self, data_store_with_data):
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.select_rows(fields=["nonexistent"])

    async def test_select_invalid_filter_column_raises(self, data_store_with_data):
        filters = [FilterCondition(column="bad_col", operator="=", value="x")]
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.select_rows(filters=filters)

    async def test_select_invalid_filter_op_raises(self, data_store_with_data):
        with pytest.raises(ValidationError, match="Invalid filter operator"):
            FilterCondition(column="name", operator="!=", value="Alice")

    async def test_select_no_filters_returns_all(self, data_store_with_data):
        result = await data_store_with_data.select_rows(filters=None)
        assert result.count == 5

    async def test_select_empty_result(self, data_store_with_data):
        filters = [FilterCondition(column="name", operator="=", value="Nobody")]
        result = await data_store_with_data.select_rows(filters=filters)
        assert result.count == 0
        assert result.rows == []


class TestAggregate:
    async def test_count_all(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="count")
        assert result.rows[0]["result"] == 5

    async def test_count_case_insensitive(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="COUNT")
        assert result.rows[0]["result"] == 5

    async def test_sum(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="sum", field="age")
        total = result.rows[0]["result"]
        assert total == pytest.approx(160.0)  # 30+25+35+28+42

    async def test_avg(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="avg", field="age")
        avg = result.rows[0]["result"]
        assert avg == pytest.approx(32.0)  # 160/5

    async def test_min(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="min", field="score")
        assert result.rows[0]["result"] == pytest.approx(76.9)

    async def test_max(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="max", field="score")
        assert result.rows[0]["result"] == pytest.approx(95.5)

    async def test_group_by(self, data_store_with_data):
        result = await data_store_with_data.aggregate(operation="count", group_by="active")
        assert result.count >= 1
        groups = {str(r["active"]): r["result"] for r in result.rows}
        assert groups.get("true", 0) + groups.get("false", 0) == 5

    async def test_aggregate_with_filter(self, data_store_with_data):
        filters = [FilterCondition(column="active", operator="=", value="true")]
        result = await data_store_with_data.aggregate(operation="count", filters=filters)
        assert result.rows[0]["result"] == 3

    async def test_invalid_operation_raises(self, data_store_with_data):
        with pytest.raises(ValueError, match="Unsupported aggregation"):
            await data_store_with_data.aggregate(operation="MEDIAN", field="age")

    async def test_missing_field_for_sum_raises(self, data_store_with_data):
        with pytest.raises(ValueError, match="field.*required"):
            await data_store_with_data.aggregate(operation="sum")

    async def test_invalid_field_raises(self, data_store_with_data):
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.aggregate(operation="sum", field="nonexistent")

    async def test_invalid_group_by_raises(self, data_store_with_data):
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.aggregate(operation="count", group_by="nonexistent")


class TestSQLSafety:
    async def test_sql_injection_in_filter_column(self, data_store_with_data):
        """Column name injection is blocked by validation against known columns."""
        filters = [FilterCondition(column='"; DROP TABLE sample_data; --', operator="=", value="x")]
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.select_rows(filters=filters)

    async def test_sql_injection_in_filter_op(self, data_store_with_data):
        """Operator injection is blocked by allowlist."""
        with pytest.raises(ValidationError, match="Invalid filter operator"):
            FilterCondition(column="name", operator="= 1; DROP TABLE sample_data; --", value="x")

    async def test_sql_injection_in_field_name(self, data_store_with_data):
        with pytest.raises(ValueError, match="not found"):
            await data_store_with_data.select_rows(fields=['"; DROP TABLE sample_data; --'])
