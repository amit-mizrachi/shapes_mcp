"""Tests for NominalDateRule — days-since-epoch computation."""

from datetime import date
from unittest.mock import patch

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.nominal_date_rule import NominalDateRule


def _cols(*names_types):
    return [ColumnInfo(name=n, detected_type=t, samples=[]) for n, t in names_types]


def _rows(col_name, values):
    return [{col_name: v} for v in values]


@pytest.fixture()
def rule():
    return NominalDateRule()


class TestInferDerivedColumns:
    def test_adds_days_column(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977", "15/06/1990", "03/12/1985"])
        result = rule.infer_derived_columns(cols, rows)
        assert len(result) == 1
        assert result[0].name == "dob_days"
        assert result[0].detected_type == "numeric"

    def test_multiple_date_columns(self, rule):
        cols = _cols(("dob", "text"), ("start", "text"))
        rows = [
            {"dob": "28/01/1977", "start": "01/06/2023"},
            {"dob": "15/06/1990", "start": "15/03/2022"},
            {"dob": "03/12/1985", "start": "28/11/2021"},
        ]
        result = rule.infer_derived_columns(cols, rows)
        assert len(result) == 2
        names = [c.name for c in result]
        assert "dob_days" in names
        assert "start_days" in names

    def test_skips_non_date(self, rule):
        cols = _cols(("name", "text"))
        rows = _rows("name", ["Alice", "Bob", "Charlie"])
        result = rule.infer_derived_columns(cols, rows)
        assert result == []

    def test_skips_conflict(self, rule):
        cols = _cols(("dob", "text"), ("dob_days", "numeric"))
        rows = [{"dob": "28/01/1977", "dob_days": 999}] * 3
        result = rule.infer_derived_columns(cols, rows)
        names = [c.name for c in result]
        assert "dob_days" not in names


class TestAddDerivedColumns:
    def test_computes_days_since_epoch(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["01/01/1970"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_days"] == 0

    def test_known_date(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["02/01/1970"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_days"] == 1

    def test_date_before_epoch(self, rule):
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["31/12/1969"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_days"] == -1

    def test_handles_empty_values(self, rule):
        cols = _cols(("dob", "text"))
        rows = [{"dob": "28/01/1977"}, {"dob": ""}, {"dob": "15/06/1990"}]
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[1]["dob_days"] is None

    def test_handles_unparseable(self, rule):
        cols = _cols(("dob", "text"))
        rows = [
            {"dob": "28/01/1977"}, {"dob": "15/06/1990"}, {"dob": "03/12/1985"},
            {"dob": "01/01/2000"}, {"dob": "not-a-date"},
        ]
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[4]["dob_days"] is None

    def test_custom_epoch(self):
        with patch("enrichment.rules.nominal_date_rule.Config") as mock_cfg:
            mock_cfg.get.return_value = "2000-01-01"
            rule = NominalDateRule()
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["02/01/2000"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        assert result[0]["dob_days"] == 1

    def test_realistic_date(self, rule):
        # 28/01/1977 = Jan 28 1977, epoch = 1970-01-01
        # Expected: (date(1977,1,28) - date(1970,1,1)).days = 2583
        cols = _cols(("dob", "text"))
        rows = _rows("dob", ["28/01/1977"])
        rule.infer_derived_columns(cols, rows)
        result = rule.add_derived_columns(rows)
        expected = (date(1977, 1, 28) - date(1970, 1, 1)).days
        assert result[0]["dob_days"] == expected
