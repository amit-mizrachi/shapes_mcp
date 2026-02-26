from __future__ import annotations

import csv
import logging
import os
import re
from dataclasses import dataclass

from shared.config import Config
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)

_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SAMPLE_VALUES = 3


def _sanitize_identifier(raw_name: str) -> str:
    """Lowercase, replace non-alphanumeric runs with underscores, strip edges."""
    return _SANITIZE_PATTERN.sub("_", raw_name.lower()).strip("_")


@dataclass(frozen=True)
class ParsedCSV:
    table_name: str
    columns: list[ColumnInfo]
    rows: list[dict]

    @property
    def headers(self) -> list[str]:
        return [col.name for col in self.columns]


def _read_csv(csv_path: str) -> tuple[list[str], list[dict]]:
    """Read CSV file and return (raw_columns, rows)."""
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            raw_columns = reader.fieldnames
            if not raw_columns:
                raise ValueError(f"CSV file {csv_path} has no headers")
            rows = list(reader)
    except FileNotFoundError:
        logger.error("CSV file not found: %s", csv_path)
        raise ValueError(f"CSV file not found: {csv_path}") from None
    except PermissionError:
        logger.error("Permission denied reading CSV: %s", csv_path)
        raise ValueError(f"Permission denied reading CSV: {csv_path}") from None

    if not rows:
        raise ValueError(f"CSV file {csv_path} has no data rows")

    logger.debug("Read %d rows with %d columns from %s", len(rows), len(raw_columns), csv_path)
    return list(raw_columns), rows


def _sanitize_column_names(raw_columns: list[str]) -> list[str]:
    """Sanitize raw column names into safe SQL identifiers."""
    return [_sanitize_identifier(col) for col in raw_columns]


def _detect_columns(
    raw_columns: list[str],
    sanitized_columns: list[str],
    rows: list[dict],
) -> list[ColumnInfo]:
    """Detect column types by sampling row values."""
    columns: list[ColumnInfo] = []
    for original, sanitized in zip(raw_columns, sanitized_columns):
        values = [row[original] for row in rows]
        detected = CSVParser.detect_column_type(values)
        columns.append(ColumnInfo(name=sanitized, detected_type=detected, samples=values[:_MAX_SAMPLE_VALUES]))
    return columns


def _rekey_rows(raw_columns: list[str], sanitized_columns: list[str], rows: list[dict]) -> list[dict]:
    """Re-key rows from original headers to sanitized column names."""
    column_name_map = dict(zip(raw_columns, sanitized_columns))
    return [{column_name_map[key]: val for key, val in row.items()} for row in rows]


class CSVParser:
    @staticmethod
    def detect_column_type(values: list[str]) -> str:
        """Return 'numeric' if >80% of non-empty values parse as float, else 'text'."""
        numeric_count = 0
        total = 0
        for raw_value in values:
            stripped = raw_value.strip()
            if not stripped:
                continue
            total += 1
            try:
                float(stripped)
                numeric_count += 1
            except ValueError:
                pass
        if total == 0:
            return "text"
        return "numeric" if numeric_count / total > Config.get("mcp_server.numeric_threshold") else "text"

    @staticmethod
    def path_to_table_name(csv_path: str) -> str:
        """Convert a CSV path into a safe SQL table name."""
        basename = os.path.splitext(os.path.basename(csv_path))[0]
        return _sanitize_identifier(basename) or "data"

    @staticmethod
    def parse(csv_path: str) -> ParsedCSV:
        """Read a CSV file, sanitize column names, detect types, return parsed data."""
        raw_columns, rows = _read_csv(csv_path)
        sanitized_columns = _sanitize_column_names(raw_columns)
        table_name = CSVParser.path_to_table_name(csv_path)
        columns = _detect_columns(raw_columns, sanitized_columns, rows)
        sanitized_rows = _rekey_rows(raw_columns, sanitized_columns, rows)

        return ParsedCSV(
            table_name=table_name,
            columns=columns,
            rows=sanitized_rows,
        )
