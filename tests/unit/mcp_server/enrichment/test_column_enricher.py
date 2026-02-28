"""Tests for ColumnEnricher orchestrator."""

import copy
from datetime import date

import pytest

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV
from enrichment.column_enricher import ColumnEnricher
from enrichment.rules.nominal_date_rule import NominalDateRule
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from enrichment.rules.year_extraction_rule import YearExtractionRule


def _make_parsed_csv(columns, rows, table_name="test_table"):
    cols = [ColumnInfo(name=n, detected_type=t, samples=[]) for n, t in columns]
    return ParsedCSV(table_name=table_name, columns=cols, rows=rows)


def _all_rules():
    return [NominalDateRule(), MonthExtractionRule(), YearExtractionRule()]


class TestEnrich:
    def test_enrich_adds_columns(self):
        parsed = _make_parsed_csv(
            columns=[("dob", "text"), ("name", "text")],
            rows=[
                {"dob": "28/01/1977", "name": "Alice"},
                {"dob": "15/06/1990", "name": "Bob"},
                {"dob": "03/12/1985", "name": "Charlie"},
            ],
        )
        enricher = ColumnEnricher(rules=_all_rules())
        result = enricher.enrich(parsed)

        col_names = [c.name for c in result.columns]
        assert "dob_days" in col_names
        assert "dob_year" in col_names
        assert "dob_month" in col_names
        assert len(result.columns) == 5  # 2 original + 3 derived

    def test_enrich_no_applicable_rules(self):
        parsed = _make_parsed_csv(
            columns=[("name", "text"), ("score", "numeric")],
            rows=[{"name": "Alice", "score": "95"}, {"name": "Bob", "score": "87"}],
        )
        enricher = ColumnEnricher(rules=_all_rules())
        result = enricher.enrich(parsed)

        assert result is parsed  # exact same object, no copy

    def test_enrich_preserves_original_columns(self):
        parsed = _make_parsed_csv(
            columns=[("dob", "text"), ("city", "text")],
            rows=[
                {"dob": "28/01/1977", "city": "NYC"},
                {"dob": "15/06/1990", "city": "London"},
                {"dob": "03/12/1985", "city": "Paris"},
            ],
        )
        enricher = ColumnEnricher(rules=_all_rules())
        result = enricher.enrich(parsed)

        original_names = [c.name for c in result.columns[:2]]
        assert original_names == ["dob", "city"]
        assert result.rows[0]["city"] == "NYC"

    def test_enrich_multiple_rules_compose(self):
        parsed = _make_parsed_csv(
            columns=[("dob", "text")],
            rows=[
                {"dob": "28/01/1977"},
                {"dob": "15/06/1990"},
                {"dob": "03/12/1985"},
            ],
        )
        enricher = ColumnEnricher(rules=_all_rules())
        result = enricher.enrich(parsed)

        col_names = [c.name for c in result.columns]
        assert "dob_days" in col_names
        assert "dob_month" in col_names
        assert "dob_year" in col_names
        expected_days = (date(1977, 1, 28) - date(1970, 1, 1)).days
        assert result.rows[0]["dob_days"] == expected_days
        assert result.rows[0]["dob_month"] == 1
        assert result.rows[0]["dob_year"] == 1977

    def test_enrich_does_not_mutate_original_rows(self):
        original_rows = [
            {"dob": "28/01/1977", "name": "Alice"},
            {"dob": "15/06/1990", "name": "Bob"},
        ]
        snapshot = copy.deepcopy(original_rows)

        parsed = _make_parsed_csv(
            columns=[("dob", "text"), ("name", "text")],
            rows=original_rows,
        )
        enricher = ColumnEnricher(rules=_all_rules())
        enricher.enrich(parsed)

        assert original_rows == snapshot

    def test_enrich_populates_samples(self):
        parsed = _make_parsed_csv(
            columns=[("dob", "text")],
            rows=[
                {"dob": "28/01/1977"},
                {"dob": "15/06/1990"},
                {"dob": "03/12/1985"},
                {"dob": "01/01/2000"},
            ],
        )
        enricher = ColumnEnricher(rules=_all_rules())
        result = enricher.enrich(parsed)

        days_col = next(c for c in result.columns if c.name == "dob_days")
        assert len(days_col.samples) == 3

        year_col = next(c for c in result.columns if c.name == "dob_year")
        assert year_col.samples[0] == "1977"
