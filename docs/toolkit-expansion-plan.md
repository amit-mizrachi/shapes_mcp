# Toolkit Expansion Plan — shapes_mcp

**Date:** 2026-02-27
**Status:** Implementation in progress
**Total estimated LOC:** ~230

---

## Problem Statement

Two automated testing agents (db-destroyer, db-edgecaser) found 16 issues. The current MCP toolset (`get_schema`, `select_rows`, `aggregate`) lacks general-purpose primitives needed for common data analysis questions. Rather than domain-specific fixes (e.g., a salary enrichment rule), we're adding **general-purpose tools and parameters** that solve these issues for any dataset.

## Findings Inventory

| ID | Severity | Finding | Root Cause |
|----|----------|---------|------------|
| E1-E4 | CRITICAL | Salary mixing — averages/comparisons mix currencies and time units silently | No conditional math (CASE WHEN) on columns |
| E5 | HIGH | Default limit=20 silently truncates results | No total_count in response |
| E6 | HIGH | No negation (`!=`, `NOT IN`) in filters | Operator whitelist too small |
| E7 | HIGH | No per-group top-N / window functions | Would need ROW_NUMBER(), deferred |
| E8 | HIGH | Name parsing broken for nicknames | Bug in FullNameEnrichmentRule, separate fix |
| E9 | HIGH | LLM sorts youngest/oldest wrong | System prompt lacks guidance |
| E10 | HIGH | Exact match instead of LIKE for job search | System prompt lacks guidance |
| E11 | HIGH | Multi-criteria questions partially answered | Needs better filters + OR logic |
| E12 | HIGH | Date text sorting broken (DD/MM/YYYY) | System prompt should direct to _year/_years_ago columns |
| E13 | MEDIUM | No median/percentile | SQLite has no built-in MEDIAN, deferred |
| E14 | MEDIUM | No multi-column GROUP BY | group_by accepts only a single string |
| E15 | MEDIUM | No current date awareness | System prompt has no date context |
| E16 | MEDIUM | No self-join/lookup | Single-table architecture, deferred |

---

## Implementation Plan — 7 Priorities

### Priority 1: System Prompt Improvements (~5 LOC)

**Files:** `shared/config.py`

**What:** Update the LLM system prompt with data quality rules, query tips, and current date.

**New prompt content:**
```
DATA QUALITY RULES:
- Before aggregating numeric columns, check if related columns indicate different units or categories.
  For example, if a 'salary_amount' column exists alongside 'salary_type' (Yearly/Monthly/Hourly)
  or 'salary_currency' (USD/GBP/ILS), you MUST use the transform parameter to normalize values,
  or filter to a single type/currency before aggregating.
- When results are truncated (count < total_count), ALWAYS tell the user how many total results exist.

QUERY TIPS:
- Use LIKE operator for partial text matching (e.g., job LIKE '%Manager%' finds all Manager roles).
- For 'youngest' or 'most recent', sort by the _year or _years_ago columns, not text date columns.
  'Youngest' = smallest _years_ago value (ORDER BY date_of_birth_years_ago ASC).
- For age-related queries, use date_of_birth_years_ago. For tenure, use start_date_years_ago.
- When a question asks about 'all' records, set limit to 100 or be aware the default is 20.
- Use aggregate() with group_by to discover what distinct values exist in a column before filtering.
- Today's date is {current_date}.
```

**Findings addressed:** E5 (partial), E9, E10, E12, E15, partial E1-E4

---

### Priority 2: Extended Filter Operators (~30 LOC)

**Files:** `shared/modules/data/filter_condition.py`, `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** Add `!=`, `NOT IN`, `NOT LIKE`, `IS NULL`, `IS NOT NULL` to the filter operator whitelist.

**Current operators:** `=`, `>`, `>=`, `<`, `<=`, `LIKE`, `IN`
**New operators:** `!=`, `NOT IN`, `NOT LIKE`, `IS NULL`, `IS NOT NULL`

**Example usage:**
```json
{"filters": [{"column": "city", "operator": "!=", "value": "London"}]}
{"filters": [{"column": "city", "operator": "NOT IN", "value": ["London", "Tel Aviv"]}]}
{"filters": [{"column": "salary_amount", "operator": "IS NOT NULL", "value": ""}]}
```

**Generated SQL:**
```sql
WHERE "city" != ?
WHERE "city" NOT IN (?,?)
WHERE "salary_amount" IS NOT NULL
```

**Security:** Same parameterized pattern as existing operators. IS NULL/IS NOT NULL take no value parameter. Column whitelist still applies.

**Findings addressed:** E6, partial E11

---

### Priority 3: Truncation Warning — `total_count` (~30 LOC)

**Files:** `shared/modules/data/query_result.py`, `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** Add `total_count` field to query responses. Run a parallel `SELECT COUNT(*)` with the same WHERE clause. When `count < total_count`, the LLM knows truncation occurred.

**Current response:** `{"data": [...], "count": 20}`
**New response:** `{"data": [...], "count": 20, "total_count": 107}`

**Implementation:** Add a `_count_total` method to `SqliteDataStore` that runs `SELECT COUNT(*) FROM table WHERE ...` with the same params. Call it from `select_rows` and grouped `aggregate`. Add `total_count: int | None` to `QueryResult`.

**Security:** Count query uses identical WHERE clause and params. No new SQL surface.

**Findings addressed:** E5 (full fix)

---

### Priority 4: Multi-Column GROUP BY (~25 LOC)

**Files:** `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/repository/data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** Accept `group_by` as either a string or a list of strings.

**Example usage:**
```json
{"operation": "count", "group_by": ["city", "job"], "order_by": "@result", "order": "desc"}
```

**Generated SQL:**
```sql
SELECT "city", "job", COUNT(*) AS result
FROM "people_list_export"
GROUP BY "city", "job"
ORDER BY result DESC LIMIT ?
```

**Implementation:** Normalize `group_by` to a list internally. Validate each element against column whitelist. Build `GROUP BY "col1", "col2"` string. Update `_build_aggregated_sql_query` and `_validate_aggregation_args`.

**Security:** Each column validated against `_valid_columns`. Quoted in SQL. Same pattern as existing single group_by.

**Findings addressed:** E14

---

### Priority 5: HAVING Clause (~25 LOC)

**Files:** `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/repository/data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** Add `having_operator` and `having_value` params to `aggregate`. Constrained to operate only on the aggregation result — no arbitrary HAVING expressions.

**Example usage:**
```json
{"operation": "count", "group_by": "job", "having_operator": ">", "having_value": 5, "order_by": "@result", "order": "desc"}
```

**Generated SQL:**
```sql
SELECT "job", COUNT(*) AS result
FROM "people_list_export"
GROUP BY "job"
HAVING result > ?
ORDER BY result DESC LIMIT ?
-- params: [5, 20]
```

**Implementation:** `having_operator` validated against comparison operators (`=`, `!=`, `>`, `>=`, `<`, `<=`). `having_value` is a float bound via `?`. If `group_by` is None and `having_value` is provided, return validation error.

**Security:** Operator from fixed set. Value parameterized. No injection vector.

**Findings addressed:** HAVING queries, partial E7

---

### Priority 6: Computed Expressions — TransformExpression (~100 LOC)

**Files:** `shared/modules/data/transform_expression.py` (NEW), `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/repository/data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** A structured CASE WHEN expression that the LLM can use on both `select_rows` and `aggregate`. Maps to SQL `CASE WHEN ... THEN ... END`.

**New models:**
```python
class TransformCase(ShapesBaseModel):
    when: list[FilterCondition]      # Reuses existing filter model for conditions
    then_multiply: float | None = None  # Multiply source_column by this
    then_value: float | None = None     # Replace with this constant

class TransformExpression(ShapesBaseModel):
    source_column: str                # Column to transform
    cases: list[TransformCase]        # CASE WHEN branches (max 10)
    else_multiply: float | None = None  # Default multiplier
    else_value: float | None = None     # Default constant
    alias: str                         # Name for the computed result
```

**Example usage — salary normalization (the CRITICAL fix):**
```json
{
  "operation": "avg",
  "transform": {
    "source_column": "salary_amount",
    "cases": [
      {"when": [{"column": "salary_type", "value": "Monthly"}], "then_multiply": 12},
      {"when": [{"column": "salary_type", "value": "Hourly"}], "then_multiply": 2080}
    ],
    "else_multiply": 1,
    "alias": "annual_salary"
  },
  "filters": [{"column": "salary_currency", "value": "GBP £"}],
  "group_by": "city",
  "order_by": "@result",
  "order": "desc"
}
```

**Generated SQL:**
```sql
SELECT "city", AVG(
  CASE
    WHEN "salary_type" = ? THEN "salary_amount" * ?
    WHEN "salary_type" = ? THEN "salary_amount" * ?
    ELSE "salary_amount" * ?
  END
) AS result
FROM "people_list_export"
WHERE "salary_currency" = ?
GROUP BY "city"
ORDER BY result DESC LIMIT ?
-- params: ["Monthly", 12, "Hourly", 2080, 1, "GBP £", 20]
```

**Also works on select_rows** — adds the computed column to output:
```sql
SELECT "full_name", "salary_amount",
  CASE
    WHEN "salary_type" = ? THEN "salary_amount" * ?
    WHEN "salary_type" = ? THEN "salary_amount" * ?
    ELSE "salary_amount" * ?
  END AS "annual_salary"
FROM "people_list_export"
ORDER BY "annual_salary" DESC LIMIT ?
```

**Validation:**
- `source_column` validated against column whitelist
- Each `when` clause reuses `FilterCondition` (already validated)
- `then_multiply` / `else_multiply` are floats, bound via `?`
- `alias` must match `^[a-z][a-z0-9_]{0,63}$` and NOT collide with existing columns
- Max 10 cases

**Security:** All column names whitelist-validated. All values parameterized. Operator set is the existing FilterCondition set. No string interpolation of user input.

**Findings addressed:** E1, E2, E3, E4 (all CRITICAL)

---

### Priority 7: OR Conditions (~15 LOC)

**Files:** `mcp-server/src/repository/sqlite_data_store.py`, `mcp-server/src/repository/data_store.py`, `mcp-server/src/tool_handlers.py`

**What:** Add `filter_logic` parameter to `select_rows` and `aggregate`. Defaults to `"AND"`, can be `"OR"`.

**Example usage:**
```json
{
  "filters": [
    {"column": "salary_amount", "operator": ">", "value": 80000},
    {"column": "job", "operator": "LIKE", "value": "%Manager%"}
  ],
  "filter_logic": "OR"
}
```

**Generated SQL:**
```sql
WHERE "salary_amount" > ? OR "job" LIKE ?
```

**Security:** `filter_logic` validated to be exactly `"AND"` or `"OR"`. Only changes the join keyword between existing parameterized clauses.

**Findings addressed:** OR logic, partial E11

---

## Coverage Matrix

| Finding | P1 Prompt | P2 Operators | P3 total_count | P4 Multi-Group | P5 HAVING | P6 Transform | P7 OR | Covered? |
|---------|:---------:|:------------:|:--------------:|:--------------:|:---------:|:------------:|:-----:|:--------:|
| E1 Salary type mixing | partial | | | | | **FULL** | | YES |
| E2 Cross-currency avg | partial | | | | | **FULL** | | YES |
| E3 Gender pay gap | partial | | | | | **FULL** | | YES |
| E4 Payroll sums mix | partial | | | | | **FULL** | | YES |
| E5 Silent truncation | partial | | **FULL** | | | | | YES |
| E6 No negation | | **FULL** | | | | | | YES |
| E7 Per-group top-N | | | | | partial | | | PARTIAL |
| E8 Nickname parsing | | | | | | | | NO (bug fix) |
| E9 Sort direction | **FULL** | | | | | | | YES |
| E10 Exact vs LIKE | **FULL** | | | | | | | YES |
| E11 Multi-criteria | | partial | | | | | partial | PARTIAL |
| E12 Date sorting | **FULL** | | | | | | | YES |
| E13 Median | | | | | | | | NO (deferred) |
| E14 Multi-column GROUP BY | | | | **FULL** | | | | YES |
| E15 No current date | **FULL** | | | | | | | YES |
| E16 Self-join | | | | | | | | NO (deferred) |

**Result: 12/16 findings fully or partially addressed.**

Remaining 4 not covered:
- **E7** (per-group top-N) — needs window functions, major complexity
- **E8** (nickname parsing) — bug fix in FullNameEnrichmentRule, separate task
- **E13** (median) — SQLite has no built-in MEDIAN
- **E16** (self-join) — needs multi-table architecture

---

## Security Invariants (maintained by ALL changes)

1. **Column whitelist** — every column reference validated against `_valid_columns`
2. **Parameterized queries** — all values bound via `?`, no string interpolation
3. **PRAGMA query_only = ON** — database remains read-only
4. **Operator whitelist** — expanded but still a fixed set in code
5. **Pydantic validation** — all new models use `ShapesBaseModel` with validators

---

## Files Modified/Created Summary

| File | Priorities |
|------|-----------|
| `shared/config.py` | P1 |
| `shared/modules/data/filter_condition.py` | P2 |
| `shared/modules/data/query_result.py` | P3 |
| `shared/modules/data/transform_expression.py` **(NEW)** | P6 |
| `mcp-server/src/repository/data_store.py` | P2,P3,P4,P5,P6,P7 |
| `mcp-server/src/repository/sqlite_data_store.py` | P2,P3,P4,P5,P6,P7 |
| `mcp-server/src/tool_handlers.py` | P2,P3,P4,P5,P6,P7 |
