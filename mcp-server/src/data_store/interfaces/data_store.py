from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Union

from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.table_schema import TableSchema
from shared.modules.data.query_result import QueryResult
from shared.modules.data.transform_expression import TransformExpression


class DataStore(ABC):
    @abstractmethod
    async def get_schema(self) -> Optional[TableSchema]: ...

    @abstractmethod
    async def select_rows(
        self,
        filters: Optional[list[FilterCondition]] = None,
        fields: Optional[list[str]] = None,
        limit: int = 20,
        order_by: Optional[str] = None,
        order: str = "asc",
        distinct: bool = False,
        transform: Optional[TransformExpression] = None,
        filter_logic: str = "AND",
    ) -> QueryResult: ...

    @abstractmethod
    async def aggregate(
        self,
        operation: str,
        field: Optional[str] = None,
        group_by: Optional[Union[str, list[str]]] = None,
        filters: Optional[list[FilterCondition]] = None,
        limit: int = 20,
        order_by: Optional[str] = None,
        order: str = "desc",
        having_operator: Optional[str] = None,
        having_value: Optional[float] = None,
        transform: Optional[TransformExpression] = None,
        filter_logic: str = "AND",
    ) -> QueryResult: ...
