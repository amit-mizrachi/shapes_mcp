from __future__ import annotations

from pydantic import ConfigDict, model_validator

from shared.modules.shapes_base_model import ShapesBaseModel

VALID_OPERATORS = frozenset({"=", ">", ">=", "<", "<=", "LIKE", "IN"})


class FilterCondition(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    column: str
    op: str = "="
    value: str | int | float | list = ""

    @model_validator(mode="after")
    def _validate(self) -> FilterCondition:
        if not self.column or not isinstance(self.column, str):
            raise ValueError(
                f"FilterCondition 'column' must be a non-empty string. Got: {self.column!r}"
            )
        if self.op not in VALID_OPERATORS:
            raise ValueError(
                f"Invalid filter operator '{self.op}'. Must be one of: {sorted(VALID_OPERATORS)}"
            )
        if self.op == "IN":
            if not isinstance(self.value, list) or len(self.value) == 0:
                raise ValueError(
                    f"IN operator requires a non-empty list for 'value'. Got: {self.value!r}"
                )
        elif self.op == "LIKE":
            if not isinstance(self.value, str):
                raise ValueError(
                    f"LIKE operator requires a string 'value'. Got: {self.value!r}"
                )
        return self
