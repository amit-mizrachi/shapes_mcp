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
        columns, sanitized_rows = CSVParser._detect_types_and_rekey(
            raw_columns, sanitized_columns, rows,
        )

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
            message = f"CSV file not found: {csv_path}"
            logger.error(message)
            raise ValueError(message) from None
        except PermissionError:
            message = f"Permission denied reading CSV: {csv_path}"
            logger.error(message)
            raise ValueError(message) from None

        if not rows:
            raise ValueError(f"CSV file {csv_path} has no data rows")

        logger.debug("Read %d rows with %d columns from %s", len(rows), len(raw_columns), csv_path)
        return list(raw_columns), rows

    @staticmethod
    def _sanitize_column_names(raw_columns: list[str]) -> list[str]:
        """Sanitize raw column names into safe SQL identifiers."""
        return [CSVParser._sanitize_identifier(column_name) for column_name in raw_columns]

    @staticmethod
    def _sanitize_identifier(raw_name: str) -> str:
        """Lowercase, replace non-alphanumeric runs with underscores, strip edges."""
        return _SANITIZE_PATTERN.sub("_", raw_name.lower()).strip("_")

    @staticmethod
    def path_to_table_name(csv_path: str) -> str:
        basename = os.path.splitext(os.path.basename(csv_path))[0]
        return CSVParser._sanitize_identifier(basename) or "data"

    @staticmethod
    def _detect_types_and_rekey(
        raw_columns: list[str],
        sanitized_columns: list[str],
        rows: list[dict],
    ) -> tuple[list[ColumnInfo], list[dict]]:
        """Detect column types and rekey rows in a single pass over the data."""
        num_columns = len(raw_columns)
        numeric_counts = [0] * num_columns
        totals = [0] * num_columns
        samples: list[list[str]] = [[] for _ in range(num_columns)]
        sanitized_rows: list[dict] = []

        for row in rows:
            new_row = {}
            for column_index in range(num_columns):
                value = row[raw_columns[column_index]]
                new_row[sanitized_columns[column_index]] = value

                stripped = value.strip()
                if stripped:
                    totals[column_index] += 1
                    try:
                        float(stripped)
                        numeric_counts[column_index] += 1
                    except ValueError:
                        pass

                if len(samples[column_index]) < _MAX_SAMPLE_VALUES:
                    samples[column_index].append(value)

            sanitized_rows.append(new_row)

        numeric_threshold = Config.get("mcp_server.numeric_threshold")
        columns = []
        for column_index in range(num_columns):
            total = totals[column_index]
            if total == 0:
                detected_type = "text"
            else:
                detected_type = "numeric" if numeric_counts[column_index] / total > numeric_threshold else "text"
            columns.append(ColumnInfo(
                name=sanitized_columns[column_index],
                detected_type=detected_type,
                samples=samples[column_index],
            ))

        return columns, sanitized_rows

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
