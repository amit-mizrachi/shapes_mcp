# Date Handling Strategy Report

**Date:** 2026-02-28
**Status:** Analysis complete, pending decision

---

## Problem Statement

The current date enrichment pipeline detects date columns at ingestion time and materializes three derived columns per date column (`_years_ago`, `_year`, `_month`). While functional, this approach has architectural concerns:

1. **Schema pollution** — 3 extra columns per date column clutter the LLM's view
2. **Fixed derivations** — only years_ago/year/month; adding quarter, day-of-week, etc. requires code changes
3. **Staleness** — `_years_ago` bakes in `date.today()` at ingestion time
4. **Violates CSV-agnostic design** — the enrichment pipeline encodes domain assumptions about date semantics
5. **System prompt coupling** — the prompt must reference specific column naming patterns (`_years_ago`, `_year`)

This report evaluates four alternative approaches and recommends a path forward.

---

## Approaches Evaluated

### Approach A: Nominal Dates (Days Since Epoch)

**Concept:** Convert all detected dates to integers (days since 1970-01-01) during ingestion. Keep the original text column alongside the numeric one. Provide `today_days` in the `get_schema` response so the LLM can compute ages.

**How age calculation works:**
```
LLM calls get_schema() → sees date_of_birth_days (numeric), today_days = 20513
LLM calls aggregate(operation="avg", field="date_of_birth_days") → result: 12150
LLM computes internally: (20513 - 12150) / 365.25 = 22.9 years
```

**Strengths:**
- Eliminates 3 derived columns, replaces with 1 (`_days`)
- No staleness — today is provided at query time
- Simple server implementation (~120 LOC)
- No new tools needed

**Weaknesses:**
- **LLM must do arithmetic after every date query** — this is the critical flaw. Research shows LLMs consistently struggle with date arithmetic ([DATETIME benchmark](https://ownyourai.com/datetime-a-new-benchmark-to-measure-llm-translation-and-reasoning-capabilities/)), and errors produce silently wrong results rather than obvious failures.
- **Cannot express `(today - col) / 365.25` in the aggregate tool** — the `field` parameter accepts a column name, not an expression. The LLM would need to aggregate the raw day-number and post-process.
- **"Show birthdays this month" is impossible** — extracting month from epoch-days requires modular arithmetic on irregular month lengths.
- **Schema is confusing** — samples like `[7256, 9392, 4183]` are meaningless without context.
- **Filtering by age requires LLM arithmetic** — "people over 30" becomes `date_of_birth_days < 20513 - (30 * 365.25)` = `date_of_birth_days < 9555`. The LLM must compute this.

**Verdict:** Shifts complexity to the weakest link (the LLM). **Not recommended.**

---

### Approach B: SQLite Native Dates with Virtual Columns

**Concept:** Normalize dates to ISO 8601 format (`YYYY-MM-DD`) at ingestion time. Register "virtual columns" (e.g., `date_of_birth_age_years`, `date_of_birth_year`) that are computed at query time using SQLite's `julianday()` and `strftime()` functions. The LLM sees them in `get_schema` as regular numeric columns.

**How age calculation works:**
```
LLM calls get_schema() → sees date_of_birth_age_years (numeric, virtual)
LLM calls aggregate(operation="avg", field="date_of_birth_age_years")
    → Server expands to: SELECT AVG(CAST((julianday('now') - julianday("date_of_birth")) / 365.25 AS INTEGER))
    → result: 38.4
LLM responds: "The average age is 38.4 years"
```

**Strengths:**
- **Identical LLM experience to current enrichment** — the LLM just aggregates/filters on column names. Zero arithmetic.
- **Never stale** — computed at query time using `julianday('now')`.
- **No extra storage** — virtual columns exist only in the query, not in the database.
- **No new tools** — keeps the 3-tool architecture intact.

**Weaknesses:**
- **Significant server complexity** — every code path that handles column names (`_validate_column`, `_build_select_columns`, `_build_where_clause`, `_build_order_clause`, `_build_aggregation_expression`) must handle virtual columns. Requires a `_resolve_column(name) → str` helper.
- **Same number of schema columns as current enrichment** — the LLM still sees 3 virtual columns per date column (age, year, month). The schema pollution is identical, just without storage overhead.
- **Harder to test and debug** — SQL is generated dynamically for virtual columns.
- **Still needs date format conversion at ingestion** — must convert DD/MM/YYYY → ISO 8601.

**Implementation estimate:** ~160 LOC across 8 files, ~56 tests to write/rewrite.

**Verdict:** Architecturally clean but adds complexity to the query layer for the same LLM experience as the current approach. **A strong option if staleness is a real concern.**

---

### Approach C: Dedicated Date Tool

**Concept:** Add a new `date_calc` MCP tool with date-specific operations: age calculation, year/month extraction, date ranges.

```python
date_calc(
    column="date_of_birth",
    metric="age_years",        # "age_years", "year", "month", "in_range"
    operation="avg",           # "avg", "min", "max", "count" (optional aggregation)
    group_by="department",     # optional grouping
    range_start="2020-03-01",  # for date ranges
    range_end="2021-06-30",
    filters=[...],             # standard filters on other columns
)
```

**How age calculation works:**
```
LLM calls get_schema() → sees date_of_birth (date type)
LLM calls date_calc(column="date_of_birth", metric="age_years", operation="avg")
    → result: 38.4
```

**Strengths:**
- **Zero schema pollution** — no extra columns at all.
- **Semantically clear** — the LLM calls a tool explicitly designed for dates.
- **Always fresh** — computed at query time.
- **Handles date ranges naturally** — ISO date parameters for start/end.
- **Flat parameter structure** — low risk of Gemini MALFORMED_FUNCTION_CALL errors.

**Weaknesses:**
- **Adds a 4th tool** — increases the LLM's decision surface. The LLM must decide between `aggregate` and `date_calc` for grouped date metrics, creating overlap.
- **Low composability** — cannot combine date computation with the `transform` parameter, or cross-reference two date columns.
- **Filtering on computed values is awkward** — "count people over 30" requires filtering on the computed age, which doesn't map cleanly to the standard filter model (filters operate on stored columns, not computed values).

**Implementation estimate:** ~220 LOC across 7 files, ~150 new tests.

**Verdict:** Clean for pure date queries but creates tool overlap and composability issues. **Acceptable but not ideal.**

---

### Approach D: Keep Current Enrichment, Targeted Improvements

**Concept:** Retain the date enrichment pipeline with one key addition: an `_iso_date` column per date column, enabling native date range filtering.

**Current enrichment output per date column:**
| Column | Example | Purpose |
|---|---|---|
| `date_of_birth_years_ago` | `36` | Age/tenure computation |
| `date_of_birth_year` | `1989` | Year filtering/grouping |
| `date_of_birth_month` | `12` | Month filtering/grouping |

**Proposed addition:**
| Column | Example | Purpose |
|---|---|---|
| `date_of_birth_iso` | `1989-12-07` | Arbitrary date range filtering |

**Why this works:**
```
"Hired between March 2020 and June 2021":
  select_rows(filters=[
    {"column": "start_date_iso", "operator": ">=", "value": "2020-03-01"},
    {"column": "start_date_iso", "operator": "<=", "value": "2021-06-30"}
  ])
```
SQLite compares ISO 8601 strings lexicographically, which preserves chronological order. No special SQL functions needed.

**Strengths:**
- **Zero LLM arithmetic** — the LLM treats every column as a plain value to filter/sort/aggregate. This is the single most important property for Gemini Pro, which struggles with complex parameters and cannot reliably do date math.
- **Flat filter parameters** — simple comparisons with no nested structures, minimizing MALFORMED_FUNCTION_CALL risk.
- **Minimal code changes** — add one column to the existing enrichment rule. ~20 LOC.
- **Battle-tested** — the enrichment pipeline is already working, tested, and understood.
- **No new tools** — keeps the 3-tool architecture.

**Weaknesses:**
- **4 derived columns per date column** — schema pollution increases slightly.
- **`_years_ago` staleness** — still computed at ingestion time. However, in the Docker Compose architecture, the MCP server restarts per deployment. For values to drift by even 1 year, the server would need to run continuously for 365 days without restart.
- **Not CSV-agnostic** — still encodes date-specific enrichment logic. But the alternative approaches all require date detection and processing too — the work just moves to a different layer.

---

## Comparison Matrix

| Criterion | A: Epoch Days | B: Virtual Columns | C: Date Tool | D: Enrichment + ISO |
|---|---|---|---|---|
| **LLM arithmetic needed** | Yes (every query) | None | None | None |
| **Tool calls for avg age** | 2 + post-processing | 2 | 2 | 2 |
| **MALFORMED_FUNCTION_CALL risk** | Low | Low | Low | Low |
| **Schema columns per date** | +1 | +3 (virtual) | 0 | +4 |
| **Staleness** | None | None | None | Low (restart clears) |
| **Date range queries** | Hard (LLM computes) | Easy | Easy | Easy (with ISO col) |
| **Birthday-this-month queries** | Impossible | Easy | Easy | Easy |
| **New tools** | 0 | 0 | 1 | 0 |
| **Server complexity** | Low (~120 LOC) | High (~160 LOC) | Medium (~220 LOC) | Very low (~20 LOC) |
| **Test impact** | ~26 rewritten | ~56 rewrite/new | ~150 new | ~5 new |
| **Risk of LLM errors** | High | Low | Medium | Low |
| **Storage overhead** | +1 col | 0 | 0 | +1 col |

---

## Recommendation

### Primary: Approach B (Virtual Columns) — Best Architecture

**If the goal is to drop the enrichment pipeline entirely**, virtual columns are the strongest option. They provide:
- The same simple LLM experience (treat columns as regular numeric values)
- Zero staleness (query-time computation)
- No storage overhead
- No new tools

The tradeoff is server-side complexity in the query layer (~160 LOC), but it's well-contained in `sqlite_data_store.py` behind a `_resolve_column()` helper.

**Implementation path:**
1. Add `"date"` as a recognized `detected_type` in column detection
2. Replace `DateEnrichmentRule` with a `DateNormalizationRule` that converts dates to ISO 8601 in-place
3. Register virtual columns at schema time: `{col}_age_years`, `{col}_year`, `{col}_month`
4. Add `_resolve_column(name)` to `SqliteDataStore` that returns SQL expressions for virtual columns
5. Update `_validate_column` to accept virtual column names
6. Update `get_schema` to include virtual columns with computed sample values
7. Update system prompt to remove `_years_ago` references

### Fallback: Approach D (Enrichment + ISO) — Least Risk

**If minimizing implementation risk is the priority**, keep the current enrichment and just add an ISO date column. This is ~20 LOC of changes, maintains everything that already works, and solves the one gap (date range queries) with the simplest possible mechanism.

### Not Recommended

- **Approach A (Epoch Days)** — Shifts date math to the LLM, which is the least reliable component. Cannot handle month/year extraction. Silent errors.
- **Approach C (Date Tool)** — Creates tool overlap with `aggregate`, increases LLM decision surface, and adds composability issues. The improvement over enrichment/virtual-columns doesn't justify the added complexity.

---

## Appendix: LLM Query Traces

### "Who is the youngest employee?"

| Approach | Tool Calls | LLM Arithmetic |
|---|---|---|
| Current | `select_rows(order_by="dob_years_ago", order="asc", limit=1)` | None |
| Virtual | `select_rows(order_by="dob_age_years", order="asc", limit=1)` | None |
| Epoch | `select_rows(order_by="dob_days", order="desc", limit=1)` | Must understand "largest = youngest" |
| Date Tool | `date_calc(column="dob", metric="age_years", operation="min")` | None |

### "Average age by department?"

| Approach | Tool Calls | LLM Arithmetic |
|---|---|---|
| Current | `aggregate(op="avg", field="dob_years_ago", group_by="team")` | None |
| Virtual | `aggregate(op="avg", field="dob_age_years", group_by="team")` | None |
| Epoch | `aggregate(op="avg", field="dob_days")` + mental math | `(20513 - result) / 365.25` |
| Date Tool | `date_calc(column="dob", metric="age_years", op="avg", group_by="team")` | None |

### "Employees hired in last 2 years?"

| Approach | Tool Calls | LLM Arithmetic |
|---|---|---|
| Current | `select_rows(filters=[{col: "start_years_ago", op: "<=", val: 2}])` | None |
| Virtual | `select_rows(filters=[{col: "start_age_years", op: "<=", val: 2}])` | None |
| Epoch | `select_rows(filters=[{col: "start_days", op: ">", val: 19782}])` | `20513 - 730 = 19782` |
| Date Tool | `date_calc(column="start_date", metric="in_range", range_start="2024-02-28")` | None |

### "Birthdays this month?"

| Approach | Tool Calls | LLM Arithmetic |
|---|---|---|
| Current | `select_rows(filters=[{col: "dob_month", val: 2}])` | None |
| Virtual | `select_rows(filters=[{col: "dob_month", val: 2}])` | None |
| Epoch | **Impossible** without additional tooling | N/A |
| Date Tool | `date_calc(column="dob", metric="month", filters=[{val: 2}])` | None |
