from __future__ import annotations

import logging
from datetime import datetime, date

from enrichment.enrichment_rule import EnrichmentRule
from enrichment.rules.date_detection import detect_date_columns
from shared.config import Config
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)


class NominalDateRule(EnrichmentRule):

    def __init__(self) -> None:
        epoch_string = Config.get("mcp_server.enrichment.nominal_date_epoch")
        self._epoch = date.fromisoformat(epoch_string)
        self._date_columns: list[tuple[str, str]] = []

    def infer_derived_columns(
        self, columns: list[ColumnInfo], sample_rows: list[dict],
    ) -> list[ColumnInfo]:
        self._date_columns = detect_date_columns(columns, sample_rows)
        existing_names = {column.name for column in columns}
        new_columns: list[ColumnInfo] = []

        for column_name, date_format in self._date_columns:
            derived = f"{column_name}_days"
            if derived not in existing_names:
                new_columns.append(ColumnInfo(name=derived, detected_type="numeric", samples=[]))
                logger.info("NominalDateRule: will add '%s' (format '%s')", derived, date_format)

        return new_columns

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            for column_name, date_format in self._date_columns:
                raw = str(row.get(column_name, "")).strip()
                key = f"{column_name}_days"
                if not raw:
                    row[key] = None
                    continue
                try:
                    parsed = datetime.strptime(raw, date_format).date()
                    row[key] = (parsed - self._epoch).days
                except ValueError:
                    row[key] = None
        return rows
