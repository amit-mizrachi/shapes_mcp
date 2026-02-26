"""Tests for shared.modules.column_info.ColumnInfo."""

import pytest
from pydantic import ValidationError

from shared.modules.data.column_info import ColumnInfo


class TestColumnInfo:
    def test_basic_creation(self):
        col = ColumnInfo(name="age", detected_type="numeric", samples=["25", "30"])
        assert col.name == "age"
        assert col.detected_type == "numeric"
        assert col.samples == ["25", "30"]

    def test_default_samples(self):
        col = ColumnInfo(name="name", detected_type="text")
        assert col.samples == []

    def test_frozen(self):
        col = ColumnInfo(name="age", detected_type="numeric")
        with pytest.raises(ValidationError):
            col.name = "new_name"

    def test_equality(self):
        a = ColumnInfo(name="x", detected_type="text", samples=["a"])
        b = ColumnInfo(name="x", detected_type="text", samples=["a"])
        assert a == b

    def test_inequality(self):
        a = ColumnInfo(name="x", detected_type="text")
        b = ColumnInfo(name="y", detected_type="text")
        assert a != b
