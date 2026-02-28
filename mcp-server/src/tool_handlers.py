import json
import logging
from datetime import date

from mcp.server.fastmcp import Context

from shared.config import Config
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.transform_expression import TransformExpression
from shared.modules.data.query_result import QueryResult
from data_store.data_store import DataStore

logger = logging.getLogger(__name__)


def _validate_order(order: str) -> str | None:
    """Return normalized order or None if invalid."""
    order = order.lower()
    return order if order in ("asc", "desc") else None


def _clamp_limit(limit: int) -> int:
    max_limit = Config.get("mcp_server.max_query_limit")
    return max(1, min(limit, max_limit))


def _format_query_response(query_result: QueryResult) -> str:
    response = {"data": query_result.rows, "count": query_result.count}
    if query_result.total_count is not None:
        response["total_count"] = query_result.total_count
    return json.dumps(response)


async def get_schema(context: Context) -> str:
    """Return the database schema: table name, column names, detected types, and sample values.

    CAPABILITIES: discover table structure, column names, data types, sample values.
    Use this tool FIRST to understand what data is available before querying.
    Takes no parameters.
    """
    try:
        data_store = _get_data_store(context)
        schema = await data_store.get_schema()
    except Exception as e:
        logger.error("get_schema failed unexpectedly", exc_info=True)
        return json.dumps({"error": f"Internal error: {e}"})
    if schema is None:
        logger.warning("get_schema called but no data is loaded")
        return json.dumps({"error": "No data loaded"})
    epoch_str = Config.get("mcp_server.enrichment.nominal_date_epoch")
    epoch = date.fromisoformat(epoch_str)
    today_nominal = (date.today() - epoch).days

    return json.dumps(
        {
            "table": schema.table_name,
            "date_context": {
                "nominal_date_epoch": epoch_str,
                "today_as_nominal_days": today_nominal,
            },
            "columns": [
                {"name": c.name, "detected_type": c.detected_type, "samples": c.samples}
                for c in schema.columns
            ],
        },
        indent=2,
    )

async def select_rows(
    filters: list[FilterCondition] | None = None,
    fields: list[str] | None = None,
    limit: int = Config.get("mcp_server.default_query_limit"),
    order_by: str | None = None,
    order: str = "asc",
    distinct: bool = False,
    transform: TransformExpression | None = None,
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
    - transform: compute a derived column using conditional math (CASE WHEN logic). Structure:
        {"source_column": "salary_amount", "cases": [
            {"when": [{"column": "salary_type", "value": "Monthly"}], "then_multiply": 12},
            {"when": [{"column": "salary_type", "value": "Hourly"}], "then_multiply": 2080}
        ], "else_multiply": 1, "alias": "annual_salary"}
      The computed column is added to each row. You can sort by the alias via order_by.
    - filter_logic: "AND" (default) or "OR". Controls how multiple filters are combined.
      Example: filter_logic="OR" with two filters means rows matching EITHER filter are returned.
    """
    logger.info("Executing row selection tool")
    data_store = _get_data_store(context)
    order = _validate_order(order)
    if order is None:
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    limit = _clamp_limit(limit)
    try:
        query_result = await data_store.select_rows(
            filters=filters, fields=fields, limit=limit,
            order_by=order_by, order=order, distinct=distinct, transform=transform,
            filter_logic=filter_logic,
        )
    except ValueError as e:
        logger.warning("select_rows validation error: %s", e)
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error("select_rows failed unexpectedly", exc_info=True)
        return json.dumps({"error": f"Internal error: {e}"})
    return _format_query_response(query_result)


async def aggregate(
    operation: str,
    field: str | None = None,
    group_by: str | list[str] | None = None,
    filters: list[FilterCondition] | None = None,
    limit: int = Config.get("mcp_server.default_query_limit"),
    order_by: str | None = None,
    order: str = "desc",
    having_operator: str | None = None,
    having_value: float | None = None,
    transform: TransformExpression | None = None,
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
      Structure: {"source_column": "salary_amount", "cases": [
          {"when": [{"column": "salary_type", "value": "Monthly"}], "then_multiply": 12},
          {"when": [{"column": "salary_type", "value": "Hourly"}], "then_multiply": 2080}
      ], "else_multiply": 1, "alias": "annual_salary"}
      Example: to get average annual salary by city (normalizing Hourly/Monthly/Yearly):
      operation="avg", transform={...as above...}, group_by="city", order_by="@result", order="desc".
    - filter_logic: "AND" (default) or "OR". Controls how multiple filters are combined.
    """
    logger.info("Executing aggregation tool")
    data_store = _get_data_store(context)
    order = _validate_order(order)
    if order is None:
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    limit = _clamp_limit(limit)
    try:
        query_result = await data_store.aggregate(
            operation=operation, field=field, group_by=group_by, filters=filters, limit=limit,
            order_by=order_by, order=order, having_operator=having_operator, having_value=having_value,
            transform=transform, filter_logic=filter_logic,
        )
    except ValueError as e:
        logger.warning("aggregate validation error: %s", e)
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error("aggregate failed unexpectedly", exc_info=True)
        return json.dumps({"error": f"Internal error: {e}"})
    return _format_query_response(query_result)

def _get_data_store(context: Context) -> DataStore:
    data_store = context.request_context.lifespan_context.get("data_store")
    if data_store is None:
        logger.error("DataStore not initialized")
        raise RuntimeError("DataStore not initialized")
    return data_store
