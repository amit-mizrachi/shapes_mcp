from __future__ import annotations

from abc import ABC, abstractmethod

from shared.modules.data.column_info import ColumnInfo


class EnrichmentRule(ABC):
    @abstractmethod
    def infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]:
        """Examine existing columns and return new ColumnInfo objects for
        columns this rule wants to add. Return an empty list if no
        enrichment applies."""
        ...

    @abstractmethod
    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        """Return rows with derived column values added. Rules may mutate
        the input rows in-place; the caller is responsible for copying
        if the originals must be preserved.
        Must only be called after infer_derived_columns() returned a non-empty list."""
        ...
