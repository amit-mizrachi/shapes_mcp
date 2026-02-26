# Rule-Based Column Enrichment

## Problem

The MCP server exposes three structured tools — `get_schema`, `select_rows`, `aggregate` — that let the LLM query a CSV-loaded SQLite database **without writing raw SQL**. This works well for columns that exist verbatim in the CSV, but fails when users ask questions that require **derived values**.

**Real example from the dataset:**
The CSV contains `date_of_birth` (e.g. `"07/12/1989"`) stored as TEXT. When a user asks *"What is the average age of employees?"*, the LLM cannot answer — there is no `age` column, and computing `years(today - date_of_birth)` would require raw SQL, which defeats the purpose of the structured tool design.

The same problem applies to:
- *"How many employees started in 2023?"* — requires extracting a year from `start_date`
- *"How many were born in January?"* — requires extracting a month from `date_of_birth`

**Constraint:** The LLM must not write SQL queries. All answers must come through `select_rows` and `aggregate` using column names and filters.

## Solutions Considered

We evaluated six approaches, ranked by feasibility:

0. **Expose a tool that adds a column - immutability of database after ingestion (bad for many reasons).
1. **Rule-based enrichment (chosen)** — Detect enrichable columns at ingestion time and materialize derived columns (e.g. `years_ago`, `year`, `month`) as real SQLite columns. Simple, no tool changes, LLM uses them like any other column.
2. **Hybrid: rule-based + constrained SQL** — Combine pre-materialized columns with a read-only SQL tool that only allows SELECT with a whitelist of functions. More flexible but re-introduces SQL at the LLM level, conflicting with the design constraint.
3. **Constrained read-only SQL tool** — Let the LLM write SELECT queries with guardrails (read-only, no DDL, function whitelist). Powerful but defeats the purpose of the structured tool design.
4. **Expression column tool** — Add a new MCP tool that lets the LLM request computed columns via expressions like `YEAR(start_date)`. Requires the tool to understand date formats and parse expressions — added complexity for marginal benefit over pre-materialization.
5. **SQLite generated columns** — Use `ALTER TABLE ADD COLUMN ... AS (expression)` to define computed columns at the database level. Elegant but SQLite's date functions require ISO format, and our dates are DD/MM/YYYY — would need format conversion during ingestion anyway.
6. **LLM-driven enrichment** — Let the LLM itself suggest derived columns by analyzing the schema. Creative but non-deterministic, slow, and adds a dependency on LLM quality for basic data preparation.

## Solution

**Enrich the data at ingestion time.** Before the CSV rows are inserted into SQLite, a rule engine scans the parsed columns, detects enrichable patterns (e.g. date columns), and materializes new derived columns as real SQLite columns. The LLM then sees these columns in `get_schema` and can use them directly.

### Pipeline (before vs after)

**Before:**
```
CSVParser.parse() → ParsedCSV → SqliteIngester → SQLite
```

**After:**
```
CSVParser.parse() → ParsedCSV → ColumnEnricher.enrich() → enriched ParsedCSV → SqliteIngester → SQLite
```

The enricher sits between parsing and ingestion. It receives a `ParsedCSV` and returns a new `ParsedCSV` with additional columns appended and row dicts augmented with the derived values. Everything downstream — the repository, MCP tools — works unchanged.

> **Architecture review note:** Both the software architect and clean architecture agents independently recommended that enrichment be orchestrated in `server.py` (the composition root), not injected into the ingester. This also fixes an existing SRP issue where the ingester calls the CSV parser internally. After this change, the ingester accepts a `ParsedCSV` directly — it no longer knows about CSV files or enrichment.

---

## How It Works, Step by Step

### 1. The Enrichment Framework

Two classes form the framework:

**`EnrichmentRule` (ABC)** — Each rule implements two methods:
- `detect(columns, sample_rows)` — Examine existing column metadata and a sample of rows. Return a list of new `ColumnInfo` objects for columns this rule wants to add. Return `[]` if nothing applies.
- `apply(rows)` — Mutate each row dict in-place, adding the derived column values. Only called if `detect()` returned a non-empty list.

**`ColumnEnricher` (orchestrator)** — Holds a list of rules. Its `enrich(parsed_csv)` method:
1. Iterates over all rules, calling `detect()` on each
2. Collects rules that returned new columns (applicable rules)
3. If none are applicable, returns the original `ParsedCSV` unchanged
4. Otherwise, calls `apply()` on each applicable rule sequentially — rows are **shallow-copied** (not mutated in-place) so the input `ParsedCSV` is not modified
5. Returns a new `ParsedCSV` with the original columns + new columns, and the enriched rows
6. After all rules apply, populates `samples` on derived `ColumnInfo` objects from the first 3 enriched rows — so the LLM sees example values like `[36, 48, 29]` in `get_schema`

### 2. Date Detection — How We Identify a Column Is a Date

The `DateEnrichmentRule` is the primary rule. Here is exactly how it decides whether a column contains dates:

**Step 1 — Skip numeric columns.**
If `column.detected_type == "numeric"`, skip immediately. Dates are always stored as text in CSV files. The CSVParser already classifies columns where 80%+ of values parse as float as `"numeric"`, so these are never date candidates.

**Step 2 — Collect non-empty sample values.**
From the first 20 rows of data (passed as `sample_rows`), extract all non-empty, stripped values for the candidate column. If there are zero non-empty values, skip the column.

**Step 3 — Try each known date format.**
We define a list of common date formats:

```python
_DATE_FORMATS = [
    "%d/%m/%Y",   # 28/01/1977
    "%m/%d/%Y",   # 07/12/1989
    "%Y-%m-%d",   # 1989-07-12
    "%d-%m-%Y",   # 28-01-1977
    "%m-%d-%Y",   # 07-12-1989
    "%Y/%m/%d",   # 1989/07/12
]
```

For each format, attempt to parse **every** sample value using `datetime.strptime(value, format)`. Count successes.

**Step 4 — Apply the 80% threshold.**
If `successes / total_samples >= 0.8` (80%), this format is a match. The **first** format that crosses the threshold wins. This means format order matters — `%d/%m/%Y` is tried before `%m/%d/%Y`, which is the correct priority for our dataset (dates like `28/01/1977` can only be DD/MM/YYYY).

**Step 5 — Register the column.**
If a format matched, store `(column_name, matched_format)` internally and return three new `ColumnInfo` objects:
- `{column_name}_years_ago` (numeric) — integer years elapsed since the date
- `{column_name}_year` (numeric) — the 4-digit year extracted from the date
- `{column_name}_month` (numeric) — the month number (1-12) extracted from the date

If no format matched across all 6 formats, the column is not a date — skip it.

**Why 20 rows?** Enough to be statistically confident without scanning the entire dataset. The 80% threshold allows for a few malformed values without rejecting the column.

**DD/MM vs MM/DD ambiguity:** When all values have day ≤ 12 (e.g. `07/06/1989`), both `%d/%m/%Y` and `%m/%d/%Y` would pass. Since `%d/%m/%Y` is tried first, it wins. This is a deliberate choice — the actual dataset uses DD/MM/YYYY format. For datasets where MM/DD is correct, the format order can be adjusted in config, or a future heuristic could be added. For now, first-match-wins is simple and sufficient.

### 3. How Derived Values Are Computed

Once `detect()` identifies date columns, `apply()` iterates over every row:

For each date column `(col_name, format)`:
1. Read the raw string value: `row[col_name]`
2. If empty or whitespace → set all three derived columns to `None`
3. Try `datetime.strptime(raw_value, format)`:
   - **`_years_ago`**: Calculate integer years between the parsed date and today. Uses exact calendar comparison: subtract years, then adjust down by 1 if today's (month, day) is before the date's (month, day). This matches how human age works.
   - **`_year`**: `parsed_date.year` (integer, e.g. `1977`)
   - **`_month`**: `parsed_date.month` (integer, 1-12)
4. If parsing fails (malformed value) → set all three to `None`

**No rows are dropped.** A single unparseable value just gets `None` in the derived columns.

### 4. How Columns Are Inserted Into SQLite

The enricher returns a `ParsedCSV` with the new columns appended to the `columns` list and the new values added to each row dict. The `SqliteIngester` is refactored to accept `ParsedCSV` directly (instead of a CSV path).

**Bug fix required:** The existing `_to_sql_value` method assumes all values are strings (from CSV). Enriched columns produce `int` or `None` — calling `.strip()` on those crashes. The method is updated with a type guard:

```python
@staticmethod
def _to_sql_value(raw_value, detected_type: str):
    if raw_value is None:
        return None
    if detected_type != "numeric":
        return str(raw_value)
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    stripped = str(raw_value).strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None
```

The table creation and row insertion logic is otherwise unchanged:
1. **`_create_table()`** — `detected_type == "numeric"` → `REAL`, else → `TEXT`
2. **`_insert_rows()`** — uses `_to_sql_value` per column, now safe for `int`/`None` values

Derived integer values (years_ago, year, month) are stored as `REAL` in SQLite, which is fine — SQLite is dynamically typed and the values behave correctly in aggregations and comparisons.

### 5. How the LLM Sees the New Columns

After enrichment, `get_schema` returns the full column list including derived columns. For our dataset, the LLM will see:

```
date_of_birth           TEXT
date_of_birth_years_ago REAL    ← NEW
date_of_birth_year      REAL    ← NEW
date_of_birth_month     REAL    ← NEW
start_date              TEXT
start_date_years_ago    REAL    ← NEW
start_date_year         REAL    ← NEW
start_date_month        REAL    ← NEW
```

Now the LLM can:
- `aggregate(operation="avg", field="date_of_birth_years_ago")` → average age
- `select_rows(filters=[{column: "date_of_birth_year", op: "=", value: 1977}])` → born in 1977
- `aggregate(operation="count", group_by="start_date_year")` → hires per year
- `select_rows(filters=[{column: "start_date_month", op: "=", value: 6}])` → started in June

### 6. Name Concatenation Rule

A secondary rule detects `first_name` + `last_name` column pairs and creates a `full_name` column. This is simpler:

- **detect()**: Check if both `first_name` and `last_name` exist in the column list, and `full_name` does not already exist
- **apply()**: For each row, concatenate `first_name` and `last_name` with a space, trimming whitespace

Our dataset already has a `full_name` column, so this rule will be a no-op. It exists for CSV files that split names into two columns.

---

## Concrete Example With Our Dataset

**Input CSV row:**
```
Full Name,Start Date,Date of Birth,First Name,Last Name,...
Alaric Finch-Sallow,03/06/2023,07/12/1989,Alaric,Finch-Sallow,...
```

**After CSVParser (sanitized, no enrichment):**
```python
{
    "full_name": "Alaric Finch-Sallow",
    "start_date": "03/06/2023",
    "date_of_birth": "07/12/1989",
    "first_name": "Alaric",
    "last_name": "Finch-Sallow",
    ...
}
```

**After ColumnEnricher (enriched):**
```python
{
    "full_name": "Alaric Finch-Sallow",
    "start_date": "03/06/2023",
    "date_of_birth": "07/12/1989",
    "first_name": "Alaric",
    "last_name": "Finch-Sallow",
    "start_date_years_ago": 2,         # today (2026-02-26) - 2023-06-03
    "start_date_year": 2023,
    "start_date_month": 6,
    "date_of_birth_years_ago": 36,     # today (2026-02-26) - 1989-12-07
    "date_of_birth_year": 1989,
    "date_of_birth_month": 12,
    ...
}
```

**SQLite table schema (new columns appended):**
```sql
CREATE TABLE "people_list_export" (
    "full_name" TEXT,
    "start_date" TEXT,
    "date_of_birth" TEXT,
    "first_name" TEXT,
    "last_name" TEXT,
    ...
    "start_date_years_ago" REAL,
    "start_date_year" REAL,
    "start_date_month" REAL,
    "date_of_birth_years_ago" REAL,
    "date_of_birth_year" REAL,
    "date_of_birth_month" REAL
);
```

---

## Edge Cases

| Edge Case | Handling |
|---|---|
| Unparseable date value (e.g. `"N/A"`) | All three derived columns → `None` (row not dropped) |
| Empty date value | All three derived columns → `None` |
| DD/MM vs MM/DD ambiguity | First format passing 80% threshold wins (`%d/%m/%Y` tried first) |
| Future dates (e.g. `start_date = "01/03/2027"`) | `years_ago` = negative number (correct and useful) |
| Column name conflict (derived name already exists) | Skip that derived column |
| Non-date text column (e.g. names) | Fails all 6 format parses on sample → not enriched |
| Numeric column (e.g. salary) | Skipped immediately (`detected_type == "numeric"`) |
| All sample values empty | Zero non-empty samples → column skipped |
| Partial date format (e.g. `"Q1 2024"`) | Fails all formats → not enriched |
| `full_name` already exists in CSV | NameConcatenationRule skips (no duplicate column) |
| Only `first_name` exists, no `last_name` | NameConcatenationRule skips |

---

## Files to Create

```
mcp-server/src/enrichment/
    __init__.py
    enrichment_rule.py              # ABC with detect() and apply()
    column_enricher.py              # Orchestrator: runs rules, returns enriched ParsedCSV
    default_rules.py                # Factory: create_default_enricher()
    rules/
        __init__.py
        date_enrichment_rule.py     # Date detection + years_ago/year/month
        name_concatenation_rule.py  # first_name + last_name → full_name

tests/unit/mcp_server/enrichment/
    __init__.py
    test_date_enrichment_rule.py
    test_name_concatenation_rule.py
    test_column_enricher.py
```

## Files to Modify

| File | Change |
|---|---|
| `mcp-server/src/repository/sqlite/sqlite_ingester.py` | Refactor `ingest()` to accept `ParsedCSV` instead of `csv_path`. Fix `_to_sql_value` for non-string values. Remove `CSVParser` import. |
| `mcp-server/src/server.py` | Orchestrate full pipeline: `CSVParser.parse()` → `enricher.enrich()` → `ingester.ingest()` |
| Existing tests calling `ingester.ingest(csv_path)` | Update to `ingester.ingest(CSVParser.parse(csv_path))` |

**Zero changes** to: `csv_parser.py`, `sqlite_repository.py`, `mcp_tools.py`, any shared models, any frontend code.

## Tests

### DateEnrichmentRule (14 tests)
| Test | What it verifies |
|---|---|
| `test_detect_dd_mm_yyyy` | `"28/01/1977"` detected as `%d/%m/%Y` |
| `test_detect_yyyy_mm_dd` | `"1989-07-12"` detected as `%Y-%m-%d` |
| `test_detect_skips_numeric_columns` | Column with `detected_type="numeric"` is never checked |
| `test_detect_below_threshold` | <80% parse rate → column not detected |
| `test_detect_no_dates` | Text like `"Alice"` → not enriched |
| `test_detect_returns_three_columns_per_date` | 1 date column → 3 ColumnInfo objects returned |
| `test_detect_multiple_date_columns` | Both `date_of_birth` and `start_date` enriched (6 total) |
| `test_apply_computes_years_ago` | Fixed "today", verify years_ago value |
| `test_apply_extracts_year` | `date_of_birth_year == 1977` |
| `test_apply_extracts_month` | `date_of_birth_month == 1` |
| `test_apply_handles_empty_values` | Empty string → `None` for all 3 derived columns |
| `test_apply_handles_unparseable` | `"not-a-date"` → `None` for all 3 |
| `test_apply_birthday_not_yet` | Born Dec 31, "today" is Jan 1 → one less year |
| `test_derived_column_naming` | Verify `{original_name}_years_ago/year/month` pattern |

### NameConcatenationRule (5 tests)
| Test | What it verifies |
|---|---|
| `test_detect_with_first_and_last` | Both present, no `full_name` → detected |
| `test_detect_skips_when_full_name_exists` | `full_name` already in columns → no-op |
| `test_detect_missing_one_column` | Only `first_name` → no enrichment |
| `test_apply_concatenates` | `"Alice"` + `"Smith"` → `"Alice Smith"` |
| `test_apply_handles_empty_parts` | Empty last_name → just first_name, trimmed |

### ColumnEnricher Integration (5 tests)
| Test | What it verifies |
|---|---|
| `test_enrich_adds_columns` | Full round-trip: input 5 cols → output 5 + derived cols |
| `test_enrich_no_applicable_rules` | No rules match → returned unchanged |
| `test_enrich_preserves_original_columns` | Original columns still present and unmodified |
| `test_enrich_multiple_rules_compose` | Both date and name rules apply in sequence |
| `test_enrich_does_not_mutate_original_rows` | Original row dicts unchanged after enrichment |

## Implementation Order

1. Create `enrichment/` package with `__init__.py`, ABC, and orchestrator
2. Implement `DateEnrichmentRule` + its tests
3. Implement `NameConcatenationRule` + its tests
4. Write `ColumnEnricher` integration tests
5. Refactor `sqlite_ingester.py` — accept `ParsedCSV`, fix `_to_sql_value`, remove `CSVParser` import
6. Update `server.py` — orchestrate: parse → enrich → ingest
7. Update existing tests that call `ingester.ingest(csv_path)`
8. Run full test suite
9. Docker compose rebuild + manual end-to-end test

## Architecture Review Notes

Changes incorporated from clean-architecture and software-architect agent reviews:

1. **Enrichment orchestrated in `server.py`** (not inside ingester) — both agents independently recommended this. Keeps the ingester single-responsibility and makes the pipeline visible in the composition root.
2. **`_to_sql_value` type guard** — the existing method crashes on `int`/`None` values from enriched columns. Fixed with `isinstance` checks.
3. **`samples` populated on derived `ColumnInfo`** — so `get_schema` shows the LLM example values like `[36, 48, 29]` for `date_of_birth_years_ago`.
4. **Shallow-copy rows in `apply()`** — avoids mutating the input `ParsedCSV`'s row dicts while returning a "new" `ParsedCSV`.
5. **`years_ago` is computed at ingestion time** — refreshes on each server restart (which happens every MCP session). Documented trade-off.
