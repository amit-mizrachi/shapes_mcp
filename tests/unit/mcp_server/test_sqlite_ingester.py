"""Tests for mcp-server/src/repository/sqlite/sqlite_ingester.py — CSV ingestion to SQLite."""

import sqlite3

import pytest

from repository.sqlite.sqlite_ingester import SqliteIngester


class TestSqliteIngester:
    def test_ingest_creates_table(self, in_memory_db, sample_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(sample_csv_path))

        conn = sqlite3.connect(db_uri, uri=True)
        cursor = conn.execute(f"SELECT count(*) FROM \"{result.table_name}\"")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 5

    def test_ingest_returns_correct_table_name(self, in_memory_db, sample_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(sample_csv_path))
        assert result.table_name == "sample_data"

    def test_ingest_returns_columns(self, in_memory_db, sample_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(sample_csv_path))
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "age" in col_names
        assert "score" in col_names

    def test_ingest_column_types(self, in_memory_db, sample_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(sample_csv_path))
        type_map = {c.name: c.detected_type for c in result.columns}
        assert type_map["age"] == "numeric"
        assert type_map["name"] == "text"

    def test_ingest_data_values(self, in_memory_db, sample_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(sample_csv_path))

        conn = sqlite3.connect(db_uri, uri=True)
        cursor = conn.execute(f'SELECT "name" FROM "{result.table_name}" ORDER BY "name"')
        names = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert names == ["Alice", "Bob", "Charlie", "Diana", "Eve"]

    def test_ingest_special_columns(self, in_memory_db, special_columns_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(special_columns_csv_path))

        col_names = [c.name for c in result.columns]
        assert "first_name" in col_names
        assert "last_name" in col_names

    def test_ingest_unicode(self, in_memory_db, unicode_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        result = ingester.ingest(str(unicode_csv_path))

        conn = sqlite3.connect(db_uri, uri=True)
        cursor = conn.execute(f'SELECT "name" FROM "{result.table_name}" ORDER BY "name"')
        names = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "Müller" in names
        assert "García" in names

    def test_ingest_empty_data_raises(self, in_memory_db, empty_headers_csv_path):
        db_uri, keeper = in_memory_db
        ingester = SqliteIngester(db_uri)
        with pytest.raises(ValueError, match="no data rows"):
            ingester.ingest(str(empty_headers_csv_path))
