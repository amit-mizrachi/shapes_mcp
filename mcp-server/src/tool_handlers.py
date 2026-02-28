import json
import logging
from datetime import date
from typing import Optional, Union

from mcp.server.fastmcp import Context

from shared.config import Config
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.transform_expression import TransformExpression
from shared.modules.data.query_result import QueryResult
from data_store.interfaces.data_store import DataStore

logger = logging.getLogger(__name__)


def _validate_order(order: str) -> str:
    """Return normalized order or raise ValueError."""
    normalized = order.lower()
    if normalized not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'")
    return normalized


def _clamp_limit(limit: int) -> int:
    max_limit = Config.get("mcp_server.max_query_limit")
    return max(1, min(limit, max_limit))


def _format_query_response(query_result: QueryResult) -> str:
    response = {"data": query_result.rows, "count": query_result.count}
    if query_result.total_count is not None:
        response["total_count"] = query_result.total_count
    return json.dumps(response)


def _build_date_context() -> dict:
    epoch_string = Config.get("mcp_server.enrichment.nominal_date_epoch")
    epoch = date.fromisoformat(epoch_string)
    today_nominal = (date.today() - epoch).days
    return {
        "nominal_date_epoch": epoch_string,
        "today_as_nominal_days": today_nominal,
    }


async def _execute_query(tool_name: str, coro) -> str:
    try:
        query_result = await coro
    except ValueError as error:
        logger.warning("%s validation error: %s", tool_name, error)
        return json.dumps({"error": str(error)})
    except Exception as error:
        logger.error("%s failed unexpectedly", tool_name, exc_info=True)
        return json.dumps({"error": f"Internal error: {error}"})
    return _format_query_response(query_result)


async def get_schema(context: Context) -> str:
    """Return the database schema: table name, column names, detected types, and sample values.

    CAPABILITIES: discover table structure, column names, data types, sample values.
    Use this tool FIRST to understand what data is available before querying.
    Takes no parameters.
    """
    try:
        data_store = _get_data_store(context)
        schema = await data_store.get_schema()
    except Exception as error:
        logger.error("get_schema failed unexpectedly", exc_info=True)
        return json.dumps({"error": f"Internal error: {error}"})
    if schema is None:
        logger.warning("get_schema called but no data is loaded")
        return json.dumps({"error": "No data loaded"})
    return json.dumps(
        {
            "table": schema.table_name,
            "date_context": _build_date_context(),
            "columns": [
                {"name": column.name, "detected_type": column.detected_type, "samples": column.samples}
                for column in schema.columns
            ],
        },
        indent=2,
    )

async def select_rows(
    filters: Optional[list[FilterCondition]] = None,
    fields: Optional[list[str]] = None,
    limit: int = Config.get("mcp_server.default_query_limit"),
    order_by: Optional[str] = None,
    order: str = "asc",
    distinct: bool = False,
    transform: Optional[TransformExpression] = None,
    filter_logic: str = "AND",
    context: Context = None,
) -> str:
    """Retrieve rows from the data table.

    CAPABILITIES: row retrieval, filtering (AND/OR), sorting, distinct values, conditional value transformation (for normalizing mixed units/currencies).

    - fields: list of column names to return (default: all columns).
    - filters: list of filter objects. Each has:
        - "column": column name
        - "operator": one of "=", "!=", ">", ">=", "<", "<=", "LIKE", "NOT LIKE", "IN", "NOT IN", "IS NULL", "IS NOT NULL" (default "=")
        - "value": the value to compare against. For IN, pass a list of values.
      Example: [{"column": "age", "operator": ">", "value": 30}, {"column": "city", "value": "London"}]
      LIKE example: [{"column": "name", "operator": "LIKE", "value": "%son%"}]
      IN example: [{"column": "city", "operator": "IN", "value": ["London", "Paris"]}]
    - limit: max rows to return (default 20, max 100).
    - order_by: column name to sort results by (or the transform alias to sort by the computed column).
    - order: "asc" or "desc" (default "asc").
    - distinct: if true, return only unique combinations of the selected fields.
    - transform: compute a derived column using conditional math (CASE WHEN logic).
      When a value is qualified by MULTIPLE columns (e.g., both unit and frequency), include ALL
      qualifier columns in each case's "when" conditions — do not normalize only one dimension.
      Structure:
        {"source_column": "usage_amount", "cases": [
            {"when": [{"column": "unit", "value": "gallons"}, {"column": "frequency", "value": "Daily"}], "then_multiply": 113.55},
            {"when": [{"column": "unit", "value": "gallons"}, {"column": "frequency", "value": "Monthly"}], "then_multiply": 3.785},
            {"when": [{"column": "unit", "value": "liters"}, {"column": "frequency", "value": "Daily"}], "then_multiply": 30}
        ], "else_multiply": 1, "alias": "monthly_liters"}
      The computed column is added to each row. You can sort by the alias via order_by.
    - filter_logic: "AND" (default) or "OR". Controls how multiple filters are combined.
      Example: filter_logic="OR" with two filters means rows matching EITHER filter are returned.
    """
    logger.info("Executing row selection tool")
    data_store = _get_data_store(context)

    async def _query():
        validated_order = _validate_order(order)
        clamped_limit = _clamp_limit(limit)
        return await data_store.select_rows(
            filters=filters, fields=fields, limit=clamped_limit,
            order_by=order_by, order=validated_order, distinct=distinct, transform=transform,
            filter_logic=filter_logic,
        )

    return await _execute_query("select_rows", _query())


async def aggregate(
    operation: str,
    field: Optional[str] = None,
    group_by: Optional[Union[str, list[str]]] = None,
    filters: Optional[list[FilterCondition]] = None,
    limit: int = Config.get("mcp_server.default_query_limit"),
    order_by: Optional[str] = None,
    order: str = "desc",
    having_operator: Optional[str] = None,
    having_value: Optional[float] = None,
    transform: Optional[TransformExpression] = None,
    filter_logic: str = "AND",
    context: Context = None,
) -> str:
    """Run an aggregation on the data table.

    CAPABILITIES: count/sum/avg/min/max, group-by (single or multi-column), HAVING filters, conditional value transformation (for normalizing mixed units/currencies before aggregating), sort by aggregated result (@result).

    - operation: one of "count", "sum", "avg", "min", "max".
    - field: column to aggregate (not required for "count", or when using transform).
    - group_by: column name or list of column names to group results by.
      Example: "city" or ["city", "job"] for multi-column grouping.
    - filters: list of filter objects, same format as select_rows.
      Example: [{"column": "age", "operator": ">=", "value": 18}]
    - limit: max groups to return when using group_by (default 20, max 100).
    - order_by: column name to sort grouped results by, or "@result" to sort by the
      aggregated value (e.g. count, sum, avg). Only applies when group_by is used.
      Example: to get the top 5 cities by count, use
      group_by="city", order_by="@result", order="desc", limit=5.
    - order: "asc" or "desc" (default "desc").
    - having_operator: comparison operator for filtering groups by the aggregated result.
      One of "=", "!=", ">", ">=", "<", "<=". Only applies when group_by is used.
    - having_value: numeric threshold for the HAVING filter. Use with having_operator.
      Example: to find jobs with more than 5 people, use
      operation="count", group_by="job", having_operator=">", having_value=5.
    - transform: compute a derived value using conditional math (CASE WHEN) before aggregating.
      When using transform, the 'field' parameter is not needed — the source column is inside the transform.
      When a value is qualified by MULTIPLE columns (e.g., both unit and frequency), include ALL
      qualifier columns in each case's "when" conditions — do not normalize only one dimension.
      Structure:
        {"source_column": "usage_amount", "cases": [
            {"when": [{"column": "unit", "value": "gallons"}, {"column": "frequency", "value": "Daily"}], "then_multiply": 113.55},
            {"when": [{"column": "unit", "value": "gallons"}, {"column": "frequency", "value": "Monthly"}], "then_multiply": 3.785},
            {"when": [{"column": "unit", "value": "liters"}, {"column": "frequency", "value": "Daily"}], "then_multiply": 30}
        ], "else_multiply": 1, "alias": "monthly_liters"}
      Example: to get average monthly usage by region:
      operation="avg", transform={...as above...}, group_by="region", order_by="@result", order="desc".
    - filter_logic: "AND" (default) or "OR". Controls how multiple filters are combined.
    """
    logger.info("Executing aggregation tool")
    data_store = _get_data_store(context)

    async def _query():
        validated_order = _validate_order(order)
        clamped_limit = _clamp_limit(limit)
        return await data_store.aggregate(
            operation=operation, field=field, group_by=group_by, filters=filters, limit=clamped_limit,
            order_by=order_by, order=validated_order, having_operator=having_operator, having_value=having_value,
            transform=transform, filter_logic=filter_logic,
        )

    return await _execute_query("aggregate", _query())

def _get_data_store(context: Context) -> DataStore:
    data_store = context.request_context.lifespan_context.get("data_store")
    if data_store is None:
        logger.error("DataStore not initialized")
        raise RuntimeError("DataStore not initialized")
    return data_store
