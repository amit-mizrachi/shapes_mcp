from __future__ import annotations

from pydantic import ConfigDict, model_validator

from shared.modules.shapes_base_model import ShapesBaseModel

VALID_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "LIKE", "NOT LIKE", "IN", "NOT IN", "IS NULL", "IS NOT NULL"}

_LIST_OPERATORS = {"IN", "NOT IN"}
_STRING_OPERATORS = {"LIKE", "NOT LIKE"}
_NO_VALUE_OPERATORS = {"IS NULL", "IS NOT NULL"}


class FilterCondition(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    column: str
    operator: str = "="
    value: str | int | float | list = ""

    @model_validator(mode="after")
    def _validate(self) -> FilterCondition:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(f"Invalid filter operator '{self.operator}'. Must be one of: {sorted(VALID_OPERATORS)}")
        if self.operator in _LIST_OPERATORS:
            if not isinstance(self.value, list) or len(self.value) == 0:
                raise ValueError(f"{self.operator} operator requires a non-empty list for 'value'. Got: {self.value!r}")
        elif self.operator in _STRING_OPERATORS:
            if not isinstance(self.value, str):
                raise ValueError(f"{self.operator} operator requires a string 'value'. Got: {self.value!r}")

        return self
