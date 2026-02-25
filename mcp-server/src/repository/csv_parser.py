from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass

from shared.modules.column_info import ColumnInfo

class CSVParser:
    @staticmethod
    def detect_column_type(values: list[str]) -> str:
        """Return 'numeric' if >80% of non-empty values parse as float, else 'text'."""
        numeric_count = 0
        total = 0
        for value in values:
            value = value.strip()
            if not value:
                continue
            total += 1
            try:
                float(value)
                numeric_count += 1
            except ValueError:
                pass
        if total == 0:
            return "text"
        return "numeric" if numeric_count / total > 0.8 else "text"

    @staticmethod
    def csv_filename_to_table_name(csv_path: str) -> str:
        """Convert a CSV filename into a safe SQL table name."""
        basename = os.path.splitext(os.path.basename(csv_path))[0]
        sanitized_name = re.sub(r"[^a-z0-9]+", "_", basename.lower()).strip("_")
        return sanitized_name or "data"


    @dataclass(frozen=True)
    class ParsedCSV:
        table_name: str
        columns: list[ColumnInfo]
        headers: list[str]
        rows: list[dict]


    @staticmethod
    def parse(csv_path: str) -> ParsedCSV:
        """Read a CSV file, sanitize column names, detect types, return parsed data."""
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_columns = reader.fieldnames
            if not raw_columns:
                raise ValueError(f"CSV file {csv_path} has no headers")
            rows = list(reader)

        if not rows:
            raise ValueError(f"CSV file {csv_path} has no data rows")

        sanitized_columns = [re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in raw_columns]
        table_name = CSVParser.csv_filename_to_table_name(csv_path)

        columns: list[ColumnInfo] = []
        for orig, sanitized in zip(raw_columns, sanitized_columns):
            values = [r[orig] for r in rows]
            detected = CSVParser.detect_column_type(values)
            columns.append(ColumnInfo(name=sanitized, detected_type=detected, samples=values[:3]))

        # Re-key rows from original headers to sanitized column names
        column_name_map = dict(zip(raw_columns, sanitized_columns))
        sanitized_rows = [{column_name_map[k]: v for k, v in row.items()} for row in rows]

        return ParsedCSV(
            table_name=table_name,
            columns=columns,
            headers=sanitized_columns,
            rows=sanitized_rows,
        )
