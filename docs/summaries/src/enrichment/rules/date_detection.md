# `date_detection.py` — Date column detection for tabular data

## Overview

This module inspects tabular data to identify columns that contain date values. It works by sampling row values and attempting to parse them against a prioritized list of common date formats. When a sufficient proportion of values in a column match a given format (80% by default), the column is flagged as a date column and the matching format string is returned. Columns already classified as `"numeric"` are skipped entirely.

The module is part of the enrichment rules pipeline and depends on `ColumnInfo` from the shared data layer.

## Constants

### `_DATE_FORMATS`

```python
_DATE_FORMATS = [
    "%d/%m/%Y",  # 28/01/1977
    "%m/%d/%Y",  # 07/12/1989
    "%Y-%m-%d",  # 1989-07-12
    "%d-%m-%Y",  # 28-01-1977
    "%m-%d-%Y",  # 07-12-1989
    "%Y/%m/%d",  # 1989/07/12
]
```

A list of `datetime.strptime`-compatible format strings that the detector tries, in order. The ordering matters: the first format that reaches the detection threshold wins. This means `"%d/%m/%Y"` (day-first with slashes) takes priority over `"%m/%d/%Y"` (month-first with slashes) when both could technically match the same data.

---

### `_DETECTION_THRESHOLD`

```python
_DETECTION_THRESHOLD = 0.8
```

The minimum fraction of non-empty sample values that must successfully parse for a format to be considered a match. A value of `0.8` means at least 80% of the sampled values must parse. This allows for a small number of missing, malformed, or header-like values without rejecting the entire column.

---

## Functions

### `detect_date_columns(columns, sample_rows) -> list[tuple[str, str]]`

The public entry point. Iterates over a list of column metadata objects, skips any column whose `detected_type` is `"numeric"`, and delegates each remaining column to `_detect_date_format`. Returns a list of `(column_name, date_format)` pairs for every column that appears to contain dates.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `columns` | `list[ColumnInfo]` | Column metadata objects. Each must expose `.name` (str) and `.detected_type` (str). |
| `sample_rows` | `list[dict]` | A sample of rows from the dataset. Each row is a dictionary keyed by column name. |

**Returns:** `list[tuple[str, str]]` -- A list of tuples where each tuple contains the column name and the `strptime`-compatible format string that matched.

**Example:**

```python
from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.date_detection import detect_date_columns

columns = [
    ColumnInfo(name="id", detected_type="numeric"),
    ColumnInfo(name="birth_date", detected_type="string"),
    ColumnInfo(name="city", detected_type="string"),
]

sample_rows = [
    {"id": 1, "birth_date": "28/01/1977", "city": "London"},
    {"id": 2, "birth_date": "15/06/1990", "city": "Paris"},
    {"id": 3, "birth_date": "03/11/2001", "city": "Berlin"},
]

result = detect_date_columns(columns, sample_rows)
# result == [("birth_date", "%d/%m/%Y")]
```

**Behavior notes:**

- Columns with `detected_type == "numeric"` are unconditionally skipped, even if their values happen to look like dates (e.g., `20230115`).
- The function returns an empty list if no columns match any date format.

---

### `_detect_date_format(column_name, sample_rows) -> str | None`

Internal helper. Extracts the values for a single column from the sample rows, strips whitespace, discards empty strings, and then tests each format in `_DATE_FORMATS` order. Returns the first format where at least `_DETECTION_THRESHOLD` (80%) of the non-empty values parse successfully, or `None` if no format qualifies.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `column_name` | `str` | The name of the column to inspect. Used as the dictionary key into each row. |
| `sample_rows` | `list[dict]` | The same sample rows passed to `detect_date_columns`. |

**Returns:** `str | None` -- The matching `strptime` format string, or `None` if no format met the threshold.

**Example:**

```python
from enrichment.rules.date_detection import _detect_date_format

rows = [
    {"start": "2024-01-15"},
    {"start": "2024-06-30"},
    {"start": "2024-12-25"},
    {"start": ""},           # empty -- excluded from count
    {"start": "not-a-date"}, # will fail to parse
]

fmt = _detect_date_format("start", rows)
# 3 out of 4 non-empty values parse as "%Y-%m-%d" (75%), which is below 80%.
# fmt == None

# With one more valid row the threshold would be met.
```

**Behavior notes:**

- Rows where the column key is missing are treated as empty strings and excluded.
- The function short-circuits: it returns the first format that meets the threshold, so later formats in `_DATE_FORMATS` are never tested if an earlier one already qualifies.

---

### `_try_parse(value, date_format) -> bool`

Internal helper. Attempts to parse a single string value using `datetime.strptime` with the given format. Returns `True` on success and `False` if a `ValueError` is raised.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `str` | The string to attempt to parse as a date. |
| `date_format` | `str` | A `datetime.strptime`-compatible format string (e.g., `"%Y-%m-%d"`). |

**Returns:** `bool` -- `True` if the value successfully parses; `False` otherwise.

**Example:**

```python
from enrichment.rules.date_detection import _try_parse

_try_parse("2024-01-15", "%Y-%m-%d")   # True
_try_parse("15/01/2024", "%Y-%m-%d")   # False
_try_parse("not-a-date", "%d/%m/%Y")   # False
_try_parse("28/01/1977", "%d/%m/%Y")   # True
```

---

## Dependencies

| Import | Source | Purpose |
|--------|--------|---------|
| `annotations` | `__future__` | Enables PEP 604 union syntax (`str \| None`) at runtime on older Python versions. |
| `datetime` | `datetime` (stdlib) | Provides `datetime.strptime` for date parsing. |
| `ColumnInfo` | `shared.modules.data.column_info` | Data class representing column metadata; exposes `.name` and `.detected_type`. |

## Call graph

```
detect_date_columns
  |
  +---> (skips numeric columns)
  |
  +---> _detect_date_format   (for each non-numeric column)
            |
            +---> _try_parse   (for each value x format combination)
```
