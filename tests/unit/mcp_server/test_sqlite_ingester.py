"""Tests for mcp-server/src/data_store/sqlite_ingester.py — CSV ingestion to SQLite."""

import sqlite3

import pytest

from data_store.csv_parser import CSVParser
from data_store.sqlite_ingester import SqliteIngester


class TestSqliteIngester:
    def test_ingest_creates_table(self, test_db, sample_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(sample_csv_path)))

        conn = sqlite3.connect(test_db)
        cursor = conn.execute(f"SELECT count(*) FROM \"{result.table_name}\"")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 5

    def test_ingest_returns_correct_table_name(self, test_db, sample_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
        assert result.table_name == "sample_data"

    def test_ingest_returns_columns(self, test_db, sample_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "age" in col_names
        assert "score" in col_names

    def test_ingest_column_types(self, test_db, sample_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
        type_map = {c.name: c.detected_type for c in result.columns}
        assert type_map["age"] == "numeric"
        assert type_map["name"] == "text"

    def test_ingest_data_values(self, test_db, sample_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(sample_csv_path)))

        conn = sqlite3.connect(test_db)
        cursor = conn.execute(f'SELECT "name" FROM "{result.table_name}" ORDER BY "name"')
        names = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert names == ["Alice", "Bob", "Charlie", "Diana", "Eve"]

    def test_ingest_special_columns(self, test_db, special_columns_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(special_columns_csv_path)))

        col_names = [c.name for c in result.columns]
        assert "first_name" in col_names
        assert "last_name" in col_names

    def test_ingest_unicode(self, test_db, unicode_csv_path):
        ingester = SqliteIngester(test_db)
        result = ingester.ingest(CSVParser.parse(str(unicode_csv_path)))

        conn = sqlite3.connect(test_db)
        cursor = conn.execute(f'SELECT "name" FROM "{result.table_name}" ORDER BY "name"')
        names = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "Müller" in names
        assert "García" in names

    def test_ingest_empty_data_raises(self, test_db, empty_headers_csv_path):
        with pytest.raises(ValueError, match="no data rows"):
            CSVParser.parse(str(empty_headers_csv_path))
