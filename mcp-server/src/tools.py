from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import Context

from repository import DataRepository

logger = logging.getLogger(__name__)


def _get_repository(ctx: Context) -> DataRepository:
    repository = ctx.request_context.lifespan_context.get("repository")
    if repository is None:
        logger.error("Repository not initialized")
        raise RuntimeError("Repository not initialized")
    return repository


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
    filters: dict[str, str | int | float] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
    ctx: Context = None,
) -> str:
    """Retrieve rows from the data table.

    - fields: list of column names to return (default: all columns).
    - filters: dict of conditions. Key is a column name, optionally with a
      suffix _gt, _lt, _gte, or _lte for comparison operators.
      Example: {"age_gt": 30, "city": "London"}
    - limit: max rows to return (default 20, max 100).
    """
    logger.info("Executing select_rows")
    repository = _get_repository(ctx)
    try:
        query_result = await repository.select_rows(filters=filters, fields=fields, limit=limit)
    except ValueError as e:
        logger.warning("select_rows validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})


async def aggregate(
    op: str,
    field: str | None = None,
    group_by: str | None = None,
    filters: dict[str, str | int | float] | None = None,
    limit: int = 20,
    ctx: Context = None,
) -> str:
    """Run an aggregation on the data table.

    - op: one of "count", "sum", "avg", "min", "max".
    - field: column to aggregate (not required for "count").
    - group_by: optional column to group results by.
    - filters: dict of conditions, same syntax as select_rows.
    - limit: max groups to return when using group_by (default 20, max 100).
    """
    logger.info("Executing aggregate")
    repository = _get_repository(ctx)
    try:
        query_result = await repository.aggregate(op=op, field=field, group_by=group_by, filters=filters, limit=limit)
    except ValueError as e:
        logger.warning("aggregate validation failed")
        return json.dumps({"error": str(e)})
    return json.dumps({"data": query_result.rows, "count": query_result.count})
