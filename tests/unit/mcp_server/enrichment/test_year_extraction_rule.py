"""Tests for YearExtractionRule — year extraction from date columns."""

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.year_extraction_rule import YearExtractionRule


def _cols(*names_types):
    return [ColumnInfo(name=n, detected_type=t, samples=[]) for n, t in names_types]


def _rows(col_name, values):
    return [{col_name: v} for v in values]


@pytest.fixture()
def rule():
    return YearExtractionRule()


class TestInferDerivedColumns:
    def test_adds_year_column(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977", "15/06/1990", "03/12/1985"])
        result = rule.infer_derived_columns(cols, rows)
        assert len(result) == 1
        assert result[0].name == "dob_year"
        assert result[0].detected_type == "numeric"

    def test_skips_non_date(self, rule):
        cols = _cols(("name", "text"))
        rows = _rows("name", ["Alice", "Bob", "Charlie"])
        result = rule.infer_derived_columns(cols, rows)
        assert result == []

    def test_skips_conflict(self, rule):
        cols = _cols(("dob", "text"), ("dob_year", "numeric"))
        rows = [{"dob": "28/01/1977", "dob_year": 1977}] * 3
        result = rule.infer_derived_columns(cols, rows)
        names = [c.name for c in result]
        assert "dob_year" not in names


class TestAddDerivedColumns:
    def test_extracts_year(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_year"] == 1977

    def test_various_years(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["15/06/1990", "03/12/2005"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_year"] == 1990
        assert result[1]["dob_year"] == 2005

    def test_handles_empty(self, rule):
        cols = _cols(("dob", "text"))
        rows = [{"dob": "28/01/1977"}, {"dob": ""}]
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[1]["dob_year"] is None

    def test_handles_unparseable(self, rule):
        cols = _cols(("dob", "text"))
        rows = [
            {"dob": "28/01/1977"}, {"dob": "15/06/1990"}, {"dob": "03/12/1985"},
            {"dob": "01/01/2000"}, {"dob": "bad"},
        ]
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[4]["dob_year"] is None
