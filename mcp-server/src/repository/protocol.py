from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    detected_type: str
    samples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableSchema:
    table_name: str
    columns: list[ColumnInfo]


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict]
    count: int


@dataclass(frozen=True)
class IngestResult:
    table_name: str
    columns: list[ColumnInfo]
    db_path: str


@runtime_checkable
class DataRepository(Protocol):
    async def get_schema(self) -> TableSchema | None: ...

    async def select_rows(
        self,
        filters: dict[str, str | int | float] | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
    ) -> QueryResult: ...

    async def aggregate(
        self,
        op: str,
        field: str | None = None,
        group_by: str | None = None,
        filters: dict[str, str | int | float] | None = None,
        limit: int = 20,
    ) -> QueryResult: ...
