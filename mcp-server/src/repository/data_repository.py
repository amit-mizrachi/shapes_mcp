from __future__ import annotations

from typing import Protocol, runtime_checkable

from shared.modules.filter_condition import FilterCondition
from shared.modules.table_schema import TableSchema
from shared.modules.query_result import QueryResult


@runtime_checkable
class DataRepository(Protocol):
    async def get_schema(self) -> TableSchema | None: ...

    async def select_rows(
        self,
        filters: list[FilterCondition] | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
        order_by: str | None = None,
        order: str = "asc",
        distinct: bool = False,
    ) -> QueryResult: ...

    async def aggregate(
        self,
        operation: str,
        field: str | None = None,
        group_by: str | None = None,
        filters: list[FilterCondition] | None = None,
        limit: int = 20,
        order_by: str | None = None,
        order: str = "desc",
    ) -> QueryResult: ...
