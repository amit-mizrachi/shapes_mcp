from __future__ import annotations

import re

from pydantic import ConfigDict, model_validator

from shared.modules.shapes_base_model import ShapesBaseModel
from shared.modules.data.filter_condition import FilterCondition

_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_CASES = 10
_MAX_CONSTANT = 1_000_000


class TransformCase(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    when: list[FilterCondition]
    then_multiply: float | None = None
    then_value: float | None = None

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


class TransformExpression(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    source_column: str
    cases: list[TransformCase]
    else_multiply: float | None = None
    else_value: float | None = None
    alias: str

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
