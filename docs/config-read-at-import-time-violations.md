# Configuration Violations

Remaining places where config values are read in one place and passed to another,
or where `Config.get()` is used in function signatures as default parameter values.

> Files already fixed in this session (`chat-server/src/server.py`, `mcp-server/src/server.py`,
> and their downstream classes) are excluded.

---

## mcp-server/src/tool_handlers.py

### `select_rows` — default param uses `Config.get()`

```python
# line 42
limit: int = Config.get("mcp_server.default_query_limit"),
```

Default parameter values are evaluated once at module load time. Should use
`limit: int | None = None` and resolve inside the function body.

### `aggregate` — same issue

```python
# line 89
limit: int = Config.get("mcp_server.default_query_limit"),
```

---

## mcp-server/src/repository/sqlite_data_store.py

### `select_rows` — default param uses `Config.get()`

```python
# line 33
limit: int = Config.get("mcp_server.default_query_limit"),
```

### `aggregate` — same issue

```python
# line 54
limit: int = Config.get("mcp_server.default_query_limit"),
```

---

## mcp-server/src/repository/data_store.py (abstract base)

### `select_rows` / `aggregate` — hardcoded default duplicates config value

```python
# lines 19, 32
limit: int = 20,
```

The magic number `20` duplicates `mcp_server.default_query_limit`. Should use
`limit: int | None = None` for consistency with concrete implementation fixes.

---

## chat-server/src/mcp_client/mcp_client.py

### Constructor receives `url` that could be read from Config

`MCPClient.__init__(self, url: str)` — the URL is always
`Config.get("chat_server.mcp_server_url")`, passed through from `MCPClientManager`.
Could read it directly from Config instead of receiving it as a parameter.

---

## Files scanned — no violations

- `shared/config.py` — Config class itself
- `mcp-server/src/enrichment/column_enricher.py` — reads Config directly (correct)
- `mcp-server/src/repository/csv_parser.py` — stateless utility, receives path as arg (correct)
- `mcp-server/src/repository/sqlite_ingester.py` — fixed this session
- All shared modules (data models, API models) — no Config usage
- All enrichment rules — no Config usage
- `chat-server/src/llm_clients/llm_client_interface.py` — abstract, no Config usage
