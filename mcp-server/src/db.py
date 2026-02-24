import csv
import os
import re
import sqlite3

import aiosqlite

DB_PATH = "/app/db/data.db"

_table_name: str = ""
_column_info: list[dict] = []


def _detect_type(values: list[str]) -> str:
    numeric = 0
    total = 0
    for v in values:
        v = v.strip()
        if not v:
            continue
        total += 1
        try:
            float(v)
            numeric += 1
        except ValueError:
            pass
    if total == 0:
        return "text"
    return "numeric" if numeric / total > 0.8 else "text"


def _derive_table_name(csv_path: str) -> str:
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    safe = re.sub(r"[^a-z0-9]+", "_", basename.lower()).strip("_")
    return safe or "data"


def ingest_csv(csv_path: str, db_path: str) -> list[dict]:
    global _column_info, _table_name

    _table_name = _derive_table_name(csv_path)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        if not columns:
            raise ValueError(f"CSV file {csv_path} has no headers")
        safe_columns = [re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in columns]
        rows = list(reader)

    if not rows:
        raise ValueError(f"CSV file {csv_path} has no data rows")

    col_map = dict(zip(columns, safe_columns))
    meta = []
    for orig, safe in zip(columns, safe_columns):
        values = [r[orig] for r in rows]
        detected = _detect_type(values)
        meta.append({
            "name": safe,
            "detected_type": detected,
            "samples": [v for v in values[:3]],
        })

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    col_defs = ", ".join(
        f'"{m["name"]}" {"REAL" if m["detected_type"] == "numeric" else "TEXT"}'
        for m in meta
    )
    cur.execute(f'DROP TABLE IF EXISTS "{_table_name}"')
    cur.execute(f'CREATE TABLE "{_table_name}" ({col_defs})')

    placeholders = ", ".join("?" for _ in safe_columns)
    for row in rows:
        values = [row[orig] for orig in columns]
        cur.execute(f'INSERT INTO "{_table_name}" VALUES ({placeholders})', values)

    conn.commit()
    conn.close()

    _column_info = meta
    print(f"Ingested {len(rows)} rows into table '{_table_name}' with columns: {[m['name'] for m in meta]}")
    return meta


def get_table_name() -> str:
    return _table_name


def get_column_info() -> list[dict]:
    return _column_info


async def get_read_connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = aiosqlite.Row
    return conn
