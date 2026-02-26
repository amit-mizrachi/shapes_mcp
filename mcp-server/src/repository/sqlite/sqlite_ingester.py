from __future__ import annotations

import sqlite3

from repository.csv_parser import CSVParser
from shared.modules.ingest_result import IngestResult


class SqliteIngester:
    def __init__(self, db_uri: str) -> None:
        self._db_uri = db_uri

    def ingest(self, csv_path: str) -> IngestResult:
        parsed = CSVParser.parse(csv_path)

        connection = sqlite3.connect(self._db_uri, uri=True)
        cursor = connection.cursor()

        column_definitions = []

        for column in parsed.columns:
            if column.detected_type == "numeric":
                sql_type = "REAL"
            else:
                sql_type = "TEXT"

            column_definitions.append(f'"{column.name}" {sql_type}')

        column_definitions = ", ".join(column_definitions)

        cursor.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
        cursor.execute(f'CREATE TABLE "{parsed.table_name}" ({column_definitions})')

        column_types = {c.name: c.detected_type for c in parsed.columns}
        placeholders = ", ".join("?" for _ in parsed.headers)
        for row in parsed.rows:
            values = [self._convert_value(row[h], column_types[h]) for h in parsed.headers]
            cursor.execute(f'INSERT INTO "{parsed.table_name}" VALUES ({placeholders})', values)

        connection.commit()
        connection.close()

        return IngestResult(
            table_name=parsed.table_name,
            columns=parsed.columns,
        )

    @staticmethod
    def _convert_value(value: str, detected_type: str) -> float | None | str:
        if detected_type != "numeric":
            return value
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
