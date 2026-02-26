"""Tests for shared.modules.table_schema.TableSchema."""

import pytest
from pydantic import ValidationError

from shared.modules.data.table_schema import TableSchema
from shared.modules.data.column_info import ColumnInfo


class TestTableSchema:
    def test_basic_creation(self):
        cols = [ColumnInfo(name="id", detected_type="numeric")]
        schema = TableSchema(table_name="users", columns=cols)
        assert schema.table_name == "users"
        assert len(schema.columns) == 1

    def test_frozen(self):
        schema = TableSchema(table_name="t", columns=[])
        with pytest.raises(ValidationError):
            schema.table_name = "other"

    def test_column_access(self):
        cols = [
            ColumnInfo(name="name", detected_type="text"),
            ColumnInfo(name="age", detected_type="numeric"),
        ]
        schema = TableSchema(table_name="people", columns=cols)
        assert schema.columns[0].name == "name"
        assert schema.columns[1].detected_type == "numeric"
