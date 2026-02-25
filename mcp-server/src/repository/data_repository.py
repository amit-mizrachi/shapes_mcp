from __future__ import annotations

from typing import Protocol, runtime_checkable

from shared.modules.table_schema import TableSchema
from shared.modules.query_result import QueryResult


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
