# `enrichment/rules/__init__.py` — Rules sub-package marker

## Overview

This file is an **empty package initializer** (`__init__.py`) for the `enrichment.rules` sub-package. It contains no imports, exports, or executable code. Its sole purpose is to mark the `rules/` directory as a Python package so that its modules can be imported using dotted paths such as `enrichment.rules.nominal_date_rule`.

The parent package `enrichment/__init__.py` is also empty, so neither level re-exports any symbols. All consumers import directly from the individual modules inside `enrichment/rules/`.

## Exports / Imports

**None.** The file is completely empty.

Consumers are expected to import from the concrete modules directly. There is no facade or convenience re-export layer.

## Package structure

```
enrichment/
    __init__.py                  # empty package marker (parent)
    enrichment_rule.py           # EnrichmentRule ABC (base class)
    rules/
        __init__.py              # <-- THIS FILE (empty package marker)
        date_detection.py        # detect_date_columns() utility function
        month_extraction_rule.py # MonthExtractionRule(EnrichmentRule)
        year_extraction_rule.py  # YearExtractionRule(EnrichmentRule)
        nominal_date_rule.py     # NominalDateRule(EnrichmentRule)
```

## Modules in the package

### `date_detection.py`

Shared utility module (not an `EnrichmentRule` subclass). Provides:

| Symbol | Type | Description |
|--------|------|-------------|
| `detect_date_columns(columns, sample_rows)` | function | Scans columns against sample data and returns `(column_name, date_format)` pairs for columns whose values parse as dates in at least 80% of samples. |

Supported date formats: `%d/%m/%Y`, `%m/%d/%Y`, `%Y-%m-%d`, `%d-%m-%Y`, `%m-%d-%Y`, `%Y/%m/%d`.

### `month_extraction_rule.py`

| Symbol | Type | Description |
|--------|------|-------------|
| `MonthExtractionRule` | class | Adds a `{column}_month` numeric column for every detected date column, containing the 1--12 month number. |

### `year_extraction_rule.py`

| Symbol | Type | Description |
|--------|------|-------------|
| `YearExtractionRule` | class | Adds a `{column}_year` numeric column for every detected date column, containing the four-digit year. |

### `nominal_date_rule.py`

| Symbol | Type | Description |
|--------|------|-------------|
| `NominalDateRule` | class | Adds a `{column}_days` numeric column containing the number of days between the parsed date and a configurable epoch (read from `mcp_server.enrichment.nominal_date_epoch` in the application config). |

## Base class

All three rule classes (`MonthExtractionRule`, `YearExtractionRule`, `NominalDateRule`) extend `enrichment.enrichment_rule.EnrichmentRule`, an abstract base class that defines two methods:

- `infer_derived_columns(columns, sample_rows) -> list[ColumnInfo]` -- examine existing columns, return new `ColumnInfo` objects for columns the rule will add.
- `add_derived_columns(rows) -> list[dict]` -- mutate rows in-place to add the derived column values. Must only be called after `infer_derived_columns` returned a non-empty list.

## Known consumers

The rules are instantiated and wired together in `server.py`:

```python
from enrichment.rules.nominal_date_rule import NominalDateRule
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from enrichment.rules.year_extraction_rule import YearExtractionRule
```

## Design notes

- The empty `__init__.py` follows a **flat import** convention: each module is imported explicitly by path rather than re-exported from the package. This avoids circular imports and makes dependency graphs easy to trace, at the cost of slightly longer import statements.
- All three rule modules share the same internal dependency on `date_detection.detect_date_columns` for discovering which columns contain dates.
- The `__pycache__` directory shows compiled bytecode for a `full_name_enrichment_rule` and a `date_enrichment_rule`, indicating that additional rules existed historically but have since been removed from the source tree.
