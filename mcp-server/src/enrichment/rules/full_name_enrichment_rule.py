from __future__ import annotations

from enrichment.enrichment_rule import EnrichmentRule
from shared.modules.data.column_info import ColumnInfo

_NAME_PAIRS = [
    ("first_name", "last_name"),
]


class FullNameEnrichmentRule(EnrichmentRule):

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str]] = []

    def infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]:
        self._pairs = []
        column_names = {c.name for c in columns}
        new_columns: list[ColumnInfo] = []

        for first_col, last_col in _NAME_PAIRS:
            if first_col in column_names and last_col in column_names and "full_name" not in column_names:
                self._pairs.append((first_col, last_col))
                new_columns.append(ColumnInfo(name="full_name", detected_type="text", samples=[]))

        return new_columns

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            for first_col, last_col in self._pairs:
                first = str(row.get(first_col, "")).strip()
                last = str(row.get(last_col, "")).strip()
                row["full_name"] = f"{first} {last}".strip()
        return rows
