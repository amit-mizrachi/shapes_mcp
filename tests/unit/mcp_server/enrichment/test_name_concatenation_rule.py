"""Tests for NameConcatenationRule."""

import pytest

from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.name_concatenation_rule import NameConcatenationRule


@pytest.fixture()
def rule():
    return NameConcatenationRule()


def _cols(*names):
    return [ColumnInfo(name=n, detected_type="text", samples=[]) for n in names]


class TestDetect:
    def test_detect_with_first_and_last(self, rule):
        cols = _cols("first_name", "last_name", "email")
        result = rule.detect(cols, [])
        assert len(result) == 1
        assert result[0].name == "full_name"
        assert result[0].detected_type == "text"

    def test_detect_skips_when_full_name_exists(self, rule):
        cols = _cols("first_name", "last_name", "full_name")
        result = rule.detect(cols, [])
        assert result == []

    def test_detect_missing_one_column(self, rule):
        cols = _cols("first_name", "email")
        result = rule.detect(cols, [])
        assert result == []


class TestApply:
    def test_apply_concatenates(self, rule):
        cols = _cols("first_name", "last_name")
        rule.detect(cols, [])
        rows = [{"first_name": "Alice", "last_name": "Smith"}]
        result = rule.apply(rows)
        assert result[0]["full_name"] == "Alice Smith"

    def test_apply_handles_empty_parts(self, rule):
        cols = _cols("first_name", "last_name")
        rule.detect(cols, [])
        rows = [
            {"first_name": "Alice", "last_name": ""},
            {"first_name": "", "last_name": "Smith"},
        ]
        result = rule.apply(rows)
        assert result[0]["full_name"] == "Alice"
        assert result[1]["full_name"] == "Smith"
