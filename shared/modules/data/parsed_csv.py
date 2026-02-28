from __future__ import annotations

from pydantic import ConfigDict

from shared.modules.data.column_info import ColumnInfo
from shared.modules.shapes_base_model import ShapesBaseModel


class ParsedCSV(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    table_name: str
    columns: list[ColumnInfo]
    rows: list[dict]

    @property
    def headers(self) -> list[str]:
        return [column.name for column in self.columns]
