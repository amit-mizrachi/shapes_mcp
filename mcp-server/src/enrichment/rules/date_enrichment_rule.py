from __future__ import annotations

import logging
from datetime import datetime, date

from enrichment.enrichment_rule import EnrichmentRule
from enrichment.rules.date_detection import detect_date_columns
from shared.config import Config
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)


class DateEnrichmentRule(EnrichmentRule):

    _ALL_SUFFIXES = ("_days", "_month", "_year")

    def __init__(self) -> None:
        epoch_string = Config.get("mcp_server.enrichment.nominal_date_epoch")
        self._epoch = date.fromisoformat(epoch_string)
        self._date_columns: list[tuple[str, str, tuple[str, ...]]] = []

    def infer_derived_columns(
        self, columns: list[ColumnInfo], sample_rows: list[dict],
    ) -> list[ColumnInfo]:
        detected = detect_date_columns(columns, sample_rows)
        existing_names = {column.name for column in columns}
        self._date_columns = []
        new_columns: list[ColumnInfo] = []

        for column_name, date_format in detected:
            suffixes = tuple(
                s for s in self._ALL_SUFFIXES
                if f"{column_name}{s}" not in existing_names
            )
            if not suffixes:
                continue
            self._date_columns.append((column_name, date_format, suffixes))
            for suffix in suffixes:
                derived = f"{column_name}{suffix}"
                new_columns.append(ColumnInfo(name=derived, detected_type="numeric", samples=[]))
                logger.info("DateEnrichmentRule: will add '%s' (format '%s')", derived, date_format)

        return new_columns

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            for column_name, date_format, suffixes in self._date_columns:
                raw = str(row.get(column_name, "")).strip()
                if not raw:
                    for suffix in suffixes:
                        row[f"{column_name}{suffix}"] = None
                    continue
                try:
                    parsed = datetime.strptime(raw, date_format).date()
                    values = {
                        "_days": (parsed - self._epoch).days,
                        "_month": parsed.month,
                        "_year": parsed.year,
                    }
                    for suffix in suffixes:
                        row[f"{column_name}{suffix}"] = values[suffix]
                except ValueError:
                    for suffix in suffixes:
                        row[f"{column_name}{suffix}"] = None
        return rows
