"""Tests for shared.modules.filter_condition.FilterCondition."""

import pytest
from pydantic import ValidationError

from shared.modules.data.filter_condition import FilterCondition


class TestFilterCondition:
    def test_basic_creation(self):
        f = FilterCondition(column="age", operator=">", value=30)
        assert f.column == "age"
        assert f.operator == ">"
        assert f.value == 30

    def test_defaults(self):
        f = FilterCondition(column="name")
        assert f.operator == "="
        assert f.value == ""

    def test_frozen(self):
        f = FilterCondition(column="age", operator="=", value=25)
        with pytest.raises(ValidationError):
            f.column = "name"

    def test_equality(self):
        a = FilterCondition(column="x", operator="=", value=1)
        b = FilterCondition(column="x", operator="=", value=1)
        assert a == b

    def test_string_value(self):
        f = FilterCondition(column="city", operator="=", value="London")
        assert f.value == "London"

    def test_float_value(self):
        f = FilterCondition(column="score", operator=">=", value=90.5)
        assert f.value == 90.5
