from __future__ import annotations

import sqlite3

from repository.csv_parser import CSVParser, ParsedCSV
from shared.modules.data.ingest_result import IngestResult


class SqliteIngester:
    def __init__(self, db_uri: str) -> None:
        self._db_uri = db_uri

    def ingest(self, csv_path: str) -> IngestResult:
        parsed_csv = CSVParser.parse(csv_path)

        connection = sqlite3.connect(self._db_uri, uri=True)
        try:
            self._create_table(connection, parsed_csv)
            self._insert_rows(connection, parsed_csv)
            connection.commit()
        finally:
            connection.close()

        return IngestResult(table_name=parsed_csv.table_name, columns=parsed_csv.columns)

    def _create_table(self, connection: sqlite3.Connection, parsed: ParsedCSV) -> None:
        column_defs = ", ".join(
            f'"{col.name}" {"REAL" if col.detected_type == "numeric" else "TEXT"}'
            for col in parsed.columns
        )
        cursor = connection.cursor()
        cursor.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
        cursor.execute(f'CREATE TABLE "{parsed.table_name}" ({column_defs})')

    def _insert_rows(self, connection: sqlite3.Connection, parsed_csv: ParsedCSV) -> None:
        column_types = {c.name: c.detected_type for c in parsed_csv.columns}
        placeholders = ", ".join("?" for _ in parsed_csv.headers)
        cursor = connection.cursor()
        for row in parsed_csv.rows:
            values = [self._to_sql_value(row[h], column_types[h]) for h in parsed_csv.headers]
            cursor.execute(f'INSERT INTO "{parsed_csv.table_name}" VALUES ({placeholders})', values)

    @staticmethod
    def _to_sql_value(raw_value: str, detected_type: str) -> float | None | str:
        if detected_type != "numeric":
            return raw_value
        stripped = raw_value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
