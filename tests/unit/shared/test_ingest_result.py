"""Tests for shared.modules.ingest_result.IngestResult."""

import pytest

from shared.modules.ingest_result import IngestResult
from shared.modules.column_info import ColumnInfo


class TestIngestResult:
    def test_basic_creation(self):
        cols = [ColumnInfo(name="name", detected_type="text")]
        result = IngestResult(table_name="people", columns=cols)
        assert result.table_name == "people"
        assert len(result.columns) == 1

    def test_frozen(self):
        result = IngestResult(table_name="t", columns=[])
        with pytest.raises(AttributeError):
            result.table_name = "other"

    def test_multiple_columns(self):
        cols = [
            ColumnInfo(name="name", detected_type="text"),
            ColumnInfo(name="age", detected_type="numeric"),
        ]
        result = IngestResult(table_name="data", columns=cols)
        assert len(result.columns) == 2
        assert result.columns[1].detected_type == "numeric"
