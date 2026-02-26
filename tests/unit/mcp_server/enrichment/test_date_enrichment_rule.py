"""Tests for DateEnrichmentRule — date detection, years_ago/year/month computation."""

from datetime import date
from unittest.mock import patch

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.date_enrichment_rule import DateEnrichmentRule


@pytest.fixture()
def rule():
    return DateEnrichmentRule()


def _cols(*names_types):
    return [ColumnInfo(name=n, detected_type=t, samples=[]) for n, t in names_types]


def _rows(col_name, values):
    return [{col_name: v} for v in values]


class TestDetect:
    def test_detect_dd_mm_yyyy(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977", "15/06/1990", "03/12/1985"])
        result = rule.detect(cols, rows)
        assert len(result) == 3
        assert result[0].name == "dob_years_ago"

    def test_detect_yyyy_mm_dd(self, rule):
        cols = _cols(("joined", "text"))
        rows = _rows("joined", ["1989-07-12", "2001-01-15", "2020-11-30"])
        result = rule.detect(cols, rows)
        assert len(result) == 3
        assert result[0].name == "joined_years_ago"

    def test_detect_skips_numeric_columns(self, rule):
        cols = _cols(("salary", "numeric"))
        rows = _rows("salary", ["50000", "60000", "70000"])
        result = rule.detect(cols, rows)
        assert result == []

    def test_detect_below_threshold(self, rule):
        cols = _cols(("mixed", "text"))
        rows = _rows("mixed", ["28/01/1977", "not-a-date", "also-not", "nope", "nah"])
        result = rule.detect(cols, rows)
        assert result == []

    def test_detect_no_dates(self, rule):
        cols = _cols(("name", "text"))
        rows = _rows("name", ["Alice", "Bob", "Charlie"])
        result = rule.detect(cols, rows)
        assert result == []

    def test_detect_returns_three_columns_per_date(self, rule):
        cols = _cols(("start_date", "text"))
        rows = _rows("start_date", ["01/06/2023", "15/03/2022", "28/11/2021"])
        result = rule.detect(cols, rows)
        assert len(result) == 3
        names = [c.name for c in result]
        assert names == ["start_date_years_ago", "start_date_year", "start_date_month"]
        assert all(c.detected_type == "numeric" for c in result)

    def test_detect_multiple_date_columns(self, rule):
        cols = _cols(("dob", "text"), ("start", "text"), ("name", "text"))
        rows = [
            {"dob": "28/01/1977", "start": "01/06/2023", "name": "Alice"},
            {"dob": "15/06/1990", "start": "15/03/2022", "name": "Bob"},
            {"dob": "03/12/1985", "start": "28/11/2021", "name": "Charlie"},
        ]
        result = rule.detect(cols, rows)
        assert len(result) == 6
        names = [c.name for c in result]
        assert "dob_years_ago" in names
        assert "start_years_ago" in names

    def test_detect_empty_values_skipped(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["", "", ""])
        result = rule.detect(cols, rows)
        assert result == []

    def test_detect_skips_conflict(self, rule):
        cols = _cols(("dob", "text"), ("dob_years_ago", "numeric"))
        rows = _rows("dob", ["28/01/1977", "15/06/1990", "03/12/1985"])
        for r in rows:
            r["dob_years_ago"] = 40
        result = rule.detect(cols, rows)
        names = [c.name for c in result]
        assert "dob_years_ago" not in names
        assert "dob_year" in names
        assert "dob_month" in names


class TestApply:
    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_computes_years_ago(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977"])
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[0]["dob_years_ago"] == 49

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_extracts_year(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977"])
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[0]["dob_year"] == 1977

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_extracts_month(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977"])
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[0]["dob_month"] == 1

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_handles_empty_values(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        rows = [{"dob": "28/01/1977"}, {"dob": ""}, {"dob": "15/06/1990"}]
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[1]["dob_years_ago"] is None
        assert result[1]["dob_year"] is None
        assert result[1]["dob_month"] is None

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_handles_unparseable(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        # Enough valid dates for detection to pass (80% threshold)
        rows = [
            {"dob": "28/01/1977"}, {"dob": "15/06/1990"}, {"dob": "03/12/1985"},
            {"dob": "01/01/2000"}, {"dob": "not-a-date"},
        ]
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[4]["dob_years_ago"] is None
        assert result[4]["dob_year"] is None
        assert result[4]["dob_month"] is None

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_apply_birthday_not_yet(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["31/12/2000"])
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert result[0]["dob_years_ago"] == 25  # not 26, birthday hasn't happened

    @patch("enrichment.rules.date_enrichment_rule.date")
    def test_derived_column_naming(self, mock_date, rule):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        cols = _cols(("start_date", "text"))
        rows = _rows("start_date", ["01/06/2023"])
        rule.detect(cols, rows)
        result = rule.apply(rows)
        assert "start_date_years_ago" in result[0]
        assert "start_date_year" in result[0]
        assert "start_date_month" in result[0]
