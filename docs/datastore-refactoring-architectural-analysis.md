# DataStore Refactoring: Architectural Analysis Report

**Date:** 2026-02-28
**Scope:** Two proposed refactors for the `data_store` package in `mcp-server`
**Agents Used:** Software Architect (x2), Clean Architecture (x2)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Refactor 1: Separating Query Creation from Query Execution](#refactor-1-separating-query-creation-from-query-execution)
   - [Current State Analysis](#current-state-analysis)
   - [Software Architect Assessment](#software-architect-assessment)
   - [Clean Architecture Assessment](#clean-architecture-assessment)
   - [Recommended Design](#recommended-design)
   - [Implementation Plan](#implementation-plan)
   - [Testing Strategy](#testing-strategy)
3. [Refactor 2: Introducing a DataIngestor Interface](#refactor-2-introducing-a-dataingestor-interface)
   - [Current State Analysis](#current-state-analysis-1)
   - [Software Architect Assessment](#software-architect-assessment-1)
   - [Clean Architecture Assessment](#clean-architecture-assessment-1)
   - [Database Alternatives Analysis](#database-alternatives-analysis)
   - [Recommended Design](#recommended-design-1)
   - [Implementation Plan](#implementation-plan-1)
   - [YAGNI Assessment](#yagni-assessment)
4. [Combined Architecture Scores](#combined-architecture-scores)
5. [Prioritized Action Items](#prioritized-action-items)

---

## Executive Summary

Both refactors are **recommended**, but for different reasons and at different urgency levels:

| Refactor | Verdict | Urgency | Effort | Primary Benefit |
|----------|---------|---------|--------|-----------------|
| Query separation | **Do it** | Medium | Medium (~2 hrs) | Testability + SRP compliance |
| DataIngestor interface | **Do it** | Low-Medium | Low (~15 min) | Architectural consistency + DIP compliance |

The `SqliteDataStore` class has a clear **SRP violation** -- it mixes SQL query construction, input validation, and database execution in a single 320-line class. Extracting a `SqliteQueryBuilder` yields fast, isolated unit tests for SQL generation and shrinks the data store to ~90 lines.

The absence of a `DataIngestor` ABC creates an **architectural asymmetry** -- querying is properly abstracted behind `DataStore` ABC, but ingestion is hardwired to SQLite. Adding a 10-line ABC costs almost nothing and aligns the codebase with its own established patterns.

---

## Refactor 1: Separating Query Creation from Query Execution

### Current State Analysis

`SqliteDataStore` (`mcp-server/src/data_store/sqlite_data_store.py`, ~320 lines) contains **three entangled responsibilities**:

| Responsibility | Methods | Character |
|---|---|---|
| **SQL Query Construction** | `_build_select_columns`, `_build_where_clause`, `_filter_to_sql_expression`, `_build_case_expression`, `_build_order_clause`, `_build_aggregation_expression`, `_build_having_clause`, `_build_aggregated_sql_query`, `_collect_filter_params`, `_normalize_group_by` | Pure logic -- domain objects in, SQL strings + params out. No I/O. |
| **Schema Validation** | `_validate_column`, `_validate_order_direction`, `_validate_aggregation_args`, `_validate_aggregation_op`, `_validate_transform_columns` | Pure logic -- checks inputs against schema. No I/O. |
| **Database Execution** | `_connection`, `_run_query`, `_run_query_with_total`, `_execute_query` | Async I/O -- manages `aiosqlite` connections, executes SQL, converts rows. |

The public methods `select_rows` and `aggregate` orchestrate all three concerns. Query building methods account for **18 of 22 methods** in the class.

### Software Architect Assessment

**Verdict: The separation is worth doing.**

**The SRP violation is harmful today:**

1. **Testability friction.** All existing tests are integration tests that spin up a real SQLite database via `SqliteIngester`, ingest CSV data, and execute full queries. There are zero unit tests that verify SQL generation in isolation. To test whether `_build_where_clause` produces correct SQL for an `OR` filter, you must stand up a database, ingest rows, execute the full query, and inspect the returned data. A failure could be caused by ingestion, connection handling, or SQL generation.

2. **Reuse barrier.** If a different query backend is ever needed (DuckDB, PostgreSQL, or even a SQL preview/dry-run mode), the query building logic cannot be reused -- it is locked inside the SQLite-specific class.

3. **Growing complexity.** The SQL generation logic already dominates the class (18/22 methods). As new SQL features are added (JOINs, subqueries, window functions), the class grows in the query dimension while execution stays static.

**Counterarguments acknowledged:**
- The codebase is small (320 lines is manageable)
- There is only one backend (SQLite)
- All query methods are private (coupling is internal)

**These do not outweigh the testability and clarity gains.**

### Clean Architecture Assessment

**SOLID Violations Found:**

| Principle | Status | Detail |
|-----------|--------|--------|
| **SRP** | CRITICAL VIOLATION | Three distinct responsibilities in one class. They change for independent reasons. |
| **OCP** | Minor violation | `_filter_to_sql_expression` uses if/elif chain for operator mapping. A mapping-based approach would be more extensible. |
| **LSP** | Pass | `SqliteDataStore` correctly implements all `DataStore` abstract methods. |
| **ISP** | Minor concern | `select_rows` and `aggregate` have long parameter lists (8 and 11 params). |
| **DIP** | Pass at architecture level | `tool_handlers.py` depends on `DataStore` ABC, not concrete class. |

**Key finding:** The query building methods are **already functionally pure** -- they take parameters and return SQL strings + parameter lists. They do not use `self._db_uri` or `self._connection()`. They only use `self._table_schema.table_name` and `self._valid_columns`. This makes extraction straightforward.

**Additional concerns identified:**
- `Config.get()` called at **import time** as default parameter values (lines 37, 72) -- infrastructure leaking into method signatures
- `build_data_store()` return type annotation uses `SqliteDataStore` instead of `DataStore`
- `Config` class sits in `shared/` alongside entities despite being infrastructure

### Recommended Design

#### Design Principles

1. **Extract, do not abstract.** Create a concrete `SqliteQueryBuilder` class, not an ABC. Only one database exists.
2. **Return raw SQL + params tuples.** An intermediate query representation (AST, query object) is over-engineering at this scale.
3. **Co-locate validation with building.** Validation guards query building inputs -- they belong together.
4. **Keep the builder stateless per call.** Constructor holds `TableSchema` and `valid_columns`; each method call is pure.

#### Component Diagram

```
DataStore (ABC)                     SqliteQueryBuilder
  get_schema()                        build_select_query(...)  -> SelectQuery
  select_rows(...)                    build_aggregate_query(...) -> AggregateQuery
  aggregate(...)
       ^
       |
SqliteDataStore
  _query_builder: SqliteQueryBuilder   (composition)
  _connection()                        (async I/O)
  _run_query()                         (async I/O)
  _run_query_with_total()              (async I/O)
  _execute_query()                     (async I/O)
  select_rows(...)                     calls _query_builder, then _run_query_with_total
  aggregate(...)                       calls _query_builder, then _run_query
```

#### Return Types

```python
from typing import NamedTuple

class SelectQuery(NamedTuple):
    sql: str
    params: list
    count_sql: str
    count_params: list

class AggregateQuery(NamedTuple):
    sql: str
    params: list
```

#### Why Not These Alternatives?

| Alternative | Why Not |
|---|---|
| **Keep as-is** | Testability gap grows with each new SQL feature |
| **Module of free functions** | Requires passing `table_schema` and `valid_columns` to every function |
| **Query object / AST** | Over-engineering. Maps 1:1 to SQL at this scale |
| **Abstract QueryBuilder ABC** | Speculative. Only one database. Extracting an interface later is trivial |
| **Mixin / multiple inheritance** | Obscures the dependency. Composition is clearer |

### Implementation Plan

#### Step 1: Create `SqliteQueryBuilder`

**New file:** `mcp-server/src/data_store/sqlite_query_builder.py`

```python
class SqliteQueryBuilder:
    """Pure SQL query construction for SQLite dialect.
    No I/O, no connections, no framework dependencies."""

    def __init__(self, table_schema: TableSchema) -> None:
        self._table_schema = table_schema
        self._valid_columns: set[str] = {col.name for col in table_schema.columns}

    # Public API
    def build_select_query(self, *, filters, fields, limit, order_by, order,
                           distinct, transform, filter_logic) -> SelectQuery: ...
    def build_aggregate_query(self, *, operation, field, group_by, filters, limit,
                              order_by, order, having_operator, having_value,
                              transform, filter_logic) -> AggregateQuery: ...

    # All _build_* and _validate_* methods move here unchanged
```

All existing private methods (`_build_where_clause`, `_filter_to_sql_expression`, `_build_case_expression`, `_validate_column`, etc.) move into this class. The logic is identical -- only the class boundary changes.

#### Step 2: Simplify `SqliteDataStore`

**Modified file:** `mcp-server/src/data_store/sqlite_data_store.py`

Shrinks from ~320 lines to ~90 lines. Becomes a thin execution shell:

```python
class SqliteDataStore(DataStore):
    def __init__(self, database_path=None, table_schema=None):
        self._db_uri = database_path or Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._query_builder = SqliteQueryBuilder(table_schema)

    async def select_rows(self, ...) -> QueryResult:
        query = self._query_builder.build_select_query(...)
        return await self._run_query_with_total(
            query.sql, query.params, query.count_sql, query.count_params)

    async def aggregate(self, ...) -> QueryResult:
        query = self._query_builder.build_aggregate_query(...)
        return await self._run_query(query.sql, query.params)

    # Only execution methods remain: _connection, _run_query,
    # _run_query_with_total, _execute_query
```

#### Step 3: No Changes to External Files

The refactoring is **entirely internal** to the `data_store` package:
- `data_store.py` (ABC) -- unchanged
- `tool_handlers.py` -- unchanged
- `server.py` -- unchanged
- `shared/modules/data/*.py` -- unchanged
- Existing integration tests -- unchanged, all pass

#### Execution Order

1. Create `sqlite_query_builder.py` with all builder + validation methods
2. Write unit tests for the builder (see below)
3. Modify `sqlite_data_store.py` to use the builder via composition
4. Run existing integration tests -- all pass
5. Move constants (`RESULT_ORDER_SENTINEL`, `_AGG_RESULT_ALIAS`) to the builder

### Testing Strategy

**Before:** All tests are integration tests requiring a real SQLite database.

**After:** New pure unit tests for SQL generation + existing integration tests unchanged.

| Aspect | Before | After |
|---|---|---|
| SQL generation test speed | Slow (real DB per test) | Fast (no I/O) |
| SQL string assertions | Impossible (only result data) | Direct string/param checks |
| Failure localization | Ambiguous (build vs execute?) | Precise (builder or executor) |
| Test count | ~30 integration tests | ~30 integration + ~20 unit tests |

**Example unit tests for `SqliteQueryBuilder`:**

```python
class TestBuildSelectQuery:
    def test_select_all_columns(self, builder):
        q = builder.build_select_query(limit=10)
        assert 'SELECT *' in q.sql
        assert 'LIMIT ?' in q.sql
        assert q.params == [10]

    def test_where_clause_or_logic(self, builder):
        filters = [
            FilterCondition(column="name", operator="=", value="Alice"),
            FilterCondition(column="name", operator="=", value="Bob"),
        ]
        q = builder.build_select_query(filters=filters, filter_logic="OR", limit=10)
        assert " OR " in q.sql

    def test_invalid_field_raises(self, builder):
        with pytest.raises(ValueError, match="not found"):
            builder.build_select_query(fields=["nonexistent"], limit=10)
```

---

## Refactor 2: Introducing a DataIngestor Interface

### Current State Analysis

**The asymmetry:**

| Component | ABC Exists? | Concrete Implementation |
|-----------|-------------|------------------------|
| `DataStore` | Yes (`data_store.py`) | `SqliteDataStore` (aiosqlite, async) |
| `EnrichmentRule` | Yes (`enrichment_rule.py`) | `NominalDateRule`, `MonthExtractionRule`, `YearExtractionRule` |
| `DataIngestor` | **No** | `SqliteIngester` (sqlite3, sync, used directly) |

**Current wiring in `server.py`:**

```python
def build_data_store(csv_file_path: str) -> SqliteDataStore:  # concrete return type
    parsed_csv = CSVParser.parse(csv_file_path)
    enricher = ColumnEnricher(rules=[...])
    enriched_csv = enricher.enrich(parsed_csv)
    ingester = SqliteIngester()                    # no abstraction
    table_schema = ingester.ingest(enriched_csv)   # direct concrete call
    return SqliteDataStore(table_schema=table_schema)
```

If someone wanted to swap the database backend, they could swap queries (ABC exists) but NOT ingestion (no contract to follow). This makes backend portability half-baked.

### Software Architect Assessment

**Verdict: Adding a `DataIngestor` ABC is a net positive, but for architectural consistency and testability -- not because a second implementation is imminent.**

**Is SQLite actually "basic" for this use case?**

SQLite is actually an **excellent fit**:
- Single-user (one MCP server per CSV file)
- Read-heavy after a one-time write
- Small-to-medium data (CSV files, typically < 1M rows)
- No concurrent writes
- Ephemeral (database deleted on shutdown)

SQLite is not a compromise -- it is arguably the optimal choice. The in-process nature means zero network overhead, and `PRAGMA query_only = ON` is a nice safety measure.

**The honest verdict:** The cost is ~15 lines of code. The benefits are:
1. **Symmetry with DataStore** -- the codebase sets an expectation that swappable components have ABCs
2. **Testability** -- an ABC enables mocking ingestion in tests
3. **Documentation value** -- the ABC communicates the contract
4. **Factory pattern enablement** -- prevents misconfigured ingester+datastore pairs

### Clean Architecture Assessment

**SOLID Violations:**

| Principle | Status | Detail |
|-----------|--------|--------|
| **SRP** | Pass | Each class has a focused responsibility |
| **OCP** | Violation (ingestion only) | Switching ingestion backend requires modifying `server.py` directly |
| **LSP** | Pass | No substitution issues |
| **ISP** | Pass | Interfaces are well-sized |
| **DIP** | **Violation** | `server.py` depends directly on `SqliteIngester` (concrete). No abstraction to depend upon. |

**Boundary analysis:**

```
Query side (CLEAN):
  tool_handlers.py --> DataStore (ABC) <-- SqliteDataStore

Ingestion side (NOT ISOLATED):
  server.py --> SqliteIngester (concrete, hardwired)
```

**Comparison with chat-server (which IS clean):**

The `chat-server` already follows the correct pattern:
- `LLMClient` (ABC) defines `invoke()`
- `ClaudeLLMClient` and `GeminiLLMClient` implement it
- `LLMClientFactory.create()` returns `LLMClient` (the abstraction)

The `data_store/` package should follow this same pattern.

**Component metrics impact:**

Adding a `DataIngestor` ABC would improve the `data_store/` package abstractness from 0.25 to 0.40, moving it closer to the main sequence.

### Database Alternatives Analysis

| Scenario | Candidate | What Changes |
|----------|-----------|--------------|
| CSV files with 10M+ rows, complex analytical queries | **DuckDB** | Columnar, excels at analytics. Uses `duckdb.connect()` and `COPY` commands. Very close SQL dialect. |
| Multiple MCP servers sharing the same data | **PostgreSQL** | Network-accessible, concurrent readers/writers. Uses `asyncpg`. Requires connection pooling. |
| Persistent data across restarts | **PostgreSQL or DuckDB file** | SQLite could also do this (stop deleting the file). |

**DuckDB is the only realistic alternative** for this project. It shares SQLite's embed-and-forget model but is dramatically faster for analytical queries (columnar storage, vectorized execution). PostgreSQL would be significant operational burden with little benefit for this single-user use case.

| Concern | SQLite | DuckDB | PostgreSQL |
|---------|--------|--------|------------|
| Ingester: bulk insert | `executemany` | `read_csv_auto` or `INSERT` | `COPY FROM` or `executemany` |
| Ingester: sync/async | sync (`sqlite3`) | sync (`duckdb`) | async (`asyncpg`) |
| Data store: connection | `aiosqlite.connect(path)` | `duckdb.connect(path)` (sync, wrap) | `asyncpg.create_pool(dsn)` |
| Data store: SQL dialect | Standard SQL | PostgreSQL-like | PostgreSQL |
| Deployment | Zero config, file-based | Zero config, file-based | Requires server |

### Recommended Design

#### DataIngestor ABC

**New file:** `mcp-server/src/data_store/data_ingestor.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shared.modules.data.parsed_csv import ParsedCSV
from shared.modules.data.table_schema import TableSchema


class DataIngestor(ABC):
    @abstractmethod
    def ingest(self, parsed_csv: ParsedCSV) -> TableSchema:
        """Persist the parsed CSV data and return the resulting table schema."""
        ...
```

**Why a single method is correct:**
- DuckDB can ingest directly from CSV with `read_csv_auto()` -- no separate "create table" step
- PostgreSQL might use `COPY FROM STDIN` which combines creation and insertion
- The single `ingest()` gives implementations freedom in how they persist data

**Why synchronous:**
- Ingestion happens once at startup, before the async event loop serves requests
- Making the ABC async provides zero benefit for SQLite/DuckDB
- If async is needed later, making it async is a backward-compatible change

#### Factory Pattern

**Not yet.** A factory becomes worthwhile when there are two or more backends. Today, the simplest approach is to type-annotate in `server.py`:

```python
def build_data_store(csv_file_path: str) -> DataStore:     # ABC return type
    ...
    ingester: DataIngestor = SqliteIngester()               # typed against ABC
    table_schema = ingester.ingest(enriched_csv)
    return SqliteDataStore(table_schema=table_schema)
```

When a second backend arrives, introduce a `DataBackendFactory`:

```python
class DataBackendFactory:
    @staticmethod
    def create_ingester() -> DataIngestor:
        return SqliteIngester()

    @staticmethod
    def create_data_store(table_schema: TableSchema) -> DataStore:
        return SqliteDataStore(table_schema=table_schema)
```

**Do not build the factory now.**

### Implementation Plan

Every step is independently deployable. No step changes runtime behavior.

| Step | Change | Risk | Breaks Anything? |
|------|--------|------|-------------------|
| 1 | Create `data_ingestor.py` with ABC | None | No -- new file, nothing imports it yet |
| 2 | Make `SqliteIngester` extend `DataIngestor` | Minimal | No -- adding a base class doesn't change behavior |
| 3 | Update `server.py` return type to `DataStore`, type-annotate ingester as `DataIngestor` | Minimal | No -- same object returned, just typed more broadly |
| 4 | Update `__init__.py` exports (optional) | None | No -- additive |

**Total effort: ~15 minutes.**

#### Step 1: Create the ABC

**New file:** `mcp-server/src/data_store/data_ingestor.py` (~10 lines)

#### Step 2: Extend SqliteIngester

```python
# Before:
class SqliteIngester:

# After:
from data_store.data_ingestor import DataIngestor

class SqliteIngester(DataIngestor):
```

No other changes needed -- the method signature already matches.

#### Step 3: Update server.py

```python
# Before:
def build_data_store(csv_file_path: str) -> SqliteDataStore:

# After:
def build_data_store(csv_file_path: str) -> DataStore:
    ...
    ingester: DataIngestor = SqliteIngester()
    ...
```

#### Step 4: No test changes required

All existing tests instantiate `SqliteIngester` directly. They continue to work unchanged.

### YAGNI Assessment

**Verdict: The abstraction IS justified. This is NOT premature.**

**For:**
1. **Near-zero cost.** One new file, 10 lines of code, two changed lines in `sqlite_ingester.py`. This is adding a type, not a framework.
2. **Pattern already established.** `DataStore` has an ABC. `EnrichmentRule` has an ABC. The `chat-server` has `LLMClient` ABC. Not having `DataIngestor` ABC is the exception.
3. **Communicates intent.** The ABC says "this is a boundary you can swap."
4. **Prevents accidental coupling.** Typing against the ABC makes the contract explicit.
5. **Testability improves.** Can mock ingestion without needing a real SQLite database.

**Against (and why they don't hold):**
- "Only one implementation exists" -- Same was true of `DataStore` when it was created.
- "Ingestion only happens at startup" -- Lifecycle doesn't determine abstraction need.

**What NOT to do:**
- Do NOT add a factory pattern yet (zero benefit with one backend)
- Do NOT add a `BackendType` enum
- Do NOT make the ABC async
- Do NOT create a shared base class for ingester implementations
- Do NOT refactor the enrichment pipeline as part of this change

---

## Combined Architecture Scores

### Clean Architecture Score (Current)

| Category | Score | Notes |
|----------|-------|-------|
| Dependency Rule | 8/10 | Dependencies point inward correctly. `Config` placement is the one concern. |
| Layer Purity | 7/10 | Entity layer is clean. `Config.get()` in default params bleeds infrastructure. |
| Component Structure | 9/10 | No cycles. Clean DAG. Good stability/abstractness positioning. |
| Infrastructure Isolation | 7/10 | SQLite properly contained for querying, NOT for ingestion. |
| SOLID Design | 5/10 | Major SRP violation in `SqliteDataStore`. DIP violation for ingestion. |
| **Overall** | **7/10** | Fundamentally sound architecture with two clear, fixable gaps. |

### Projected Score (After Both Refactors)

| Category | Current | Projected | Delta |
|----------|---------|-----------|-------|
| Dependency Rule | 8/10 | 9/10 | +1 (ABC for ingestion) |
| Layer Purity | 7/10 | 8/10 | +1 (query building separated) |
| Component Structure | 9/10 | 9/10 | -- |
| Infrastructure Isolation | 7/10 | 9/10 | +2 (both sides behind ABCs) |
| SOLID Design | 5/10 | 8/10 | +3 (SRP + DIP fixed) |
| **Overall** | **7/10** | **9/10** | **+2** |

---

## Prioritized Action Items

| # | Issue | Severity | Effort | Files |
|---|-------|----------|--------|-------|
| 1 | **SRP violation:** `SqliteDataStore` mixes query building, validation, and execution | CRITICAL | Medium | `sqlite_data_store.py` -> new `sqlite_query_builder.py` |
| 2 | **DIP violation:** `SqliteIngester` has no ABC | HIGH | Low (15 min) | New `data_ingestor.py`, edit `sqlite_ingester.py` |
| 3 | **Return type leak:** `build_data_store()` returns `SqliteDataStore` instead of `DataStore` | MEDIUM | Trivial (1 line) | `server.py:40` |
| 4 | **Config bleed:** `Config.get()` in default parameters (import-time infrastructure coupling) | MEDIUM | Low | `sqlite_data_store.py:37`, `tool_handlers.py:72,135` |
| 5 | **OCP concern:** `_filter_to_sql_expression` uses if/elif chain instead of operator mapping | LOW | Low | `sqlite_data_store.py:138-154` |
| 6 | **Config placement:** `Config` class sits in `shared/` alongside entities | LOW | Medium | `shared/config.py` |

### Recommended Execution Order

1. **Refactor 2 first** (DataIngestor ABC) -- it is smaller, lower risk, and independently valuable
2. **Fix return type** in `server.py` -- one-line change, do it with refactor 2
3. **Refactor 1** (QueryBuilder extraction) -- larger change, higher value, do after the ABC is in place
4. **Config.get() cleanup** -- can be done independently at any time

---

## Summary of All File Changes

### Refactor 1: Query Separation

| File | Action | Lines |
|------|--------|-------|
| `mcp-server/src/data_store/sqlite_query_builder.py` | **CREATE** | ~200 lines (pure logic) |
| `mcp-server/src/data_store/sqlite_data_store.py` | **MODIFY** | Shrink ~320 -> ~90 lines |
| `tests/unit/mcp_server/test_sqlite_query_builder.py` | **CREATE** | ~20 new unit tests |
| All other files | No change | -- |

### Refactor 2: DataIngestor Interface

| File | Action | Lines |
|------|--------|-------|
| `mcp-server/src/data_store/data_ingestor.py` | **CREATE** | ~10 lines (ABC) |
| `mcp-server/src/data_store/sqlite_ingester.py` | **MODIFY** | Add 1 import + `(DataIngestor)` to class declaration |
| `mcp-server/src/server.py` | **MODIFY** | Change return type + add type annotation |
| `mcp-server/src/data_store/__init__.py` | **MODIFY** (optional) | Export both ABCs |
| All other files | No change | -- |
