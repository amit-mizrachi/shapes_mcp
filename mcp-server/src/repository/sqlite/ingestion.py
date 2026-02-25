from __future__ import annotations

import os
import sqlite3

from repository.csv_utils import parse_csv
from repository.protocol import IngestResult


class SqliteIngester:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def ingest(self, csv_path: str) -> IngestResult:
        parsed = parse_csv(csv_path)

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        cur = conn.cursor()

        col_defs = ", ".join(
            f'"{c.name}" {"REAL" if c.detected_type == "numeric" else "TEXT"}'
            for c in parsed.columns
        )
        cur.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
        cur.execute(f'CREATE TABLE "{parsed.table_name}" ({col_defs})')

        placeholders = ", ".join("?" for _ in parsed.headers)
        for row in parsed.rows:
            values = [row[h] for h in parsed.headers]
            cur.execute(f'INSERT INTO "{parsed.table_name}" VALUES ({placeholders})', values)

        conn.commit()
        conn.close()

        print(
            f"Ingested {len(parsed.rows)} rows into table '{parsed.table_name}' "
            f"with columns: {[c.name for c in parsed.columns]}"
        )

        return IngestResult(
            table_name=parsed.table_name,
            columns=parsed.columns,
            db_path=self._db_path,
        )
