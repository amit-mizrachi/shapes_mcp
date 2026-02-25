from __future__ import annotations

import sqlite3

from repository.csv_parser import CSVParser
from repository.models import IngestResult


class SqliteIngester:
    def __init__(self, db_uri: str) -> None:
        self._db_uri = db_uri

    def ingest(self, csv_path: str) -> IngestResult:
        parsed = CSVParser.parse(csv_path)

        connection = sqlite3.connect(self._db_uri, uri=True)
        cursor = connection.cursor()

        column_definitions = ", ".join(
            f'"{c.name}" {"REAL" if c.detected_type == "numeric" else "TEXT"}'
            for c in parsed.columns
        )
        cursor.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
        cursor.execute(f'CREATE TABLE "{parsed.table_name}" ({column_definitions})')

        placeholders = ", ".join("?" for _ in parsed.headers)
        for row in parsed.rows:
            values = [row[h] for h in parsed.headers]
            cursor.execute(f'INSERT INTO "{parsed.table_name}" VALUES ({placeholders})', values)

        connection.commit()
        connection.close()

        return IngestResult(
            table_name=parsed.table_name,
            columns=parsed.columns,
        )
