from __future__ import annotations

import logging

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV
from enrichment.enrichment_rule import EnrichmentRule

logger = logging.getLogger(__name__)

_MAX_SAMPLES = 3


class ColumnEnricher:
    def __init__(self, rules: list[EnrichmentRule]) -> None:
        self._rules = rules

    def enrich(self, parsed_csv: ParsedCSV) -> ParsedCSV:
        new_columns: list[ColumnInfo] = []
        applicable_rules: list[EnrichmentRule] = []

        sample_rows = parsed_csv.rows[:20]

        for rule in self._rules:
            detected = rule.detect(parsed_csv.columns, sample_rows)
            if detected:
                new_columns.extend(detected)
                applicable_rules.append(rule)
                logger.info(
                    "Enrichment rule %s will add columns: %s",
                    rule.__class__.__name__,
                    [c.name for c in detected],
                )

        if not applicable_rules:
            return parsed_csv

        enriched_rows = [{**row} for row in parsed_csv.rows]
        for rule in applicable_rules:
            enriched_rows = rule.apply(enriched_rows)

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
        """Return new ColumnInfo objects with samples populated from the first rows."""
        result = []
        for col in columns:
            samples = [
                str(row[col.name])
                for row in rows[:_MAX_SAMPLES]
                if row.get(col.name) is not None
            ]
            result.append(ColumnInfo(name=col.name, detected_type=col.detected_type, samples=samples))
        return result
