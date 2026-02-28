"""Tests for SqliteQueryBuilder — pure SQL generation, no I/O."""

import pytest

from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.table_schema import TableSchema
from shared.modules.data.transform_expression import TransformExpression
from data_store.sqlite_query_builder import SqliteQueryBuilder


@pytest.fixture()
def schema():
    return TableSchema(
        table_name="employees",
        columns=[
            ColumnInfo(name="name", detected_type="text"),
            ColumnInfo(name="age", detected_type="numeric"),
            ColumnInfo(name="city", detected_type="text"),
            ColumnInfo(name="salary", detected_type="numeric"),
            ColumnInfo(name="active", detected_type="text"),
        ],
    )


@pytest.fixture()
def builder(schema):
    return SqliteQueryBuilder(schema)


class TestBuildSelect:
    def test_select_all_columns(self, builder):
        q = builder.build_select(limit=10)
        assert "SELECT *" in q.sql
        assert "LIMIT ?" in q.sql
        assert q.params == [10]

    def test_select_specific_fields(self, builder):
        q = builder.build_select(fields=["name", "age"], limit=10)
        assert '"name", "age"' in q.sql
        assert "*" not in q.sql

    def test_invalid_field_raises(self, builder):
        with pytest.raises(ValueError, match="not found"):
            builder.build_select(fields=["nonexistent"], limit=10)

    def test_distinct(self, builder):
        q = builder.build_select(distinct=True, limit=10)
        assert "DISTINCT" in q.sql

    def test_order_by(self, builder):
        q = builder.build_select(order_by="age", order="desc", limit=10)
        assert 'ORDER BY "age" DESC' in q.sql

    def test_invalid_order_direction_raises(self, builder):
        with pytest.raises(ValueError, match="order"):
            builder.build_select(order_by="age", order="sideways", limit=10)

    def test_count_query_returned(self, builder):
        q = builder.build_select(limit=10)
        assert "COUNT(*)" in q.count_sql
        assert q.count_params == []

    def test_count_query_with_filter(self, builder):
        filters = [FilterCondition(column="city", operator="=", value="NYC")]
        q = builder.build_select(filters=filters, limit=10)
        assert "COUNT(*)" in q.count_sql
        assert "WHERE" in q.count_sql
        assert q.count_params == ["NYC"]

    def test_count_query_with_distinct(self, builder):
        q = builder.build_select(distinct=True, fields=["city"], limit=10)
        assert "DISTINCT" in q.count_sql

    def test_transform_adds_computed_column(self, builder):
        transform = TransformExpression(
            source_column="salary",
            cases=[{"when": [{"column": "active", "value": "true"}], "then_multiply": 2.0}],
            else_multiply=1.0,
            alias="adjusted",
        )
        q = builder.build_select(transform=transform, limit=10)
        assert 'AS "adjusted"' in q.sql
        assert "CASE" in q.sql

    def test_order_by_transform_alias(self, builder):
        transform = TransformExpression(
            source_column="salary",
            cases=[{"when": [{"column": "active", "value": "true"}], "then_multiply": 2.0}],
            alias="adjusted",
        )
        q = builder.build_select(transform=transform, order_by="adjusted", order="desc", limit=10)
        assert 'ORDER BY "adjusted" DESC' in q.sql

    def test_invalid_transform_column_raises(self, builder):
        transform = TransformExpression(
            source_column="nonexistent",
            cases=[{"when": [{"column": "active", "value": "true"}], "then_multiply": 1.0}],
            alias="bad",
        )
        with pytest.raises(ValueError, match="not found"):
            builder.build_select(transform=transform, limit=10)


class TestBuildAggregate:
    def test_count_all(self, builder):
        q = builder.build_aggregate(operation="count", limit=20)
        assert "COUNT(*)" in q.sql

    def test_count_case_insensitive(self, builder):
        q = builder.build_aggregate(operation="COUNT", limit=20)
        assert "COUNT(*)" in q.sql

    def test_sum_with_field(self, builder):
        q = builder.build_aggregate(operation="sum", field="salary", limit=20)
        assert 'SUM("salary")' in q.sql

    def test_sum_without_field_raises(self, builder):
        with pytest.raises(ValueError, match="field.*required"):
            builder.build_aggregate(operation="sum", limit=20)

    def test_invalid_operation_raises(self, builder):
        with pytest.raises(ValueError, match="Unsupported"):
            builder.build_aggregate(operation="MEDIAN", field="age", limit=20)

    def test_invalid_field_raises(self, builder):
        with pytest.raises(ValueError, match="not found"):
            builder.build_aggregate(operation="sum", field="ghost", limit=20)

    def test_group_by_string(self, builder):
        q = builder.build_aggregate(operation="count", group_by="city", limit=20)
        assert "GROUP BY" in q.sql
        assert '"city"' in q.sql

    def test_group_by_list(self, builder):
        q = builder.build_aggregate(operation="count", group_by=["city", "active"], limit=20)
        assert '"city"' in q.sql
        assert '"active"' in q.sql
        assert "GROUP BY" in q.sql

    def test_invalid_group_by_column_raises(self, builder):
        with pytest.raises(ValueError, match="not found"):
            builder.build_aggregate(operation="count", group_by="nonexistent", limit=20)

    def test_having_clause(self, builder):
        q = builder.build_aggregate(
            operation="count", group_by="city",
            having_operator=">=", having_value=5, limit=20,
        )
        assert "HAVING result >= ?" in q.sql
        assert 5 in q.params

    def test_having_without_group_by_raises(self, builder):
        with pytest.raises(ValueError, match="group_by"):
            builder.build_aggregate(operation="count", having_value=1, limit=20)

    def test_invalid_having_op_raises(self, builder):
        with pytest.raises(ValueError, match="having_operator"):
            builder.build_aggregate(
                operation="count", group_by="city",
                having_operator="LIKE", having_value=1, limit=20,
            )

    def test_order_by_result_sentinel(self, builder):
        q = builder.build_aggregate(
            operation="count", group_by="city",
            order_by="@result", order="desc", limit=20,
        )
        assert "ORDER BY result DESC" in q.sql

    def test_aggregate_without_group_by_no_limit(self, builder):
        q = builder.build_aggregate(operation="count", limit=20)
        assert "LIMIT" not in q.sql

    def test_aggregate_with_transform(self, builder):
        transform = TransformExpression(
            source_column="salary",
            cases=[{"when": [{"column": "active", "value": "true"}], "then_multiply": 2.0}],
            else_multiply=1.0,
            alias="adjusted",
        )
        q = builder.build_aggregate(operation="sum", transform=transform, limit=20)
        assert "SUM(CASE" in q.sql


class TestFilterExpressions:
    def test_equality(self, builder):
        filters = [FilterCondition(column="name", operator="=", value="Alice")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" = ?' in q.sql
        assert "Alice" in q.params

    def test_not_equal(self, builder):
        filters = [FilterCondition(column="name", operator="!=", value="Alice")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" != ?' in q.sql

    def test_greater_than(self, builder):
        filters = [FilterCondition(column="age", operator=">", value=30)]
        q = builder.build_select(filters=filters, limit=10)
        assert '"age" > ?' in q.sql
        assert 30 in q.params

    def test_like(self, builder):
        filters = [FilterCondition(column="name", operator="LIKE", value="%li%")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" LIKE ?' in q.sql

    def test_not_like(self, builder):
        filters = [FilterCondition(column="name", operator="NOT LIKE", value="%li%")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" NOT LIKE ?' in q.sql

    def test_in_filter(self, builder):
        filters = [FilterCondition(column="city", operator="IN", value=["NYC", "LA"])]
        q = builder.build_select(filters=filters, limit=10)
        assert '"city" IN (?,?)' in q.sql
        assert "NYC" in q.params
        assert "LA" in q.params

    def test_not_in_filter(self, builder):
        filters = [FilterCondition(column="city", operator="NOT IN", value=["NYC"])]
        q = builder.build_select(filters=filters, limit=10)
        assert '"city" NOT IN (?)' in q.sql

    def test_is_null(self, builder):
        filters = [FilterCondition(column="name", operator="IS NULL")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" IS NULL' in q.sql

    def test_is_not_null(self, builder):
        filters = [FilterCondition(column="name", operator="IS NOT NULL")]
        q = builder.build_select(filters=filters, limit=10)
        assert '"name" IS NOT NULL' in q.sql

    def test_or_logic(self, builder):
        filters = [
            FilterCondition(column="name", operator="=", value="Alice"),
            FilterCondition(column="name", operator="=", value="Bob"),
        ]
        q = builder.build_select(filters=filters, filter_logic="OR", limit=10)
        assert " OR " in q.sql

    def test_and_logic_default(self, builder):
        filters = [
            FilterCondition(column="name", operator="=", value="Alice"),
            FilterCondition(column="age", operator=">", value=30),
        ]
        q = builder.build_select(filters=filters, limit=10)
        assert " AND " in q.sql

    def test_invalid_filter_logic_raises(self, builder):
        filters = [FilterCondition(column="name", operator="=", value="x")]
        with pytest.raises(ValueError, match="filter_logic"):
            builder.build_select(filters=filters, filter_logic="XOR", limit=10)

    def test_invalid_filter_column_raises(self, builder):
        filters = [FilterCondition(column="bad_col", operator="=", value="x")]
        with pytest.raises(ValueError, match="not found"):
            builder.build_select(filters=filters, limit=10)
