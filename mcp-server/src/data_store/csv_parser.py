import csv
import logging
import os
import re

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV

logger = logging.getLogger(__name__)

_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


class CSVParser:
    @staticmethod
    def parse(csv_path: str, numeric_threshold: float = 0.8, max_sample_values: int = 3) -> ParsedCSV:
        """Parse a CSV file into a structured ParsedCSV object.

        Args:
            csv_path: Filesystem path to the CSV file.
            numeric_threshold: Fraction of non-blank values that must be
                numeric for a column to be classified as "numeric" (0-1).
            max_sample_values: Number of sample values to store per column.

        Returns:
            ParsedCSV with sanitized column names, detected types, and rows.

        Raises:
            ValueError: If the file is missing, unreadable, has no headers,
                or has no data rows.
        """
        raw_columns, rows = CSVParser._read_csv(csv_path)
        sanitized_columns = CSVParser._sanitize_column_names(raw_columns)
        table_name = CSVParser.path_to_table_name(csv_path)
        columns, sanitized_rows = CSVParser._detect_types_and_rekey(
            raw_columns, sanitized_columns, rows, numeric_threshold, max_sample_values,
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
        """Derive a safe SQL table name from the CSV file path."""
        basename = os.path.splitext(os.path.basename(csv_path))[0]
        return CSVParser._sanitize_identifier(basename) or "data"

    @staticmethod
    def _detect_types_and_rekey(
        raw_columns: list[str],
        sanitized_columns: list[str],
        rows: list[dict],
        numeric_threshold: float,
        max_sample_values: int,
    ) -> tuple[list[ColumnInfo], list[dict]]:
        """Rekey rows to sanitized column names and detect column types."""
        sanitized_rows = [
            {sanitized: row.get(raw) or "" for raw, sanitized in zip(raw_columns, sanitized_columns)}
            for row in rows
        ]

        columns = [
            ColumnInfo(
                name=name,
                detected_type=CSVParser.detect_column_type(
                    [row[name] for row in sanitized_rows], numeric_threshold,
                ),
                samples=[row[name] for row in sanitized_rows[:max_sample_values]],
            )
            for name in sanitized_columns
        ]

        return columns, sanitized_rows

    @staticmethod
    def detect_column_type(values: list[str], numeric_threshold: float = 0.8) -> str:
        """Classify a column as 'numeric' or 'text' based on its values.

        A column is 'numeric' when the fraction of non-blank values that
        parse as floats exceeds *numeric_threshold*. Blank and None values
        are ignored.
        """
        numeric_count = 0
        total = 0
        for raw_value in values:
            stripped = (raw_value or "").strip()
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
        return "numeric" if numeric_count / total > numeric_threshold else "text"
