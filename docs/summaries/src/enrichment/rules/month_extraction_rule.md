# `month_extraction_rule.py` -- Month extraction enrichment rule

## Overview

This module defines `MonthExtractionRule`, a concrete enrichment rule that automatically detects date columns in tabular data and derives new numeric columns containing the month component (1--12) of each date value. It is part of the enrichment pipeline and extends the abstract `EnrichmentRule` base class.

**File path:** `mcp-server/src/enrichment/rules/month_extraction_rule.py`

**Dependencies:**

| Import | Purpose |
|--------|---------|
| `EnrichmentRule` | Abstract base class that defines the two-phase enrichment contract |
| `detect_date_columns` | Utility that inspects sample data to find columns containing date values |
| `ColumnInfo` | Pydantic model describing a column's name, detected type, and sample values |

---

## Classes

### `MonthExtractionRule(EnrichmentRule)`

An enrichment rule that adds a `<column>_month` derived column for every date column it detects. The rule operates in two phases:

1. **Inference phase** (`infer_derived_columns`) -- examines column metadata and sample rows to identify date columns and declares which new columns will be created.
2. **Derivation phase** (`add_derived_columns`) -- parses the date values in every row and populates the derived month columns.

The class stores the detected date columns as internal state between the two phases, so `infer_derived_columns` must always be called before `add_derived_columns`.

---

#### Methods

##### `__init__(self) -> None`

Initializes the rule with an empty list of detected date columns.

**Internal state:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `_date_columns` | `list[tuple[str, str]]` | Pairs of `(column_name, date_format_string)` populated during inference |

**Example:**

```python
from enrichment.rules.month_extraction_rule import MonthExtractionRule

rule = MonthExtractionRule()
```

---

##### `infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]`

Examines the provided column metadata and a sample of data rows to detect which columns contain date values. For each detected date column, it proposes a new derived column named `<original_column>_month` -- unless a column with that name already exists.

This method also populates the internal `_date_columns` state used later by `add_derived_columns`.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `columns` | `list[ColumnInfo]` | Metadata for all existing columns in the dataset |
| `sample_rows` | `list[dict]` | A representative sample of data rows used for date format detection |

**Returns:** `list[ColumnInfo]` -- A list of new `ColumnInfo` objects for the derived month columns. Each has `detected_type="numeric"` and an empty `samples` list. Returns an empty list if no date columns are found or if all derived names already exist.

**Behavior details:**

- Delegates date detection to `detect_date_columns`, which tries multiple date formats (e.g., `%d/%m/%Y`, `%Y-%m-%d`) and requires at least 80% of sample values to parse successfully.
- Skips columns already marked as `"numeric"` in the detection step.
- Logs an info message for each new derived column it will add.

**Example:**

```python
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from shared.modules.data.column_info import ColumnInfo

rule = MonthExtractionRule()

columns = [
    ColumnInfo(name="id", detected_type="numeric", samples=["1", "2"]),
    ColumnInfo(name="birth_date", detected_type="text", samples=["28/01/1977", "12/05/1990"]),
]

sample_rows = [
    {"id": 1, "birth_date": "28/01/1977"},
    {"id": 2, "birth_date": "12/05/1990"},
]

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == [ColumnInfo(name="birth_date_month", detected_type="numeric", samples=[])]
```

**Edge case -- derived column already exists:**

```python
columns = [
    ColumnInfo(name="birth_date", detected_type="text", samples=["28/01/1977"]),
    ColumnInfo(name="birth_date_month", detected_type="numeric", samples=["1"]),
]

sample_rows = [{"birth_date": "28/01/1977", "birth_date_month": 1}]

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == []  (no new column added because "birth_date_month" already exists)
```

---

##### `add_derived_columns(self, rows: list[dict]) -> list[dict]`

Parses date values in each row and adds the corresponding `<column>_month` key with the integer month (1--12). Rows are mutated in place and also returned.

**Must be called after** `infer_derived_columns` -- the method relies on the `_date_columns` state populated during inference.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `rows` | `list[dict]` | The full set of data rows to enrich |

**Returns:** `list[dict]` -- The same list of rows, each augmented with `<column>_month` keys. Rows are mutated in place; the return value is a convenience reference to the same list.

**Behavior details:**

- For each row and each detected date column, the method:
  1. Reads the raw value from `row[column_name]`, converts it to a string, and strips whitespace.
  2. If the value is empty, sets `row[key]` to `None`.
  3. Attempts to parse the value using the date format string detected during inference.
  4. On success, sets `row[key]` to the integer month (`1`--`12`).
  5. On `ValueError` (unparseable value), sets `row[key]` to `None`.

**Example:**

```python
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from shared.modules.data.column_info import ColumnInfo

rule = MonthExtractionRule()

columns = [
    ColumnInfo(name="order_date", detected_type="text", samples=["2024-03-15"]),
]
sample_rows = [{"order_date": "2024-03-15"}]

# Phase 1: inference
rule.infer_derived_columns(columns, sample_rows)

# Phase 2: derivation
rows = [
    {"order_date": "2024-03-15"},
    {"order_date": "2024-11-01"},
    {"order_date": ""},
    {"order_date": "not-a-date"},
]

enriched = rule.add_derived_columns(rows)
# enriched == [
#     {"order_date": "2024-03-15", "order_date_month": 3},
#     {"order_date": "2024-11-01", "order_date_month": 11},
#     {"order_date": "",           "order_date_month": None},
#     {"order_date": "not-a-date", "order_date_month": None},
# ]
```

---

## Full end-to-end example

```python
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from shared.modules.data.column_info import ColumnInfo

# Set up columns and sample data
columns = [
    ColumnInfo(name="id", detected_type="numeric", samples=["1", "2", "3"]),
    ColumnInfo(name="hire_date", detected_type="text", samples=["15/06/2020", "01/12/2019"]),
    ColumnInfo(name="name", detected_type="text", samples=["Alice", "Bob"]),
]

sample_rows = [
    {"id": 1, "hire_date": "15/06/2020", "name": "Alice"},
    {"id": 2, "hire_date": "01/12/2019", "name": "Bob"},
    {"id": 3, "hire_date": "22/03/2021", "name": "Charlie"},
]

# Create the rule and run both phases
rule = MonthExtractionRule()

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == [ColumnInfo(name="hire_date_month", detected_type="numeric", samples=[])]

all_rows = [
    {"id": 1, "hire_date": "15/06/2020", "name": "Alice"},
    {"id": 2, "hire_date": "01/12/2019", "name": "Bob"},
    {"id": 3, "hire_date": "22/03/2021", "name": "Charlie"},
]

enriched_rows = rule.add_derived_columns(all_rows)
# Each row now contains "hire_date_month": 6, 12, and 3 respectively
# "name" column is not touched because it does not match any date format
```

---

## Supported date formats

The date detection (delegated to `detect_date_columns` in `date_detection.py`) recognizes the following formats:

| Format | Example |
|--------|---------|
| `%d/%m/%Y` | `28/01/1977` |
| `%m/%d/%Y` | `07/12/1989` |
| `%Y-%m-%d` | `1989-07-12` |
| `%d-%m-%Y` | `28-01-1977` |
| `%m-%d-%Y` | `07-12-1989` |
| `%Y/%m/%d` | `1989/07/12` |

A column is classified as a date column when at least 80% of non-empty sample values successfully parse with one of these formats. The first matching format in the list above is used.
