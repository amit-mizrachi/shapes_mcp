from __future__ import annotations

import logging
from datetime import datetime

from enrichment.enrichment_rule import EnrichmentRule
from enrichment.rules.date_detection import detect_date_columns
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)


class MonthExtractionRule(EnrichmentRule):

    def __init__(self) -> None:
        self._date_columns: list[tuple[str, str]] = []

    def infer_derived_columns(
        self, columns: list[ColumnInfo], sample_rows: list[dict],
    ) -> list[ColumnInfo]:
        self._date_columns = detect_date_columns(columns, sample_rows)
        existing_names = {column.name for column in columns}
        new_columns: list[ColumnInfo] = []

        for column_name, _ in self._date_columns:
            derived = f"{column_name}_month"
            if derived not in existing_names:
                new_columns.append(ColumnInfo(name=derived, detected_type="numeric", samples=[]))
                logger.info("MonthExtractionRule: will add '%s'", derived)

        return new_columns

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            for column_name, date_format in self._date_columns:
                raw = str(row.get(column_name, "")).strip()
                key = f"{column_name}_month"
                if not raw:
                    row[key] = None
                    continue
                try:
                    parsed = datetime.strptime(raw, date_format).date()
                    row[key] = parsed.month
                except ValueError:
                    row[key] = None
        return rows
