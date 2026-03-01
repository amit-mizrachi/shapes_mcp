"""Tests for shared.modules.data.transform_expression — Pydantic model validation."""

import pytest
from pydantic import ValidationError

from shared.modules.data.transform_case import TransformCase
from shared.modules.data.transform_expression import TransformExpression


def _case(*, column="score", value="high", then_multiply=None, then_value=None):
    """Shortcut to build a single TransformCase dict."""
    case = {"when": [{"column": column, "value": value}]}
    if then_multiply is not None:
        case["then_multiply"] = then_multiply
    if then_value is not None:
        case["then_value"] = then_value
    return case


class TestTransformCase:
    def test_valid_with_then_multiply(self):
        tc = TransformCase(when=[{"column": "x", "value": "a"}], then_multiply=2.0)
        assert tc.then_multiply == 2.0
        assert tc.then_value is None

    def test_valid_with_then_value(self):
        tc = TransformCase(when=[{"column": "x", "value": "a"}], then_value=100.0)
        assert tc.then_value == 100.0
        assert tc.then_multiply is None

    def test_empty_when_raises(self):
        with pytest.raises(ValidationError, match="at least one filter"):
            TransformCase(when=[], then_multiply=2.0)

    def test_both_then_multiply_and_then_value_raises(self):
        with pytest.raises(ValidationError, match="not both"):
            TransformCase(when=[{"column": "x", "value": "a"}], then_multiply=2.0, then_value=100.0)

    def test_neither_then_multiply_nor_then_value_raises(self):
        with pytest.raises(ValidationError, match="then_multiply.*or.*then_value"):
            TransformCase(when=[{"column": "x", "value": "a"}])

    def test_magnitude_limit_then_multiply(self):
        with pytest.raises(ValidationError, match="magnitude exceeds limit"):
            TransformCase(when=[{"column": "x", "value": "a"}], then_multiply=2_000_000)

    def test_magnitude_limit_then_value(self):
        with pytest.raises(ValidationError, match="magnitude exceeds limit"):
            TransformCase(when=[{"column": "x", "value": "a"}], then_value=-2_000_000)


class TestTransformExpression:
    def test_valid_with_then_multiply(self):
        te = TransformExpression(
            source_column="score",
            cases=[_case(then_multiply=2.0)],
            alias="doubled",
        )
        assert te.source_column == "score"
        assert te.alias == "doubled"
        assert len(te.cases) == 1

    def test_valid_with_then_value(self):
        te = TransformExpression(
            source_column="score",
            cases=[_case(then_value=50.0)],
            alias="fixed",
        )
        assert te.cases[0].then_value == 50.0

    def test_empty_cases_raises(self):
        with pytest.raises(ValidationError, match="at least one"):
            TransformExpression(source_column="score", cases=[], alias="bad")

    def test_too_many_cases_raises(self):
        cases = [_case(then_multiply=float(i)) for i in range(1, 12)]
        with pytest.raises(ValidationError, match="Maximum 10"):
            TransformExpression(source_column="score", cases=cases, alias="many")

    def test_invalid_alias_uppercase_raises(self):
        with pytest.raises(ValidationError, match="Invalid alias"):
            TransformExpression(
                source_column="score",
                cases=[_case(then_multiply=2.0)],
                alias="BadAlias",
            )

    def test_invalid_alias_special_chars_raises(self):
        with pytest.raises(ValidationError, match="Invalid alias"):
            TransformExpression(
                source_column="score",
                cases=[_case(then_multiply=2.0)],
                alias="my-alias!",
            )

    def test_both_else_multiply_and_else_value_raises(self):
        with pytest.raises(ValidationError, match="not both"):
            TransformExpression(
                source_column="score",
                cases=[_case(then_multiply=2.0)],
                else_multiply=1.0,
                else_value=0.0,
                alias="bad",
            )

    def test_else_multiply_magnitude_limit_raises(self):
        with pytest.raises(ValidationError, match="magnitude exceeds limit"):
            TransformExpression(
                source_column="score",
                cases=[_case(then_multiply=2.0)],
                else_multiply=2_000_000,
                alias="bad",
            )

    def test_else_value_magnitude_limit_raises(self):
        with pytest.raises(ValidationError, match="magnitude exceeds limit"):
            TransformExpression(
                source_column="score",
                cases=[_case(then_multiply=2.0)],
                else_value=-2_000_000,
                alias="bad",
            )
