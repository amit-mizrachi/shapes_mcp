from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict, Field, model_validator

from shared.modules.shapes_base_model import ShapesBaseModel
from shared.modules.data.filter_condition import FilterCondition

_MAX_CONSTANT = 1_000_000


class TransformCase(ShapesBaseModel):
    """A single CASE WHEN branch: when conditions match, apply a multiplier or constant."""
    model_config = ConfigDict(frozen=True)

    when: list[FilterCondition] = Field(description="Conditions that must all match for this case to apply.")
    then_multiply: Optional[float] = Field(default=None, description="Multiply the source column by this factor when conditions match.")
    then_value: Optional[float] = Field(default=None, description="Replace the source column with this constant when conditions match.")

    @model_validator(mode="after")
    def _validate(self) -> TransformCase:
        if not self.when:
            raise ValueError("'when' must contain at least one filter condition.")
        if self.then_multiply is None and self.then_value is None:
            raise ValueError("Each case must specify 'then_multiply' or 'then_value'.")
        if self.then_multiply is not None and self.then_value is not None:
            raise ValueError("Specify either 'then_multiply' or 'then_value', not both.")
        if self.then_multiply is not None and abs(self.then_multiply) > _MAX_CONSTANT:
            raise ValueError(f"then_multiply magnitude exceeds limit: {self.then_multiply}")
        if self.then_value is not None and abs(self.then_value) > _MAX_CONSTANT:
            raise ValueError(f"then_value magnitude exceeds limit: {self.then_value}")
        return self
