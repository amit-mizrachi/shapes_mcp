from __future__ import annotations

from abc import ABC, abstractmethod

from shared.modules.data.column_info import ColumnInfo


class EnrichmentRule(ABC):
    @abstractmethod
    def detect(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]:
        """Examine existing columns and return new ColumnInfo objects for
        columns this rule wants to add. Return an empty list if no
        enrichment applies."""
        ...

    @abstractmethod
    def apply(self, rows: list[dict]) -> list[dict]:
        """Return a new list of row dicts with derived column values added.
        Must only be called after detect() returned a non-empty list."""
        ...
