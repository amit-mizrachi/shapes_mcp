from __future__ import annotations

from abc import ABC, abstractmethod

from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.table_schema import TableSchema
from shared.modules.data.query_result import QueryResult


class DataStore(ABC):
    @abstractmethod
    async def get_schema(self) -> TableSchema | None: ...

    @abstractmethod
    async def select_rows(
        self,
        filters: list[FilterCondition] | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
        order_by: str | None = None,
        order: str = "asc",
        distinct: bool = False,
    ) -> QueryResult: ...

    @abstractmethod
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
