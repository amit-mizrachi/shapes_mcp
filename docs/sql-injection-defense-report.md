# SQL Injection Defense Report

An analysis of the six mechanisms that protect the shapes-mcp database from SQL injection attacks.

---

## 1. Parameterized Queries

**Where:** `data_store/sqlite_data_store.py:313` — `connection.execute(sql_query, params)`

Every user-supplied **value** (filter values, LIMIT counts, HAVING thresholds, CASE WHEN constants) is passed to SQLite through `?` placeholders — never interpolated into the SQL string.

### How it works

When you write:

```python
cursor.execute('SELECT * FROM people WHERE "age" > ?', [30])
```

SQLite's query engine processes it in two separate phases:

1. **Parse phase** — the SQL text `SELECT * FROM people WHERE "age" > ?` is compiled into an execution plan. The `?` is treated as a typed hole, not as text to splice in. The SQL structure is locked in at this point.
2. **Bind phase** — the value `30` is bound to that hole. SQLite knows it's a data value, not SQL syntax. No amount of creative formatting can make it escape the value context.

If an attacker sends `"30; DROP TABLE people"` as a value, SQLite sees one string literal in the value slot — it never re-parses the SQL.

### Where this is applied in the codebase

| Use case | Code location | What gets parameterized |
|---|---|---|
| Filter values (`=`, `>`, `LIKE`, etc.) | `_build_where_clause` (line 134) | `params.append(filter_condition.value)` |
| IN-list values | `_build_where_clause` (line 132) | `params.extend(filter_condition.value)` — one `?` per list item |
| LIMIT | `select_rows` (line 67), `_build_aggregated_sql_query` (line 276) | `params.append(limit)` |
| HAVING threshold | `_build_having_clause` (line 252) | `[having_value]` |
| CASE WHEN then/else constants | `_build_case_expression` (lines 220-230) | `params.append(case.then_multiply)`, `params.append(case.then_value)`, etc. |
| INSERT row data | `sqlite_ingester.py` (line 39-41) | `executemany(..., all_values)` with `?` placeholders |

### What this blocks

Any attempt to inject SQL through a **value field**. For example:

```json
{"column": "name", "operator": "=", "value": "'; DROP TABLE people; --"}
```

The entire string `'; DROP TABLE people; --` is treated as a single value to compare against. SQLite never interprets it as SQL syntax.

---

## 2. Column Name Allowlist (`_validate_column`)

**Where:** `data_store/sqlite_data_store.py:279-281`

```python
def _validate_column(self, column: str) -> None:
    if column not in self._valid_columns:
        raise ValueError(f"Column '{column}' not found. Valid columns: {sorted(self._valid_columns)}")
```

### How it works

At construction time, `SqliteDataStore.__init__` (line 23) builds a set of known column names from the table schema:

```python
self._valid_columns = {c.name for c in table_schema.columns}
```

This set is derived from the actual CSV headers that were ingested (after sanitization — see mechanism #6). It might contain values like `{"name", "age", "city", "score", "active"}`.

Every time user input is used as a column name, it is checked against this set **before** it touches any SQL string. If it's not in the set, a `ValueError` is raised and the query is never constructed.

### Every call site

| Context | Code location |
|---|---|
| SELECT field list | `_build_select_columns` (line 113): `self._validate_column(field_name)` |
| WHERE clause columns | `_build_where_clause` (line 129): `self._validate_column(filter_condition.column)` |
| ORDER BY column | `_build_order_clause` (line 161): `self._validate_column(order_by)` |
| Aggregation field | `_validate_aggregation_args` (line 184): `self._validate_column(field)` |
| GROUP BY columns | `_validate_aggregation_args` (line 187): `self._validate_column(col)` |
| Transform source column | `_validate_transform_columns` (line 198): `self._validate_column(transform.source_column)` |
| Transform CASE WHEN columns | `_validate_transform_columns` (lines 200-201): `self._validate_column(fc.column)` |

### What this blocks

Any attempt to inject SQL through a **column name field**. For example:

```json
{"column": "\"; DROP TABLE people; --", "operator": "=", "value": "x"}
```

The string `"; DROP TABLE people; --` is not in `_valid_columns`, so `_validate_column` raises `ValueError` before any SQL is built. The query never reaches SQLite.

This is critical because column names **cannot** be parameterized with `?` — they are structural parts of SQL. The allowlist is the only defense here.

---

## 3. Operator Allowlist (Pydantic `FilterCondition`)

**Where:** `shared/modules/data/filter_condition.py:7,21-24`

```python
VALID_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "LIKE", "NOT LIKE", "IN", "NOT IN", "IS NULL", "IS NOT NULL"}

@model_validator(mode="after")
def _validate(self) -> FilterCondition:
    if self.operator not in VALID_OPERATORS:
        raise ValueError(f"Invalid filter operator '{self.operator}'. Must be one of: {sorted(VALID_OPERATORS)}")
```

### How it works

Like column names, SQL operators cannot be parameterized — they are structural SQL. The operator goes directly into the SQL string in `_filter_to_sql_expression` (line 155):

```python
return f'{col} {filter_condition.operator} ?'
```

The Pydantic model `FilterCondition` validates the operator on object construction. When FastMCP deserializes the user's JSON input into a `FilterCondition`, Pydantic's `model_validator` fires and rejects any operator not in the fixed set.

Every value in `VALID_OPERATORS` is a legitimate SQL comparison operator — none of them can break out of the WHERE clause context or introduce new SQL statements.

### What this blocks

Any attempt to inject SQL through the **operator field**:

```json
{"column": "name", "operator": "= 1; DROP TABLE people; --", "value": "x"}
```

The Pydantic validator rejects `"= 1; DROP TABLE people; --"` because it's not in `VALID_OPERATORS`. The `FilterCondition` object is never constructed, so no query is ever built.

### Defense-in-depth gap (noted)

This validation happens only in the Pydantic layer, not at the SQL construction layer. If code ever constructs a `FilterCondition` using `model_construct()` (which bypasses validators), the operator would flow unchecked into SQL. The `SqliteDataStore` itself has no redundant check.

---

## 4. Aggregation Operation Allowlist

**Where:** `data_store/sqlite_data_store.py:176-179` and `191-195`

```python
def _validate_aggregation_args(self, operation: str, field, group_by_cols) -> str:
    sql_operation = operation.upper()
    if sql_operation not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
        raise ValueError(f"Unsupported aggregation op: {operation}. Use count, sum, avg, min, or max.")
    ...
```

### How it works

The aggregation operation (e.g., `"count"`, `"sum"`) is user-supplied and ends up directly in the SQL string (line 241):

```python
return f'{sql_operation}("{field}")'
# Produces: COUNT("age"), SUM("salary"), etc.
```

Since this is structural SQL (a function name), it cannot use `?` parameterization. Instead, the code normalizes the input to uppercase and checks it against the hardcoded tuple `("COUNT", "SUM", "AVG", "MIN", "MAX")`.

This check happens **inside `SqliteDataStore` itself** (unlike the operator check which relies on Pydantic). Both `_validate_aggregation_args` and `_validate_aggregation_op` enforce it, covering both the regular and transform-based aggregation paths.

### Additional validations in the same method

- `field` is validated via `_validate_column` (line 184) — blocking column injection in aggregation
- Every `group_by` column is validated via `_validate_column` (lines 186-187)

### What this blocks

```json
{"operation": "COUNT(*) FROM people; DROP TABLE people; --", "field": "age"}
```

The string doesn't match any of the five allowed operations, so `ValueError` is raised before any SQL is constructed.

---

## 5. `PRAGMA query_only = ON`

**Where:** `data_store/sqlite_data_store.py:305`

```python
@asynccontextmanager
async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(self._db_uri)
    await connection.execute("PRAGMA query_only = ON")
    ...
```

### How it works

Every database connection opened for queries has `PRAGMA query_only = ON` set immediately after creation. This is a SQLite engine-level restriction that makes the connection **read-only**. The following SQL statements are blocked by SQLite itself:

- `INSERT` — cannot add rows
- `UPDATE` — cannot modify rows
- `DELETE` — cannot remove rows
- `DROP TABLE` — cannot delete tables
- `CREATE TABLE` — cannot create tables
- `ALTER TABLE` — cannot modify table structure
- Any other DDL or DML statement

### Why this matters as a last line of defense

Even if all other validations were somehow bypassed and an attacker managed to inject arbitrary SQL, the damage would be limited to **reading data**. They could not:

- Delete the table (`DROP TABLE`)
- Modify data (`UPDATE`, `DELETE`)
- Create backdoor tables
- Corrupt the database

This is a **defense-in-depth** measure. It doesn't prevent injection — it limits the blast radius if injection occurs. The worst case becomes unauthorized data reads, not data destruction.

### Scope

This PRAGMA is set on the `_connection()` context manager used by `_run_query` and `_run_query_with_total` — the only two methods that execute user-influenced queries. The ingestion path (`sqlite_ingester.py`) uses a separate `sqlite3.connect()` call without this PRAGMA, which correctly allows it to create and populate tables at startup.

---

## 6. Identifier Sanitization at Ingestion

**Where:** `data_store/csv_parser.py:12,59-61`

```python
_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")

@staticmethod
def _sanitize_identifier(raw_name: str) -> str:
    """Lowercase, replace non-alphanumeric runs with underscores, strip edges."""
    return _SANITIZE_PATTERN.sub("_", raw_name.lower()).strip("_")
```

### How it works

When CSV data is ingested, both the **table name** and all **column names** pass through `_sanitize_identifier`. This function:

1. Lowercases the entire string
2. Replaces every run of non-`[a-z0-9]` characters with a single `_`
3. Strips leading/trailing underscores

The result is that `_valid_columns` (mechanism #2) can only ever contain identifiers matching the pattern `[a-z0-9_]+`. No identifier can contain:

- Quotes (`"`, `'`) — cannot break out of quoted identifier context
- Semicolons (`;`) — cannot terminate statements
- Dashes (`-`, `--`) — cannot start SQL comments
- Parentheses, spaces, or any other SQL metacharacter

### Example transformations

| Raw CSV header | Sanitized identifier |
|---|---|
| `First Name` | `first_name` |
| `user's "email"` | `user_s_email` |
| `Robert"; DROP TABLE--` | `robert_drop_table` |
| `age (years)` | `age_years` |

### Why this is foundational

This sanitization creates a guarantee that flows through the entire system:

1. CSV headers are sanitized at ingestion time (`csv_parser.py`)
2. Sanitized names become database column names (`sqlite_ingester.py:24-30`)
3. Sanitized names populate `_valid_columns` in the data store (`sqlite_data_store.py:23`)
4. The column allowlist (mechanism #2) can only contain these safe identifiers
5. Any user-supplied column name must exactly match a sanitized identifier to be accepted

Even the table name goes through the same sanitization via `path_to_table_name` (line 64-66), so the table name in queries like `FROM "{self._table_schema.table_name}"` is also guaranteed clean.

### Enrichment-derived columns

Columns added by enrichment rules (`DateEnrichmentRule`, `FullNameEnrichmentRule`) produce hardcoded names like `full_name`, `{col}_year`, `{col}_month`, `{col}_years_ago`. Since `{col}` is itself already sanitized, these derived names are also safe and consist only of `[a-z0-9_]` characters.

---

## How They Work Together

These six mechanisms form layers — each one catches what the others might miss:

```
User Input (JSON from MCP client)
  │
  ├─ Values ──────────► [1] Parameterized queries (? placeholders)
  │                      SQLite treats them as data, never as SQL syntax.
  │
  ├─ Column names ───► [2] Column allowlist (_validate_column)
  │                      Rejects anything not in the known schema.
  │                      ▲
  │                      │
  │                      └── [6] Identifier sanitization (csv_parser)
  │                           The allowlist itself can only contain [a-z0-9_].
  │
  ├─ Operators ──────► [3] Operator allowlist (Pydantic FilterCondition)
  │                      Only =, !=, >, >=, <, <=, LIKE, NOT LIKE, IN, NOT IN,
  │                      IS NULL, IS NOT NULL are permitted.
  │
  ├─ Agg operations ─► [4] Aggregation allowlist (_validate_aggregation_args)
  │                      Only COUNT, SUM, AVG, MIN, MAX are permitted.
  │
  └─ If ALL ELSE FAILS:
                        [5] PRAGMA query_only = ON
                         Even successful injection cannot modify or delete data.
```

No single mechanism is sufficient alone, but together they cover every path through which user input can reach SQL.
