from __future__ import annotations

from pydantic import ConfigDict

from shared.modules.shapes_base_model import ShapesBaseModel


class ColumnInfo(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    detected_type: str
    samples: list[str] = []
