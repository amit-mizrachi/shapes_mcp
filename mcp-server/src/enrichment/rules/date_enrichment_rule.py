from __future__ import annotations

import logging
from datetime import date, datetime

from enrichment.enrichment_rule import EnrichmentRule
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)

_DATE_FORMATS = [
    "%d/%m/%Y",  # 28/01/1977
    "%m/%d/%Y",  # 07/12/1989
    "%Y-%m-%d",  # 1989-07-12
    "%d-%m-%Y",  # 28-01-1977
    "%m-%d-%Y",  # 07-12-1989
    "%Y/%m/%d",  # 1989/07/12
]

_DETECTION_THRESHOLD = 0.8


class DateEnrichmentRule(EnrichmentRule):

    def __init__(self) -> None:
        self._date_columns: list[tuple[str, str]] = []

    def infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]:
        self._date_columns = []
        new_columns: list[ColumnInfo] = []
        existing_names = {c.name for c in columns}

        for col in columns:
            if col.detected_type == "numeric":
                continue

            date_format = self._detect_date_format(col.name, sample_rows)
            if date_format is None:
                continue

            self._date_columns.append((col.name, date_format))
            logger.info("Detected date column '%s' with format '%s'", col.name, date_format)

            for suffix, dtype in [("_years_ago", "numeric"), ("_year", "numeric"), ("_month", "numeric")]:
                derived_name = f"{col.name}{suffix}"
                if derived_name not in existing_names:
                    new_columns.append(ColumnInfo(name=derived_name, detected_type=dtype, samples=[]))

        return new_columns

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        today = date.today()
        for row in rows:
            for col_name, fmt in self._date_columns:
                raw = str(row.get(col_name, "")).strip()
                years_ago_key = f"{col_name}_years_ago"
                year_key = f"{col_name}_year"
                month_key = f"{col_name}_month"

                if not raw:
                    row[years_ago_key] = None
                    row[year_key] = None
                    row[month_key] = None
                    continue

                try:
                    parsed_date = datetime.strptime(raw, fmt).date()
                    row[years_ago_key] = self._years_between(parsed_date, today)
                    row[year_key] = parsed_date.year
                    row[month_key] = parsed_date.month
                except ValueError:
                    row[years_ago_key] = None
                    row[year_key] = None
                    row[month_key] = None
        return rows

    def _detect_date_format(self, col_name: str, sample_rows: list[dict]) -> str | None:
        values = [
            str(r.get(col_name, "")).strip()
            for r in sample_rows
            if str(r.get(col_name, "")).strip()
        ]
        if not values:
            return None

        for fmt in _DATE_FORMATS:
            parsed_count = sum(1 for v in values if self._try_parse(v, fmt))
            if parsed_count / len(values) >= _DETECTION_THRESHOLD:
                return fmt

        return None

    @staticmethod
    def _try_parse(value: str, fmt: str) -> bool:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            return False

    @staticmethod
    def _years_between(earlier: date, later: date) -> int:
        """Compute whole years elapsed, matching how human age works."""
        years = later.year - earlier.year
        if (later.month, later.day) < (earlier.month, earlier.day):
            years -= 1
        return years
