"""Tests for date_detection shared utility — format detection logic."""

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.date_detection import detect_date_columns


def _cols(*names_types):
    return [ColumnInfo(name=n, detected_type=t, samples=[]) for n, t in names_types]


def _rows(col_name, values):
    return [{col_name: v} for v in values]


class TestDetectDateColumns:
    def test_dd_mm_yyyy(self):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977", "15/06/1990", "03/12/1985"])
        result = detect_date_columns(cols, rows)
        assert len(result) == 1
        assert result[0] == ("dob", "%d/%m/%Y")

    def test_yyyy_mm_dd(self):
        cols = _cols(("joined", "text"))
        rows = _rows("joined", ["1989-07-12", "2001-01-15", "2020-11-30"])
        result = detect_date_columns(cols, rows)
        assert len(result) == 1
        assert result[0] == ("joined", "%Y-%m-%d")

    def test_mm_dd_yyyy_slash(self):
        cols = _cols(("d", "text"))
        rows = _rows("d", ["07/12/1989", "01/15/2001", "11/30/2020"])
        result = detect_date_columns(cols, rows)
        assert len(result) == 1
        assert result[0][1] in ("%d/%m/%Y", "%m/%d/%Y")

    def test_yyyy_slash_mm_slash_dd(self):
        cols = _cols(("d", "text"))
        rows = _rows("d", ["1989/07/12", "2001/01/15", "2020/11/30"])
        result = detect_date_columns(cols, rows)
        assert len(result) == 1
        assert result[0][1] == "%Y/%m/%d"

    def test_skips_numeric_columns(self):
        cols = _cols(("salary", "numeric"))
        rows = _rows("salary", ["50000", "60000", "70000"])
        result = detect_date_columns(cols, rows)
        assert result == []

    def test_below_threshold(self):
        cols = _cols(("mixed", "text"))
        rows = _rows("mixed", ["28/01/1977", "not-a-date", "also-not", "nope", "nah"])
        result = detect_date_columns(cols, rows)
        assert result == []

    def test_no_dates(self):
        cols = _cols(("name", "text"))
        rows = _rows("name", ["Alice", "Bob", "Charlie"])
        result = detect_date_columns(cols, rows)
        assert result == []

    def test_empty_values(self):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["", "", ""])
        result = detect_date_columns(cols, rows)
        assert result == []

    def test_multiple_date_columns(self):
        cols = _cols(("dob", "text"), ("start", "text"), ("name", "text"))
        rows = [
            {"dob": "28/01/1977", "start": "1989-07-12", "name": "Alice"},
            {"dob": "15/06/1990", "start": "2001-01-15", "name": "Bob"},
            {"dob": "03/12/1985", "start": "2020-11-30", "name": "Charlie"},
        ]
        result = detect_date_columns(cols, rows)
        assert len(result) == 2
        col_names = [r[0] for r in result]
        assert "dob" in col_names
        assert "start" in col_names
