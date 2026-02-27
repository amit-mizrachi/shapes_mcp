from pydantic import ConfigDict

from shared.modules.data.column_info import ColumnInfo
from shared.modules.shapes_base_model import ShapesBaseModel


class TableSchema(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    table_name: str
    columns: list[ColumnInfo]
