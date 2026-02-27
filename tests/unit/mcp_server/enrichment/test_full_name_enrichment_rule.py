"""Tests for FullNameEnrichmentRule."""

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.full_name_enrichment_rule import FullNameEnrichmentRule


@pytest.fixture()
def rule():
    return FullNameEnrichmentRule()


def _cols(*names):
    return [ColumnInfo(name=n, detected_type="text", samples=[]) for n in names]


class TestInferDerivedColumns:
    def test_with_first_and_last(self, rule):
        cols = _cols("first_name", "last_name", "email")
        result = rule.infer_derived_columns(cols, [])
        assert len(result) == 1
        assert result[0].name == "full_name"
        assert result[0].detected_type == "text"

    def test_skips_when_full_name_exists(self, rule):
        cols = _cols("first_name", "last_name", "full_name")
        result = rule.infer_derived_columns(cols, [])
        assert result == []

    def test_missing_one_column(self, rule):
        cols = _cols("first_name", "email")
        result = rule.infer_derived_columns(cols, [])
        assert result == []


class TestAddDerivedColumns:
    def test_concatenates(self, rule):
        cols = _cols("first_name", "last_name")
        rule.infer_derived_columns(cols, [])
        rows = [{"first_name": "Alice", "last_name": "Smith"}]
        result = rule.add_derived_columns(rows)
        assert result[0]["full_name"] == "Alice Smith"

    def test_handles_empty_parts(self, rule):
        cols = _cols("first_name", "last_name")
        rule.infer_derived_columns(cols, [])
        rows = [
            {"first_name": "Alice", "last_name": ""},
            {"first_name": "", "last_name": "Smith"},
        ]
        result = rule.add_derived_columns(rows)
        assert result[0]["full_name"] == "Alice"
        assert result[1]["full_name"] == "Smith"
