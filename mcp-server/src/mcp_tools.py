from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import Context

from shared.config import Config
from shared.modules.data.filter_condition import FilterCondition
from repository.data_repository_protocol import DataRepositoryProtocol

logger = logging.getLogger(__name__)


async def get_schema(context: Context) -> str:
    """Return the database schema: table name, column names, detected types, and sample values.

    Use this tool FIRST to understand what data is available before querying.
    Takes no parameters.
    """
    repository = _get_repository(context)
    schema = await repository.get_schema()
    if schema is None:
        logger.warning("get_schema called but no data is loaded")
        return json.dumps({"error": "No data loaded"})
    return json.dumps(
        {
            "table": schema.table_name,
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
    limit: int = Config.get("shared.default_query_limit"),
    order_by: str | None = None,
    order: str = "asc",
    distinct: bool = False,
    context: Context = None,
) -> str:
    """Retrieve rows from the data table.

    - fields: list of column names to return (default: all columns).
    - filters: list of filter objects. Each has:
        - "column": column name
        - "op": one of "=", ">", ">=", "<", "<=", "LIKE", "IN" (default "=")
        - "value": the value to compare against. For IN, pass a list of values.
      Example: [{"column": "age", "op": ">", "value": 30}, {"column": "city", "value": "London"}]
      LIKE example: [{"column": "name", "op": "LIKE", "value": "%son%"}]
      IN example: [{"column": "city", "op": "IN", "value": ["London", "Paris"]}]
    - limit: max rows to return (default 20, max 100).
    - order_by: column name to sort results by.
    - order: "asc" or "desc" (default "asc").
    - distinct: if true, return only unique combinations of the selected fields.
    """
    logger.info("Executing row selection tool")
    repository = _get_repository(context)
    order = order.lower()
    if order not in ("asc", "desc"):
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    try:
        query_result = await repository.select_rows(
            filters=filters, fields=fields, limit=limit,
            order_by=order_by, order=order, distinct=distinct,
        )
    except ValueError as e:
        logger.warning("select_rows validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})


async def aggregate(
    operation: str,
    field: str | None = None,
    group_by: str | None = None,
    filters: list[FilterCondition] | None = None,
    limit: int = Config.get("shared.default_query_limit"),
    order_by: str | None = None,
    order: str = "desc",
    context: Context = None,
) -> str:
    """Run an aggregation on the data table.

    - operation: one of "count", "sum", "avg", "min", "max".
    - field: column to aggregate (not required for "count").
    - group_by: optional column to group results by.
    - filters: list of filter objects, same format as select_rows.
      Example: [{"column": "age", "op": ">=", "value": 18}]
    - limit: max groups to return when using group_by (default 20, max 100).
    - order_by: column to sort grouped results by — the group column name or "result" (default "result"). Only applies when group_by is used.
    - order: "asc" or "desc" (default "desc").
    """
    logger.info("Executing aggregation tool")
    repository = _get_repository(context)
    order = order.lower()
    if order not in ("asc", "desc"):
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    try:
        query_result = await repository.aggregate(
            operation=operation, field=field, group_by=group_by, filters=filters, limit=limit,
            order_by=order_by, order=order,
        )
    except ValueError as e:
        logger.warning("aggregate validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})

def _get_repository(context: Context) -> DataRepositoryProtocol:
    repository = context.request_context.lifespan_context.get("repository")
    if repository is None:
        logger.error("Repository not initialized")
        raise RuntimeError("Repository not initialized")
    return repository
