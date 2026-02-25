from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass

from repository.protocol import ColumnInfo


def detect_type(values: list[str]) -> str:
    """Return 'numeric' if >80% of non-empty values parse as float, else 'text'."""
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


def derive_table_name(csv_path: str) -> str:
    """Convert a CSV filename into a safe SQL table name."""
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    safe = re.sub(r"[^a-z0-9]+", "_", basename.lower()).strip("_")
    return safe or "data"


@dataclass(frozen=True)
class ParsedCSV:
    table_name: str
    columns: list[ColumnInfo]
    headers: list[str]
    rows: list[dict]


def parse_csv(csv_path: str) -> ParsedCSV:
    """Read a CSV file, sanitize column names, detect types, return parsed data."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_columns = reader.fieldnames
        if not raw_columns:
            raise ValueError(f"CSV file {csv_path} has no headers")
        rows = list(reader)

    if not rows:
        raise ValueError(f"CSV file {csv_path} has no data rows")

    safe_columns = [re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in raw_columns]
    table_name = derive_table_name(csv_path)

    columns: list[ColumnInfo] = []
    for orig, safe in zip(raw_columns, safe_columns):
        values = [r[orig] for r in rows]
        detected = detect_type(values)
        columns.append(ColumnInfo(name=safe, detected_type=detected, samples=values[:3]))

    # Re-key rows from original headers to safe column names
    col_map = dict(zip(raw_columns, safe_columns))
    safe_rows = [{col_map[k]: v for k, v in row.items()} for row in rows]

    return ParsedCSV(
        table_name=table_name,
        columns=columns,
        headers=safe_columns,
        rows=safe_rows,
    )
