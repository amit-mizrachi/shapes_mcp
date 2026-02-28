# `enrichment_rule.py` --- Abstract base for data enrichment rules

## Overview

This file defines `EnrichmentRule`, an abstract base class (ABC) that establishes the
contract for all data enrichment rules in the MCP server's enrichment pipeline. An
enrichment rule inspects existing dataset columns, decides whether new derived columns
should be added, and then computes values for those columns across all rows.

The two-phase design --- first **infer** which columns to add, then **populate** them ---
allows the pipeline to collect schema information (column names and types) before any row
mutation occurs.

**Source:** `mcp-server/src/enrichment/enrichment_rule.py`

**Known implementations:** `NominalDateRule`, `YearExtractionRule`, `MonthExtractionRule`

---

## Classes

### `EnrichmentRule`

```python
class EnrichmentRule(ABC)
```

Abstract base class that every enrichment rule must subclass. It enforces a two-method
protocol:

1. **Inference phase** -- examine existing columns and sample data to decide which new
   columns this rule will produce.
2. **Population phase** -- iterate over the full row set and add the derived column
   values.

Subclasses must implement both abstract methods. The caller is expected to invoke
`infer_derived_columns` first and only call `add_derived_columns` when the inference
step returns a non-empty list.

---

#### Methods

##### `infer_derived_columns(columns, sample_rows) -> list[ColumnInfo]`

```python
@abstractmethod
def infer_derived_columns(
    self,
    columns: list[ColumnInfo],
    sample_rows: list[dict],
) -> list[ColumnInfo]
```

Examine the existing column metadata and a sample of rows to determine whether this rule
should add any new derived columns.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `columns` | `list[ColumnInfo]` | Metadata for every column currently in the dataset. Each `ColumnInfo` has `name: str`, `detected_type: str`, and `samples: list[str]`. |
| `sample_rows` | `list[dict]` | A representative subset of dataset rows (each row is a `str`-keyed dict). Used for heuristic detection (e.g., date format sniffing). |

**Returns:** `list[ColumnInfo]` -- Zero or more `ColumnInfo` objects describing the new
columns this rule wants to add. An empty list means no enrichment applies.

**Contract:**
- Must be called before `add_derived_columns`.
- Implementations typically store internal state (e.g., detected date columns and their
  formats) so that `add_derived_columns` knows what to compute.

**Example:**

```python
from shared.modules.data.column_info import ColumnInfo
from enrichment.rules.year_extraction_rule import YearExtractionRule

columns = [
    ColumnInfo(name="order_date", detected_type="date", samples=["2024-01-15"]),
    ColumnInfo(name="amount", detected_type="numeric", samples=["99.50"]),
]
sample_rows = [
    {"order_date": "2024-01-15", "amount": "99.50"},
    {"order_date": "2024-03-22", "amount": "150.00"},
]

rule = YearExtractionRule()
new_columns = rule.infer_derived_columns(columns, sample_rows)

# new_columns == [ColumnInfo(name="order_date_year", detected_type="numeric", samples=[])]
```

---

##### `add_derived_columns(rows) -> list[dict]`

```python
@abstractmethod
def add_derived_columns(
    self,
    rows: list[dict],
) -> list[dict]
```

Add derived column values to every row in the dataset. This method must only be called
after `infer_derived_columns` has been invoked and returned a non-empty list.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `rows` | `list[dict]` | The full set of dataset rows. Each row is a `str`-keyed dict mapping column names to values. |

**Returns:** `list[dict]` -- The same list of rows, now augmented with keys for the
derived columns. Rows are typically mutated in place; the caller must copy beforehand if
the originals need to be preserved.

**Contract:**
- Must only be called after `infer_derived_columns` returned a non-empty list.
- Implementations should handle missing or unparseable values gracefully (e.g., set the
  derived value to `None`).

**Example:**

```python
from enrichment.rules.year_extraction_rule import YearExtractionRule
from shared.modules.data.column_info import ColumnInfo

rule = YearExtractionRule()

# Phase 1 -- infer
columns = [ColumnInfo(name="created_at", detected_type="date", samples=["2025-06-01"])]
sample_rows = [{"created_at": "2025-06-01"}]
new_cols = rule.infer_derived_columns(columns, sample_rows)

# Phase 2 -- populate (only if new_cols is non-empty)
if new_cols:
    rows = [
        {"created_at": "2025-06-01", "status": "active"},
        {"created_at": "2024-11-20", "status": "closed"},
        {"created_at": "",           "status": "pending"},
    ]
    enriched = rule.add_derived_columns(rows)

    # enriched[0]["created_at_year"] == 2025
    # enriched[1]["created_at_year"] == 2024
    # enriched[2]["created_at_year"] is None  (empty input)
```

---

## Two-phase usage pattern

Every `EnrichmentRule` follows the same caller protocol:

```python
from enrichment.enrichment_rule import EnrichmentRule

def apply_rule(rule: EnrichmentRule, columns, sample_rows, rows):
    """Generic helper showing the standard two-phase call sequence."""

    # Phase 1: ask the rule what columns it wants to add
    new_columns = rule.infer_derived_columns(columns, sample_rows)

    if not new_columns:
        return columns, rows  # nothing to do

    # Phase 2: compute derived values for every row
    enriched_rows = rule.add_derived_columns(rows)

    return columns + new_columns, enriched_rows
```

---

## Dependencies

| Import | Purpose |
|--------|---------|
| `abc.ABC`, `abc.abstractmethod` | Marks the class as abstract and enforces method implementation in subclasses. |
| `shared.modules.data.column_info.ColumnInfo` | Pydantic model describing a single column (`name`, `detected_type`, `samples`). Used as both input and output type. |
