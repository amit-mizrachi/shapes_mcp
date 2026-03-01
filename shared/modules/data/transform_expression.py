from __future__ import annotations

import re
from typing import Optional

from pydantic import ConfigDict, Field, model_validator

from shared.modules.shapes_base_model import ShapesBaseModel
from shared.modules.data.transform_case import TransformCase

_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_CASES = 10
_MAX_CONSTANT = 1_000_000


class TransformExpression(ShapesBaseModel):
    """Compute a derived column using conditional math (CASE WHEN logic) before aggregating or selecting.

    Use this to normalize mixed units, currencies, or categories into a single comparable value.
    """
    model_config = ConfigDict(frozen=True)

    source_column: str = Field(description="The numeric column to transform.")
    cases: list[TransformCase] = Field(description="List of conditional branches. Each applies a multiplier or constant when its conditions match.")
    else_multiply: Optional[float] = Field(default=None, description="Default multiplier when no case matches (e.g. 1 to keep the value unchanged).")
    else_value: Optional[float] = Field(default=None, description="Default constant when no case matches.")
    alias: str = Field(description="Name for the computed column in results.")

    @model_validator(mode="after")
    def _validate(self) -> TransformExpression:
        if not self.cases:
            raise ValueError("'cases' must contain at least one TransformCase.")
        if len(self.cases) > _MAX_CASES:
            raise ValueError(f"Maximum {_MAX_CASES} cases allowed, got {len(self.cases)}.")
        if not _ALIAS_PATTERN.match(self.alias):
            raise ValueError(f"Invalid alias: {self.alias!r}. Must be lowercase alphanumeric/underscores, start with a letter.")
        if self.else_multiply is not None and self.else_value is not None:
            raise ValueError("Specify either 'else_multiply' or 'else_value', not both.")
        if self.else_multiply is not None and abs(self.else_multiply) > _MAX_CONSTANT:
            raise ValueError(f"else_multiply magnitude exceeds limit: {self.else_multiply}")
        if self.else_value is not None and abs(self.else_value) > _MAX_CONSTANT:
            raise ValueError(f"else_value magnitude exceeds limit: {self.else_value}")
        return self
