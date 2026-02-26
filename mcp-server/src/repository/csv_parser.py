from __future__ import annotations

import csv
import logging
import os
import re

from shared.config import Config
from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV

logger = logging.getLogger(__name__)

_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SAMPLE_VALUES = 3


class CSVParser:
    @staticmethod
    def parse(csv_path: str) -> ParsedCSV:
        raw_columns, rows = CSVParser._read_csv(csv_path)
        sanitized_columns = CSVParser._sanitize_column_names(raw_columns)
        table_name = CSVParser.path_to_table_name(csv_path)
        columns = CSVParser._detect_column_types(raw_columns, sanitized_columns, rows)
        sanitized_rows = CSVParser._rekey_rows(raw_columns, sanitized_columns, rows)

        return ParsedCSV(
            table_name=table_name,
            columns=columns,
            rows=sanitized_rows,
        )

    @staticmethod
    def _read_csv(csv_path: str) -> tuple[list[str], list[dict]]:
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

    @staticmethod
    def _sanitize_column_names(raw_columns: list[str]) -> list[str]:
        """Sanitize raw column names into safe SQL identifiers."""
        return [CSVParser._sanitize_identifier(col) for col in raw_columns]

    @staticmethod
    def _sanitize_identifier(raw_name: str) -> str:
        """Lowercase, replace non-alphanumeric runs with underscores, strip edges."""
        return _SANITIZE_PATTERN.sub("_", raw_name.lower()).strip("_")

    @staticmethod
    def path_to_table_name(csv_path: str) -> str:
        basename = os.path.splitext(os.path.basename(csv_path))[0]
        return CSVParser._sanitize_identifier(basename) or "data"

    @staticmethod
    def _detect_column_types(
        raw_columns: list[str],
        sanitized_columns: list[str],
        rows: list[dict],
    ) -> list[ColumnInfo]:
        columns: list[ColumnInfo] = []
        for original, sanitized in zip(raw_columns, sanitized_columns):
            values = [row[original] for row in rows]
            detected = CSVParser.detect_column_type(values)
            columns.append(ColumnInfo(name=sanitized, detected_type=detected, samples=values[:_MAX_SAMPLE_VALUES]))
        return columns

    @staticmethod
    def detect_column_type(values: list[str]) -> str:
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
    def _rekey_rows(raw_columns: list[str], sanitized_columns: list[str], rows: list[dict]) -> list[dict]:
        column_name_map = dict(zip(raw_columns, sanitized_columns))
        return [{column_name_map[key]: val for key, val in row.items()} for row in rows]
