# `column_enricher.py` -- Column enrichment orchestrator

## Overview

`column_enricher.py` defines the `ColumnEnricher` class, which is responsible for deriving new columns from existing CSV data by applying a pipeline of enrichment rules. It inspects a `ParsedCSV` object, determines which `EnrichmentRule` instances are applicable, computes the new column values, and returns a new `ParsedCSV` that includes the original columns and rows alongside the derived ones.

The module sits in the `enrichment` package and depends on:

| Dependency | Role |
|---|---|
| `shared.config.Config` | Reads runtime configuration values (`detection_sample_size`, `max_samples`) |
| `shared.modules.data.column_info.ColumnInfo` | Immutable Pydantic model representing a single column's metadata |
| `shared.modules.data.parsed_csv.ParsedCSV` | Immutable Pydantic model representing the full parsed CSV (table name, columns, rows) |
| `enrichment.enrichment_rule.EnrichmentRule` | Abstract base class that each concrete enrichment rule implements |

---

## Classes

### `ColumnEnricher`

Orchestrates column enrichment across a collection of `EnrichmentRule` objects. It follows a two-phase process:

1. **Detection** -- each rule inspects a sample of rows and reports which new columns it can produce.
2. **Computation** -- applicable rules mutate shallow copies of the rows to add the derived column values.

#### Constructor

##### `__init__(self, rules: list[EnrichmentRule]) -> None`

Stores the ordered list of enrichment rules that will be evaluated during `enrich()`.

| Parameter | Type | Description |
|---|---|---|
| `rules` | `list[EnrichmentRule]` | Ordered sequence of enrichment rules to evaluate. Rules are checked and applied in the order provided. |

**Example:**

```python
from enrichment.column_enricher import ColumnEnricher
from enrichment.some_rule import SomeConcreteRule

enricher = ColumnEnricher(rules=[SomeConcreteRule()])
```

---

#### Methods

##### `enrich(self, parsed_csv: ParsedCSV) -> ParsedCSV`

Runs the full enrichment pipeline on a parsed CSV dataset and returns a new `ParsedCSV` that includes any derived columns and their computed values.

**Algorithm:**

1. Reads `mcp_server.enrichment.detection_sample_size` from configuration and slices the first N rows as the detection sample.
2. Iterates over every registered rule, calling `rule.infer_derived_columns()` with the existing columns and the sample rows.
3. Collects the `ColumnInfo` objects returned by rules that detect applicable enrichments, and logs which rules will fire and what columns they will add.
4. If no rules are applicable, returns the original `parsed_csv` unchanged.
5. Creates shallow copies of every row (`{**row}`) to avoid mutating the original data.
6. Iterates over applicable rules in order, calling `rule.add_derived_columns()` to populate the new column values in the copied rows.
7. Calls `_populate_samples()` to fill in sample values on the new `ColumnInfo` objects.
8. Constructs and returns a new `ParsedCSV` combining the original columns with the new ones, and the enriched rows.

| Parameter | Type | Description |
|---|---|---|
| `parsed_csv` | `ParsedCSV` | The input dataset containing table name, column metadata, and row data. |

**Returns:** `ParsedCSV` -- a new instance with the original columns plus any derived columns appended, and rows augmented with the derived values. If no rules apply, the original `parsed_csv` is returned as-is (same object).

**Example:**

```python
from enrichment.column_enricher import ColumnEnricher
from enrichment.some_rule import DatePartsRule

enricher = ColumnEnricher(rules=[DatePartsRule()])
enriched = enricher.enrich(parsed_csv)

# enriched.columns now includes any new columns detected by DatePartsRule
# enriched.rows now contain values for those new columns
```

---

##### `_populate_samples(columns: list[ColumnInfo], rows: list[dict]) -> list[ColumnInfo]` *(static method)*

Creates new `ColumnInfo` instances with their `samples` field populated from the first rows of the enriched dataset. Because `ColumnInfo` is a frozen Pydantic model, this method constructs new objects rather than mutating the originals.

**Algorithm:**

1. Reads `mcp_server.enrichment.max_samples` from configuration to determine how many sample values to collect.
2. For each column, extracts up to `max_samples` non-`None` values from the corresponding rows, converting each to a string.
3. Returns a list of new `ColumnInfo` objects with the `samples` field filled in.

| Parameter | Type | Description |
|---|---|---|
| `columns` | `list[ColumnInfo]` | The newly inferred column metadata objects (without samples yet). |
| `rows` | `list[dict]` | The enriched row data from which sample values are drawn. |

**Returns:** `list[ColumnInfo]` -- new `ColumnInfo` instances identical to the input but with the `samples` field populated.

**Example:**

```python
from shared.modules.data.column_info import ColumnInfo

columns = [ColumnInfo(name="year", detected_type="integer")]
rows = [
    {"year": 2024},
    {"year": 2025},
    {"year": None},
    {"year": 2026},
]

populated = ColumnEnricher._populate_samples(columns, rows)
# populated[0].samples == ["2024", "2025", "2026"]
# (None values are skipped; count is capped at the configured max_samples)
```

---

## Configuration dependencies

The class reads two configuration keys at runtime via `Config.get()`:

| Key | Used in | Purpose |
|---|---|---|
| `mcp_server.enrichment.detection_sample_size` | `enrich()` | Number of rows to pass to each rule's `infer_derived_columns()` for detection. |
| `mcp_server.enrichment.max_samples` | `_populate_samples()` | Maximum number of sample values to attach to each new `ColumnInfo`. |

## Data flow

```
ParsedCSV (input)
    |
    v
[1] Slice sample rows (detection_sample_size)
    |
    v
[2] For each rule: infer_derived_columns(columns, sample_rows)
    |                 \-> list[ColumnInfo]  (new columns to add)
    v
[3] Shallow-copy all rows
    |
    v
[4] For each applicable rule: add_derived_columns(rows)
    |                           \-> rows with new key-value pairs
    v
[5] _populate_samples(new_columns, enriched_rows)
    |                   \-> ColumnInfo objects with samples filled
    v
ParsedCSV (output: original columns + new columns, enriched rows)
```
