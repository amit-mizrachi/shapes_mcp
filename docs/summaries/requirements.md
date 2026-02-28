# `requirements.txt` -- MCP server dependencies

## Overview

The `shapes_mcp` MCP server has a minimal dependency set. It relies on the MCP SDK to expose
data-query tools over the Model Context Protocol, and on `aiosqlite` to run async SQLite queries
against an in-memory database that is built at startup from ingested CSV data.

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `mcp[cli]` | `==1.20.0` | The official Model Context Protocol Python SDK with its CLI extras. Provides `FastMCP`, the Streamable-HTTP transport, and the tool-registration API used in `server.py` to expose `get_schema`, `select_rows`, and `aggregate` as MCP tools. The `[cli]` extra pulls in Starlette and Uvicorn for serving the HTTP application. |
| `aiosqlite` | `==0.20.0` | Async wrapper around Python's built-in `sqlite3` module. Used by `SqliteDataStore` and `SqliteIngester` to perform non-blocking database reads and writes so the async MCP server is never blocked on I/O while querying the SQLite database. |
