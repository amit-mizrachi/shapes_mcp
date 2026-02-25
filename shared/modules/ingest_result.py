from __future__ import annotations

from dataclasses import dataclass

from shared.modules.column_info import ColumnInfo


@dataclass(frozen=True)
class IngestResult:
    table_name: str
    columns: list[ColumnInfo]
