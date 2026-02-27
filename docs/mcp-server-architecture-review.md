# MCP Server Architecture Review

Four specialized agents reviewed the mcp-server codebase to answer one question: **is the component structure right-sized, and how should it be redesigned?**

Reviewers: Clean Code, Clean Architecture, Software Architect, Backend Specialist.

---

## Current Structure

```
mcp-server/src/
  server.py                              # Composition root, lifespan, health endpoint
  mcp_tools.py                           # MCP tool handlers (get_schema, select_rows, aggregate)
  repository/
    csv_parser.py                        # CSV -> ParsedCSV
    data_repository_protocol.py          # Protocol (abstract interface)
    sqlite/
      sqlite_ingester.py                 # Write-path: load data into SQLite
      sqlite_repository.py              # Read-path: query SQLite
  enrichment/
    enrichment_rule.py                   # ABC for enrichment strategies
    column_enricher.py                   # Orchestrates enrichment rules
    rules/
      date_enrichment_rule.py            # Detects dates, adds derived columns
      full_name_enrichment_rule.py       # Combines first+last name

shared/modules/data/
  filter_condition.py, query_result.py, table_schema.py, column_info.py, parsed_csv.py
```

**10 source files, 776 lines of production code, 5 shared DTOs.**

---

## 1. Clean Code Review

**Score: 5/10**

### Key Findings

- **`mcp_tools.py` is a meaningless name.** It is the equivalent of calling something `Utilities`. The functions inside are MCP tool handlers -- they translate requests into repository calls and serialize responses. Should be renamed to `tool_handlers.py`.

- **`DataRepositoryProtocol` buries intent.** The `Protocol` suffix is a Python typing mechanism, not a domain concept. The `Data` prefix is vague. Recommended rename: `DataStore`.

- **`repository/` package conflates three concerns**: an abstract port, a CSV parser, and SQLite adapters. A developer reading `from repository.csv_parser import CSVParser` rightfully asks: "Why is a CSV parser in a repository?"

- **`FilterCondition.operator` vs docstring `"op"` mismatch.** The Pydantic model field is `operator`, but docstrings tell the LLM to send `"op"`. No alias is configured -- this is a potential runtime bug.

- **Duplicate `order` validation.** Both `mcp_tools.py` and `SqliteRepository` validate the order parameter, but with different error behavior (JSON string vs ValueError).

- **`_build_aggregated_sql_query` has 7 untyped parameters.** The only private method without type annotations.

### Proposed Structure

```
src/
  server.py
  tool_handlers.py                     # was mcp_tools.py
  ingestion/
    csv_parser.py
    sqlite_ingester.py
  data_store/
    data_store.py                      # was data_repository_protocol.py
    sqlite_data_store.py               # was sqlite_repository.py
  enrichment/
    (unchanged)
```

---

## 2. Clean Architecture Review

**Score: 6.8/10**

### Key Findings

- **Dependency direction is correct** -- no cycles, arrows point inward. This is the strongest aspect of the codebase.

- **Framework leak into use-case layer.** `mcp_tools.py` imports `from mcp.server.fastmcp import Context`. This couples the handler logic to the MCP SDK. You cannot call `select_rows` from a test or CLI without constructing a full MCP Context.

- **JSON serialization is in the wrong layer.** `mcp_tools.py` calls `json.dumps()` -- this is a transport/presentation concern that belongs at the framework boundary, not in the use-case logic.

- **The Protocol lives next to its implementation** instead of being owned by the consumer. In Clean Architecture, the abstract port should live in the use-case layer, not the infrastructure layer.

- **`repository/` violates SRP** -- it holds an abstract port, a CSV parser, and SQLite adapters under one name.

- **SOLID highlights**: OCP is excellent (enrichment system is cleanly extensible). DIP is structurally undermined by Protocol placement. ISP passes (3 focused methods).

### Proposed Structure

```
src/
  server.py
  use_cases/
    data_query_service.py              # was mcp_tools.py, as a class
    ports/
      data_repository.py               # was data_repository_protocol.py
  infrastructure/
    csv/
      csv_parser.py
    sqlite/
      sqlite_repository.py
      sqlite_ingester.py
  enrichment/
    (unchanged)
```

---

## 3. Software Architect Review

**Verdict: "Slightly over-structured, but not by much."**

### Key Findings

- **The protocol is premature abstraction.** One implementation, no planned second backend. Delete it and add it back when needed. (YAGNI)

- **The `rules/` sub-package is marginal.** Two rule files do not justify a sub-directory. Flatten into `enrichment/` until there are 4+ rules.

- **`sqlite/` subdirectory is unjustified nesting.** The path `repository/sqlite/sqlite_repository.py` has the word "sqlite" three times. One backend does not need a sub-directory -- the `sqlite_` prefix is sufficient.

- **The data pipeline is well-designed.** Immutable data flow, clear phase separation, write-path vs read-path separation, `PRAGMA query_only = ON`. These are strong design decisions.

- **Extract the startup pipeline into `pipeline.py`.** The parse-enrich-ingest sequence in `server.py` is a self-contained pipeline that should be a standalone function for testability.

- **`csv_parser.py` staying under `repository/` is defensible.** It is the ingestion side of the data layer -- moving it is optional, not required.

### Proposed Structure

```
src/
  server.py
  tools.py                             # was mcp_tools.py (drop "mcp_" prefix)
  pipeline.py                          # NEW: build_repository(csv_path, db_path)
  repository/
    csv_parser.py                      # stays here
    sqlite_repository.py               # flattened from sqlite/
    sqlite_ingester.py                 # flattened from sqlite/
  enrichment/
    enrichment_rule.py
    column_enricher.py
    date_enrichment_rule.py            # flattened from rules/
    full_name_enrichment_rule.py       # flattened from rules/
```

**File count: 10 -> 9. Package directories: 4 -> 2. Protocol: deleted.**

---

## 4. Backend Specialist Review

**Verdict: "The component count is right. The structure needs tightening, not a rewrite."**

### Key Findings

- **Every component earns its place.** No merges or splits needed at the file level.

- **Keep the Protocol, but drop `runtime_checkable`.** It is cheap insurance (33 lines). The moment you write a `FakeRepository` for tests, it pays for itself. But `runtime_checkable` is unused ceremony.

- **Protocol default values are a lie.** The protocol hardcodes `limit: int = 20` while the implementation uses `Config.get()`. If that config changes, the protocol misleads readers. Remove defaults from the protocol.

- **Row-by-row insertion is slow.** `SqliteIngester` uses `cursor.execute()` in a loop. Should use `cursor.executemany()` for batch insertion.

- **One connection per query is wasteful.** Every call to `select_rows`/`aggregate` opens a new aiosqlite connection. A persistent connection created at startup would avoid repeated `PRAGMA query_only = ON` overhead.

- **Error handling is inconsistent.** `mcp_tools.py` catches `ValueError` but lets `sqlite3.OperationalError` crash. `_run_query` logs "query failed" with no SQL or params. No custom error types exist.

- **Limit is not enforced.** Docstrings say "max 100" but nothing clamps it. An LLM can request `limit=999999`.

- **`aggregate` order_by default is broken.** Docstring says default is `"result"`, but actual default is `None` (no ordering).

- **No request-level timeout.** A full table scan on a large dataset has no timeout protection.

### Proposed Structure

```
src/
  server.py
  mcp_tools.py                        # keep name (MCP context makes it clear)
  errors.py                           # NEW: custom exception types
  pipeline/
    csv_parser.py                     # moved from repository/
    column_enricher.py                # moved from enrichment/
    enrichment_rule.py                # moved from enrichment/
    rules/
      date_enrichment_rule.py
      full_name_enrichment_rule.py
  repository/
    data_repository_protocol.py       # keep, drop runtime_checkable
    sqlite_repository.py              # flattened from sqlite/
    sqlite_ingester.py                # flattened from sqlite/
  tests/                              # NEW: comprehensive test suite
```

---

## Comparison Matrix

| Topic | Clean Code | Clean Architecture | Software Architect | Backend Specialist |
|-------|-----------|-------------------|-------------------|-------------------|
| **Component count** | Right, but misplaced | Right, but misplaced | Slightly over-structured | Right-sized |
| **Protocol** | Rename to `DataStore` | Move to `use_cases/ports/` | Delete (YAGNI) | Keep, drop `runtime_checkable` |
| **`mcp_tools.py` rename** | `tool_handlers.py` | `data_query_service.py` | `tools.py` | Keep as-is |
| **`csv_parser.py` location** | Move to `ingestion/` | Move to `infrastructure/csv/` | Keep in `repository/` | Move to `pipeline/` |
| **`sqlite/` subdirectory** | Flatten | Keep under `infrastructure/` | Flatten | Flatten |
| **`rules/` subdirectory** | Not discussed | Not discussed | Flatten | Keep |
| **Add `pipeline.py`** | No | No | Yes | No (pipeline/ package instead) |
| **Add `errors.py`** | No | No | No | Yes |
| **Service layer** | No | Yes (class) | No | No ("pass-through") |
| **`enrichment/` location** | Keep separate | Keep separate | Keep separate | Merge into `pipeline/` |
| **Nesting level** | Medium | High (most nesting) | Low (flattest) | Medium |

---

## Consensus Points (All Four Agree)

1. **Flatten `repository/sqlite/` to `repository/`.** The triple "sqlite" (directory/file/class) is unnecessary nesting.
2. **`mcp_tools.py` name is unclear.** Whether to call it `tools.py`, `tool_handlers.py`, or something else varies, but all agree the current name communicates nothing about what the module does architecturally.
3. **`csv_parser.py` does not belong under `repository/`.** Three of four reviewers say move it; the architect says it is "defensible" but not ideal.
4. **The data pipeline is well-designed.** Parse -> enrich -> ingest -> query. Immutable data flow, clean phase separation, write/read path separation. No one suggested changing this.
5. **The enrichment system is the best-designed part.** Strategy pattern with ABC, two implementations, clean extension point. All four reviewers praised it.
6. **Error handling needs work.** Inconsistent catch patterns, no custom types, uninformative error logging.

---

## Contested Points

### Should the Protocol stay or go?

| Position | Who | Reasoning |
|----------|-----|-----------|
| Delete it | Software Architect | YAGNI. One implementation. Add it when a second backend appears. |
| Keep it | Backend Specialist | Cheap insurance (33 lines). Pays for itself with test fakes. |
| Keep + rename | Clean Code | Rename to `DataStore`. Drop `Protocol` suffix. |
| Keep + move | Clean Architecture | Move to `use_cases/ports/`. It is a port, not an adapter. |

### How much nesting is right?

| Position | Who | Nesting level |
|----------|-----|--------------|
| Flattest | Software Architect | 2 packages (`repository/`, `enrichment/`), no sub-packages |
| Medium | Clean Code, Backend | 2-3 packages, some sub-packages |
| Deepest | Clean Architecture | `use_cases/ports/`, `infrastructure/csv/`, `infrastructure/sqlite/` |

### Should enrichment merge into pipeline?

| Position | Who |
|----------|-----|
| Keep separate | Clean Code, Clean Architecture, Software Architect |
| Merge into `pipeline/` | Backend Specialist |

---

## Bugs and Issues Found (All Reviewers Combined)

| # | Issue | Severity | Found By |
|---|-------|----------|----------|
| 1 | `FilterCondition.operator` vs docstring `"op"` mismatch | CRITICAL | Clean Code |
| 2 | Limit not enforced (docstring says max 100, no clamping) | HIGH | Backend |
| 3 | `aggregate` order_by docstring says default `"result"`, actual is `None` | HIGH | Backend |
| 4 | `_run_query` logs "query failed" with no SQL/params/exc_info | HIGH | Backend |
| 5 | `mcp_tools.py` catches `ValueError` but not `sqlite3.OperationalError` | HIGH | Backend |
| 6 | Row-by-row insertion instead of `executemany()` | MEDIUM | Backend |
| 7 | One aiosqlite connection per query instead of persistent connection | MEDIUM | Backend |
| 8 | Duplicate `order` validation between handler and repository | MEDIUM | Clean Code |
| 9 | `_get_repository` raises `RuntimeError` which is never caught | MEDIUM | Backend |
| 10 | Protocol default values diverge from implementation | LOW | Backend |
| 11 | `runtime_checkable` decorator is unused | LOW | Backend |
| 12 | `_build_aggregated_sql_query` has 7 untyped parameters | LOW | Clean Code |

---

## Final Plan

After all four reviews and iteration, here is the agreed-upon restructuring.

### From

```
src/
  server.py
  mcp_tools.py
  repository/
    csv_parser.py
    data_repository_protocol.py
    sqlite/
      sqlite_ingester.py
      sqlite_repository.py
  enrichment/
    enrichment_rule.py
    column_enricher.py
    rules/
      date_enrichment_rule.py
      full_name_enrichment_rule.py
```

### To

```
src/
  server.py                          # Composition root (unchanged)
  tool_handlers.py                   # Renamed from mcp_tools.py
  pipeline.py                        # NEW: extract parse->enrich->ingest from server.py

  repository/
    csv_parser.py                    # Stays here (ingestion side of data layer)
    data_store.py                    # ABC interface (was Protocol in data_repository_protocol.py)
    sqlite_data_store.py             # Flattened from sqlite/, implements DataStore ABC
    sqlite_ingester.py               # Flattened from sqlite/ (write-path)

  enrichment/
    enrichment_rule.py               # ABC (unchanged)
    column_enricher.py               # Orchestrator (unchanged)
    rules/
      date_enrichment_rule.py        # Keep sub-package (unchanged)
      full_name_enrichment_rule.py   # Keep sub-package (unchanged)
```

### Changes

1. **Rename `mcp_tools.py` -> `tool_handlers.py`** -- describes what the module actually does. `tools.py` is too generic; `data_query_service.py` is too heavy. `tool_handlers` is precise: these handle MCP tool invocations.

2. **Extract `pipeline.py`** -- `build_data_store(csv_path, db_path) -> DataStore` pulls the parse->enrich->ingest sequence out of `server.py`. Makes the pipeline independently testable, keeps server.py as a pure composition root.

3. **Flatten `sqlite/` subdirectory** -- `sqlite_repository.py` becomes `sqlite_data_store.py` directly under `repository/`. One backend doesn't need a sub-directory. The `sqlite_` prefix on filenames is sufficient.

4. **Replace Protocol with ABC in `data_store.py`** -- explicit inheritance (`class SqliteDataStore(DataStore)`), enforces implementation at instantiation time, immediately readable without knowing Python structural typing.

5. **Keep `csv_parser.py` in `repository/`** -- it is the ingestion side of the data layer. Moving it to a separate `ingestion/` package would create a two-file package where the files don't actually collaborate (CSV parser produces `ParsedCSV`, enrichment runs, *then* the ingester consumes it). Grouping by lifecycle phase rather than cohesion adds nesting without payoff.

6. **Keep `rules/` sub-package** -- not flattened; preserves the Strategy pattern structure as a clear extension point.

7. **No `errors.py`** -- no custom exception hierarchy. Standard exceptions with clear messages are enough for this project scope.

8. **No service layer or class** -- the tool handlers are thin enough. A service class would just be a pass-through with no logic of its own.

### Not Changing

- **Enrichment system** -- already well-designed (Strategy pattern, OCP). No structural changes.
- **server.py** -- remains composition root, just lighter after pipeline extraction.
- **Shared DTOs** -- `FilterCondition`, `QueryResult`, `TableSchema`, `ColumnInfo`, `ParsedCSV` stay as-is.

### Bug Fixes (Do First, Before Restructuring)

1. Fix `FilterCondition.operator` vs docstring `"op"` mismatch
2. Add limit clamping (docstring says max 100, nothing enforces it)
3. Fix `aggregate` order_by default inconsistency
4. Improve `_run_query` error logging (include SQL + params)
5. Catch all exceptions in tool handlers, not just `ValueError`
6. Use `executemany()` in ingester
