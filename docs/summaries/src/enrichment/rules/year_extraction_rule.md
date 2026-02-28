# `year_extraction_rule.py` — Date-to-year enrichment rule

## Overview

This module defines `YearExtractionRule`, a concrete enrichment rule that automatically detects date columns in a dataset and creates corresponding `_year` columns containing the extracted year as a numeric value. It extends the abstract `EnrichmentRule` base class and relies on the `detect_date_columns` utility from `date_detection` to identify which columns contain parseable date strings.

**Source:** `mcp-server/src/enrichment/rules/year_extraction_rule.py`

**Dependencies:**

| Import | Purpose |
|--------|---------|
| `EnrichmentRule` | Abstract base class defining the enrichment rule interface |
| `detect_date_columns` | Utility that scans columns and sample rows to find date-formatted columns |
| `ColumnInfo` | Pydantic model representing column metadata (name, type, samples) |

---

## Classes

### `YearExtractionRule(EnrichmentRule)`

An enrichment rule that derives a `<column>_year` column for every detected date column in a dataset. The rule operates in two phases: first it infers which new columns to create (`infer_derived_columns`), then it populates those columns across all rows (`add_derived_columns`). These two methods must be called in that order because the second phase depends on state set during the first.

#### Methods

##### `__init__(self) -> None`

Initializes the rule with an empty list of detected date columns.

**Internal state:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `_date_columns` | `list[tuple[str, str]]` | Pairs of `(column_name, date_format)` populated during inference. Empty until `infer_derived_columns` is called. |

**Example:**

```python
from enrichment.rules.year_extraction_rule import YearExtractionRule

rule = YearExtractionRule()
```

---

##### `infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]`

Examines the provided columns and sample data to determine which columns contain date values, then proposes new `_year` columns for each detected date column. Stores the detected date columns internally for use by `add_derived_columns`.

A new column is only proposed if a column named `<original>_year` does not already exist in the dataset. This prevents duplicate columns when the rule is applied to data that has already been enriched.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `columns` | `list[ColumnInfo]` | Metadata for all existing columns in the dataset |
| `sample_rows` | `list[dict]` | A representative sample of data rows used for date-format detection |

**Returns:** `list[ColumnInfo]` -- A list of new column descriptors to add. Each has `detected_type="numeric"` and an empty `samples` list. Returns an empty list if no date columns are found or if all derived names already exist.

**Side effects:** Populates `self._date_columns` with the detected `(column_name, date_format)` pairs. This state is required by `add_derived_columns`.

**Example:**

```python
from enrichment.rules.year_extraction_rule import YearExtractionRule
from shared.modules.data.column_info import ColumnInfo

rule = YearExtractionRule()

columns = [
    ColumnInfo(name="birth_date", detected_type="text", samples=["28/01/1977"]),
    ColumnInfo(name="score", detected_type="numeric", samples=["95"]),
]

sample_rows = [
    {"birth_date": "28/01/1977", "score": "95"},
    {"birth_date": "15/06/1990", "score": "87"},
]

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == [ColumnInfo(name="birth_date_year", detected_type="numeric", samples=[])]
```

**Behavior when derived column already exists:**

```python
columns = [
    ColumnInfo(name="birth_date", detected_type="text", samples=["28/01/1977"]),
    ColumnInfo(name="birth_date_year", detected_type="numeric", samples=["1977"]),
]

sample_rows = [{"birth_date": "28/01/1977", "birth_date_year": "1977"}]

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == []  (no duplicates created)
```

---

##### `add_derived_columns(self, rows: list[dict]) -> list[dict]`

Iterates over every row and adds a `<column>_year` key for each date column that was detected during `infer_derived_columns`. The year is extracted by parsing the raw string value with the format string identified during inference.

**Important:** This method must only be called after `infer_derived_columns` has been invoked. It relies on `self._date_columns` being populated. If called before inference, it will silently do nothing (the internal list is empty).

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `rows` | `list[dict]` | The full set of data rows to enrich |

**Returns:** `list[dict]` -- The same list of rows, mutated in place with new `_year` keys added.

**Mutation note:** Rows are modified in place. The caller should copy the rows first if the originals must be preserved.

**Value assignment logic:**

| Condition | Value assigned to `<column>_year` |
|-----------|-----------------------------------|
| Raw value is empty or missing | `None` |
| Raw value parses successfully with the detected format | The integer year (e.g., `1977`) |
| Raw value fails to parse (malformed data) | `None` |

**Example:**

```python
from enrichment.rules.year_extraction_rule import YearExtractionRule
from shared.modules.data.column_info import ColumnInfo

rule = YearExtractionRule()

columns = [
    ColumnInfo(name="hire_date", detected_type="text", samples=["2020-03-15"]),
]

sample_rows = [
    {"hire_date": "2020-03-15"},
    {"hire_date": "2023-11-01"},
]

# Phase 1: infer new columns
new_columns = rule.infer_derived_columns(columns, sample_rows)

# Phase 2: enrich all rows
rows = [
    {"hire_date": "2020-03-15", "name": "Alice"},
    {"hire_date": "2023-11-01", "name": "Bob"},
    {"hire_date": "",            "name": "Carol"},   # empty date
    {"hire_date": "not-a-date",  "name": "Dave"},    # unparseable
]

enriched = rule.add_derived_columns(rows)
# enriched == [
#     {"hire_date": "2020-03-15", "name": "Alice", "hire_date_year": 2020},
#     {"hire_date": "2023-11-01", "name": "Bob",   "hire_date_year": 2023},
#     {"hire_date": "",            "name": "Carol", "hire_date_year": None},
#     {"hire_date": "not-a-date",  "name": "Dave",  "hire_date_year": None},
# ]
```

---

## Full lifecycle example

```python
from enrichment.rules.year_extraction_rule import YearExtractionRule
from shared.modules.data.column_info import ColumnInfo

# 1. Create the rule
rule = YearExtractionRule()

# 2. Define existing schema and sample data
columns = [
    ColumnInfo(name="event_date", detected_type="text", samples=["12/05/2019"]),
    ColumnInfo(name="event_name", detected_type="text", samples=["Conference"]),
]

sample_rows = [
    {"event_date": "12/05/2019", "event_name": "Conference"},
    {"event_date": "23/08/2021", "event_name": "Workshop"},
]

# 3. Infer derived columns (must happen first)
new_cols = rule.infer_derived_columns(columns, sample_rows)
# new_cols contains ColumnInfo(name="event_date_year", detected_type="numeric", samples=[])

# 4. Enrich all rows (uses state from step 3)
all_rows = [
    {"event_date": "12/05/2019", "event_name": "Conference"},
    {"event_date": "23/08/2021", "event_name": "Workshop"},
    {"event_date": "01/01/2025", "event_name": "Summit"},
]

enriched_rows = rule.add_derived_columns(all_rows)
# Each row now has an "event_date_year" key with the integer year
```

## Supported date formats

The date formats are determined by the `detect_date_columns` utility in `date_detection.py`. The following formats are recognized (at least 80% of sample values must parse successfully):

| Format | Example |
|--------|---------|
| `%d/%m/%Y` | `28/01/1977` |
| `%m/%d/%Y` | `07/12/1989` |
| `%Y-%m-%d` | `1989-07-12` |
| `%d-%m-%Y` | `28-01-1977` |
| `%m-%d-%Y` | `07-12-1989` |
| `%Y/%m/%d` | `1989/07/12` |
