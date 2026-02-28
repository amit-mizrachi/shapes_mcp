# `nominal_date_rule.py` — Date-to-numeric enrichment rule

## Overview

This module defines `NominalDateRule`, a concrete implementation of the `EnrichmentRule` abstract base class. Its purpose is to detect date columns in tabular data and enrich each row with a derived numeric column representing the number of days between the date value and a configurable epoch. This allows downstream consumers (such as ML models or analytics pipelines) to work with dates as continuous numeric features rather than raw date strings.

The rule operates in two phases:

1. **Inference** (`infer_derived_columns`) — scans columns and sample data to identify which columns contain dates and announces the new `_days` columns it intends to create.
2. **Transformation** (`add_derived_columns`) — iterates over actual data rows and computes the numeric day-offset value for each detected date column.

### Key dependencies

| Import | Purpose |
|--------|---------|
| `EnrichmentRule` | Abstract base class that defines the two-phase enrichment contract. |
| `detect_date_columns` | Helper that probes sample rows to find columns whose values match known date formats (e.g. `%Y-%m-%d`, `%d/%m/%Y`). |
| `Config` | Application configuration accessor; provides the epoch date string. |
| `ColumnInfo` | Pydantic model describing a column's name, detected type, and sample values. |

---

## Classes

### `NominalDateRule(EnrichmentRule)`

An enrichment rule that converts date-valued columns into numeric columns representing the number of days since a configured epoch date.

For every date column detected in the input data, the rule produces a new column named `<original_column>_days`. If a row's value cannot be parsed or is empty, the derived column is set to `None`.

---

#### Methods

##### `__init__(self) -> None`

Initializes the rule by reading the epoch date from application configuration and preparing internal state.

**Behavior:**

1. Reads the configuration key `mcp_server.enrichment.nominal_date_epoch` via `Config.get()`. This value must be an ISO-8601 date string (e.g. `"2000-01-01"`).
2. Parses it into a `datetime.date` object and stores it as `self._epoch`.
3. Initializes `self._date_columns` as an empty list. This list is populated later by `infer_derived_columns` and consumed by `add_derived_columns`.

**Instance attributes set:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `_epoch` | `datetime.date` | The reference date from which day offsets are calculated. |
| `_date_columns` | `list[tuple[str, str]]` | Pairs of `(column_name, date_format)` discovered during inference. Initially empty. |

**Example:**

```python
# Assuming Config returns "2000-01-01" for the epoch key:
rule = NominalDateRule()
# rule._epoch == date(2000, 1, 1)
```

---

##### `infer_derived_columns(self, columns: list[ColumnInfo], sample_rows: list[dict]) -> list[ColumnInfo]`

Examines existing columns and a sample of data rows to determine which columns contain date values. For each detected date column, it proposes a new derived column named `<column_name>_days`.

This method must be called before `add_derived_columns` so that the internal `_date_columns` state is populated.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `columns` | `list[ColumnInfo]` | Metadata about the columns currently present in the dataset. |
| `sample_rows` | `list[dict]` | A representative sample of data rows used to detect date formats. Each dict maps column names to their string values. |

**Returns:**

`list[ColumnInfo]` — A list of `ColumnInfo` objects for the new columns to be added. Each has `detected_type="numeric"` and an empty `samples` list. Returns an empty list if no date columns are detected or if all derived column names already exist.

**Side effects:**

- Sets `self._date_columns` to the list of `(column_name, date_format)` tuples returned by `detect_date_columns`.
- Logs an info-level message for each new derived column it will create.

**Duplicate prevention:** If a column named `<column_name>_days` already exists in the input `columns`, it is silently skipped.

**Example:**

```python
from shared.modules.data.column_info import ColumnInfo

rule = NominalDateRule()

columns = [
    ColumnInfo(name="id", detected_type="numeric", samples=["1", "2"]),
    ColumnInfo(name="birth_date", detected_type="text", samples=["1990-05-15", "1985-12-01"]),
]

sample_rows = [
    {"id": "1", "birth_date": "1990-05-15"},
    {"id": "2", "birth_date": "1985-12-01"},
]

new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns == [ColumnInfo(name="birth_date_days", detected_type="numeric", samples=[])]
```

---

##### `add_derived_columns(self, rows: list[dict]) -> list[dict]`

Iterates over data rows and adds the derived `_days` columns computed during inference. For each detected date column, it parses the raw string value, calculates the number of days between that date and the epoch, and writes the result into a new key on the row dict.

**Important:** `infer_derived_columns` must be called first to populate `self._date_columns`. If it has not been called (or returned no date columns), this method is effectively a no-op that returns the rows unchanged.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `rows` | `list[dict]` | The data rows to enrich. Each dict maps column names to values. |

**Returns:**

`list[dict]` — The same list of dicts, mutated in place with new `<column_name>_days` keys added.

**Value computation logic:**

| Condition | Derived value |
|-----------|---------------|
| Raw value is empty or missing | `None` |
| Raw value parses successfully with the detected format | `(parsed_date - epoch).days` (an integer) |
| Raw value fails to parse (raises `ValueError`) | `None` |

**Example:**

```python
rule = NominalDateRule()

# Phase 1: inference (required before calling add_derived_columns)
columns = [ColumnInfo(name="hire_date", detected_type="text", samples=["2020-06-01"])]
sample_rows = [{"hire_date": "2020-06-01"}]
rule.infer_derived_columns(columns, sample_rows)

# Phase 2: transformation
rows = [
    {"hire_date": "2020-06-01"},
    {"hire_date": "2023-01-15"},
    {"hire_date": ""},           # empty value
    {"hire_date": "not-a-date"}, # unparseable value
]

enriched = rule.add_derived_columns(rows)

# Assuming epoch is 2000-01-01:
# enriched[0]["hire_date_days"] == 7457   # days from 2000-01-01 to 2020-06-01
# enriched[1]["hire_date_days"] == 8415   # days from 2000-01-01 to 2023-01-15
# enriched[2]["hire_date_days"] is None   # empty input
# enriched[3]["hire_date_days"] is None   # parse failure
```

---

## Configuration

The rule depends on a single configuration key:

| Key | Type | Description | Example |
|-----|------|-------------|---------|
| `mcp_server.enrichment.nominal_date_epoch` | ISO-8601 date string | The reference date used as day-zero for all `_days` calculations. | `"2000-01-01"` |

---

## End-to-end example

```python
from enrichment.rules.nominal_date_rule import NominalDateRule
from shared.modules.data.column_info import ColumnInfo

# 1. Create the rule (reads epoch from config)
rule = NominalDateRule()

# 2. Define existing columns and sample data
columns = [
    ColumnInfo(name="user_id", detected_type="numeric", samples=["101"]),
    ColumnInfo(name="signup_date", detected_type="text", samples=["15/03/2022"]),
    ColumnInfo(name="last_login", detected_type="text", samples=["2024-11-30"]),
]

sample_rows = [
    {"user_id": "101", "signup_date": "15/03/2022", "last_login": "2024-11-30"},
    {"user_id": "102", "signup_date": "22/07/2021", "last_login": "2024-12-01"},
]

# 3. Inference phase: discover date columns, propose derived columns
new_columns = rule.infer_derived_columns(columns, sample_rows)
# new_columns contains ColumnInfo for "signup_date_days" and "last_login_days"

# 4. Transformation phase: enrich actual data rows
rows = [
    {"user_id": "101", "signup_date": "15/03/2022", "last_login": "2024-11-30"},
    {"user_id": "102", "signup_date": "22/07/2021", "last_login": "2024-12-01"},
]

enriched_rows = rule.add_derived_columns(rows)
# Each row now has "signup_date_days" and "last_login_days" keys with integer values
```
