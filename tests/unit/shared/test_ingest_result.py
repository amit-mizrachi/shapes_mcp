"""Tests for shared.modules.ingest_result.IngestResult."""

import pytest
from pydantic import ValidationError

from shared.modules.data.ingest_result import IngestResult
from shared.modules.data.column_info import ColumnInfo


class TestIngestResult:
    def test_basic_creation(self):
        cols = [ColumnInfo(name="name", detected_type="text")]
        result = IngestResult(table_name="people", columns=cols)
        assert result.table_name == "people"
        assert len(result.columns) == 1

    def test_frozen(self):
        result = IngestResult(table_name="t", columns=[])
        with pytest.raises(ValidationError):
            result.table_name = "other"

    def test_multiple_columns(self):
        cols = [
            ColumnInfo(name="name", detected_type="text"),
            ColumnInfo(name="age", detected_type="numeric"),
        ]
        result = IngestResult(table_name="data", columns=cols)
        assert len(result.columns) == 2
        assert result.columns[1].detected_type == "numeric"
