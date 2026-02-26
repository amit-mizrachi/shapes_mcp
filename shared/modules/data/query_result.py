from __future__ import annotations

from pydantic import ConfigDict

from shared.modules.shapes_base_model import ShapesBaseModel


class QueryResult(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    columns: list[str]
    rows: list[dict]
    count: int
