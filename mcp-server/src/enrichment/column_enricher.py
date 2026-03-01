from __future__ import annotations

import logging

from shared.config import Config
from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV
from enrichment.enrichment_rule import EnrichmentRule

logger = logging.getLogger(__name__)

_MAX_SAMPLE_VALUES = 5
_MAX_SCAN_ROWS = 100


class ColumnEnricher:
    def __init__(self, rules: list[EnrichmentRule]) -> None:
        self._rules = rules

    def enrich(self, parsed_csv: ParsedCSV) -> ParsedCSV:
        new_columns: list[ColumnInfo] = []
        applicable_rules: list[EnrichmentRule] = []

        detection_sample_size = Config.get("mcp_server.enrichment.detection_sample_size")
        sample_rows = parsed_csv.rows[:detection_sample_size]

        for rule in self._rules:
            detected = rule.infer_derived_columns(parsed_csv.columns, sample_rows)
            if detected:
                new_columns.extend(detected)
                applicable_rules.append(rule)
                logger.info(
                    "Enrichment rule %s will add columns: %s",
                    rule.__class__.__name__,
                    [column.name for column in detected],
                )

        if not applicable_rules:
            return parsed_csv

        enriched_rows = [{**row} for row in parsed_csv.rows]
        for rule in applicable_rules:
            enriched_rows = rule.add_derived_columns(enriched_rows)

        new_columns = self._populate_samples(new_columns, enriched_rows)

        return ParsedCSV(
            table_name=parsed_csv.table_name,
            columns=list(parsed_csv.columns) + new_columns,
            rows=enriched_rows,
        )

    @staticmethod
    def _populate_samples(
        columns: list[ColumnInfo], rows: list[dict],
    ) -> list[ColumnInfo]:
        """Return new ColumnInfo objects with distinct samples populated from rows."""
        result = []
        for column in columns:
            samples: list[str] = []
            seen: set[str] = set()
            for row in rows[:_MAX_SCAN_ROWS]:
                value = row.get(column.name)
                if value is None:
                    continue
                str_value = str(value)
                if str_value not in seen:
                    seen.add(str_value)
                    samples.append(str_value)
                    if len(samples) >= _MAX_SAMPLE_VALUES:
                        break
            result.append(ColumnInfo(name=column.name, detected_type=column.detected_type, samples=samples))
        return result
