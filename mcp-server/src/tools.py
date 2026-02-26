from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import Context

from shared.config import Config
from shared.modules.filter_condition import FilterCondition
from repository.data_repository import DataRepository

logger = logging.getLogger(__name__)


def _get_repository(ctx: Context) -> DataRepository:
    repository = ctx.request_context.lifespan_context.get("repository")
    if repository is None:
        logger.error("Repository not initialized")
        raise RuntimeError("Repository not initialized")
    return repository


_VALID_OPS = frozenset({"=", ">", ">=", "<", "<=", "LIKE", "IN"})


def _parse_filters(raw: list[dict] | None) -> list[FilterCondition] | None:
    if not raw:
        return None
    conditions: list[FilterCondition] = []
    for item in raw:
        column = item.get("column")
        if not column or not isinstance(column, str):
            raise ValueError(f"Each filter must have a string 'column'. Got: {item!r}")
        op = item.get("op", "=").upper()
        if op not in _VALID_OPS:
            raise ValueError(f"Invalid filter op '{op}'. Must be one of: {sorted(_VALID_OPS)}")
        value = item.get("value", "")
        if op == "IN":
            if not isinstance(value, list) or len(value) == 0:
                raise ValueError(f"IN operator requires a non-empty list for 'value'. Got: {value!r}")
        elif op == "LIKE":
            if not isinstance(value, str):
                raise ValueError(f"LIKE operator requires a string 'value'. Got: {value!r}")
        conditions.append(FilterCondition(column=column, op=op, value=value))
    return conditions


async def get_schema(ctx: Context) -> str:
    """Return the database schema: table name, column names, detected types, and sample values.

    Use this tool FIRST to understand what data is available before querying.
    Takes no parameters.
    """
    repository = _get_repository(ctx)
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
    filters: list[dict] | None = None,
    fields: list[str] | None = None,
    limit: int = Config.get("shared.default_query_limit"),
    order_by: str | None = None,
    order: str = "asc",
    distinct: bool = False,
    ctx: Context = None,
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
    repository = _get_repository(ctx)
    order = order.lower()
    if order not in ("asc", "desc"):
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    try:
        parsed_filters = _parse_filters(filters)
        query_result = await repository.select_rows(
            filters=parsed_filters, fields=fields, limit=limit,
            order_by=order_by, order=order, distinct=distinct,
        )
    except ValueError as e:
        logger.warning("select_rows validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})


async def aggregate(
    op: str,
    field: str | None = None,
    group_by: str | None = None,
    filters: list[dict] | None = None,
    limit: int = Config.get("shared.default_query_limit"),
    order_by: str | None = None,
    order: str = "desc",
    ctx: Context = None,
) -> str:
    """Run an aggregation on the data table.

    - op: one of "count", "sum", "avg", "min", "max".
    - field: column to aggregate (not required for "count").
    - group_by: optional column to group results by.
    - filters: list of filter objects, same format as select_rows.
      Example: [{"column": "age", "op": ">=", "value": 18}]
    - limit: max groups to return when using group_by (default 20, max 100).
    - order_by: column to sort grouped results by — the group column name or "result" (default "result"). Only applies when group_by is used.
    - order: "asc" or "desc" (default "desc").
    """
    logger.info("Executing aggregation tool")
    repository = _get_repository(ctx)
    order = order.lower()
    if order not in ("asc", "desc"):
        return json.dumps({"error": "order must be 'asc' or 'desc'"})
    try:
        parsed_filters = _parse_filters(filters)
        query_result = await repository.aggregate(
            operation=op, field=field, group_by=group_by, filters=parsed_filters, limit=limit,
            order_by=order_by, order=order,
        )
    except ValueError as e:
        logger.warning("aggregate validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})
