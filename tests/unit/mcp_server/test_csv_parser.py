"""Tests for mcp-server/src/data_store/csv_parser.py — type detection, sanitization, parsing."""

import pytest

from data_store.csv_parser import CSVParser
from shared.modules.data.parsed_csv import ParsedCSV


class TestDetectColumnType:
    def test_all_numeric(self):
        assert CSVParser.detect_column_type(["1", "2.5", "3"]) == "numeric"

    def test_all_text(self):
        assert CSVParser.detect_column_type(["hello", "world"]) == "text"

    def test_empty_values_only(self):
        assert CSVParser.detect_column_type(["", "", ""]) == "text"

    def test_mixed_below_threshold(self):
        # 2/5 = 40% numeric — well below 80%
        assert CSVParser.detect_column_type(["1", "2", "abc", "def", "ghi"]) == "text"

    def test_mixed_above_threshold(self):
        # 9/10 = 90% numeric — above 80%
        values = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "abc"]
        assert CSVParser.detect_column_type(values) == "numeric"

    def test_at_threshold_boundary(self):
        # Exactly 80% = 4/5 — NOT above threshold, so "text"
        values = ["1", "2", "3", "4", "abc"]
        assert CSVParser.detect_column_type(values) == "text"

    def test_just_above_threshold(self):
        # 81/100 > 80%
        values = ["1"] * 81 + ["abc"] * 19
        assert CSVParser.detect_column_type(values) == "numeric"

    def test_empty_strings_skipped(self):
        # Only "1" and "2" are counted; empty strings are skipped → 100% numeric
        assert CSVParser.detect_column_type(["1", "", "2", ""]) == "numeric"

    def test_whitespace_values_skipped(self):
        assert CSVParser.detect_column_type(["  ", "1", "2"]) == "numeric"

    def test_negative_numbers(self):
        assert CSVParser.detect_column_type(["-1", "-2.5", "3"]) == "numeric"

    def test_scientific_notation(self):
        assert CSVParser.detect_column_type(["1e10", "2.5e-3"]) == "numeric"

    def test_single_numeric(self):
        assert CSVParser.detect_column_type(["42"]) == "numeric"

    def test_single_text(self):
        assert CSVParser.detect_column_type(["hello"]) == "text"

    def test_empty_list(self):
        assert CSVParser.detect_column_type([]) == "text"


class TestPathToTableName:
    def test_simple_name(self):
        assert CSVParser.path_to_table_name("data.csv") == "data"

    def test_dashes_and_spaces(self):
        assert CSVParser.path_to_table_name("my-data file.csv") == "my_data_file"

    def test_full_path(self):
        assert CSVParser.path_to_table_name("/home/user/people-list-export.csv") == "people_list_export"

    def test_uppercase(self):
        assert CSVParser.path_to_table_name("MyData.CSV") == "mydata"

    def test_special_characters(self):
        assert CSVParser.path_to_table_name("data@2024#v1.csv") == "data_2024_v1"

    def test_empty_after_sanitization(self):
        assert CSVParser.path_to_table_name("@@@.csv") == "data"

    def test_numbers_only(self):
        assert CSVParser.path_to_table_name("12345.csv") == "12345"


class TestParse:
    def test_basic_parse(self, sample_csv_path):
        parsed = CSVParser.parse(str(sample_csv_path))
        assert parsed.table_name == "sample_data"
        assert len(parsed.headers) == 5
        assert len(parsed.rows) == 5

    def test_column_types_detected(self, sample_csv_path):
        parsed = CSVParser.parse(str(sample_csv_path))
        type_map = {c.name: c.detected_type for c in parsed.columns}
        assert type_map["age"] == "numeric"
        assert type_map["score"] == "numeric"
        assert type_map["name"] == "text"
        assert type_map["city"] == "text"

    def test_samples_populated(self, sample_csv_path):
        parsed = CSVParser.parse(str(sample_csv_path))
        for col in parsed.columns:
            assert len(col.samples) <= 3

    def test_special_column_sanitization(self, special_columns_csv_path):
        parsed = CSVParser.parse(str(special_columns_csv_path))
        assert "first_name" in parsed.headers
        assert "last_name" in parsed.headers
        assert "e_mail_address" in parsed.headers
        assert "phone" in parsed.headers
        assert "annual_alary" in parsed.headers

    def test_rows_rekeyed_to_sanitized_names(self, special_columns_csv_path):
        parsed = CSVParser.parse(str(special_columns_csv_path))
        row = parsed.rows[0]
        assert "first_name" in row
        assert row["first_name"] == "John"

    def test_empty_data_raises(self, empty_headers_csv_path):
        with pytest.raises(ValueError, match="no data rows"):
            CSVParser.parse(str(empty_headers_csv_path))

    def test_unicode_data(self, unicode_csv_path):
        parsed = CSVParser.parse(str(unicode_csv_path))
        assert len(parsed.rows) == 4
        names = [r["name"] for r in parsed.rows]
        assert "Müller" in names

    def test_parsed_csv_is_dataclass(self, sample_csv_path):
        parsed = CSVParser.parse(str(sample_csv_path))
        assert isinstance(parsed, ParsedCSV)
