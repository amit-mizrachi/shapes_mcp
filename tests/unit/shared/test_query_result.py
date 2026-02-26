"""Tests for shared.modules.query_result.QueryResult."""

import pytest

from shared.modules.query_result import QueryResult


class TestQueryResult:
    def test_basic_creation(self):
        qr = QueryResult(columns=["a", "b"], rows=[{"a": 1, "b": 2}], count=1)
        assert qr.columns == ["a", "b"]
        assert qr.count == 1

    def test_empty_result(self):
        qr = QueryResult(columns=["a"], rows=[], count=0)
        assert qr.rows == []
        assert qr.count == 0

    def test_frozen(self):
        qr = QueryResult(columns=[], rows=[], count=0)
        with pytest.raises(AttributeError):
            qr.count = 5

    def test_multiple_rows(self):
        rows = [{"x": i} for i in range(3)]
        qr = QueryResult(columns=["x"], rows=rows, count=3)
        assert len(qr.rows) == 3
        assert qr.rows[2]["x"] == 2
