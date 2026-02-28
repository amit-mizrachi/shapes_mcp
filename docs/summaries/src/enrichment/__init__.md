# `enrichment/__init__.py` -- Empty package marker

## Overview

`enrichment/__init__.py` is an empty file that marks the `enrichment` directory as a Python package. It contains no imports, exports, or re-exports. All public functionality is accessed by importing directly from the submodules.

## Exports / Imports

None. The file is empty.

## Package structure

```
enrichment/
    __init__.py              <-- this file (empty)
    enrichment_rule.py       EnrichmentRule (abstract base class)
    column_enricher.py       ColumnEnricher (orchestrator)
    rules/
        __init__.py          empty package marker
        date_detection.py    detect_date_columns() utility
        month_extraction_rule.py   MonthExtractionRule
        year_extraction_rule.py    YearExtractionRule
        nominal_date_rule.py       NominalDateRule
```

## How the package is used

Because `__init__.py` is empty, consumers import submodules directly:

```python
from enrichment.enrichment_rule import EnrichmentRule
from enrichment.column_enricher import ColumnEnricher
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from enrichment.rules.year_extraction_rule import YearExtractionRule
from enrichment.rules.nominal_date_rule import NominalDateRule
```

## Package purpose

The `enrichment` package implements a rule-based column-enrichment pipeline for CSV data. Its responsibilities are:

1. **Define a rule contract** -- `EnrichmentRule` is an abstract base class with two methods:
   - `infer_derived_columns(columns, sample_rows)` -- inspects existing columns and a sample of rows to decide which new columns to add.
   - `add_derived_columns(rows)` -- computes and attaches the derived values to every row.

2. **Orchestrate rule execution** -- `ColumnEnricher` accepts a list of `EnrichmentRule` instances, runs each rule's detection phase against a configurable sample of rows, then applies only the rules that matched. It returns a new `ParsedCSV` with the original columns plus any derived columns appended.

3. **Provide concrete date-enrichment rules** -- The `rules` sub-package ships three rules, all backed by a shared `detect_date_columns()` utility that auto-detects date-formatted columns using a threshold-based heuristic (80 % of sample values must parse successfully):

   | Rule | Derived column | Value |
   |------|---------------|-------|
   | `MonthExtractionRule` | `{col}_month` | Integer month (1--12) |
   | `YearExtractionRule` | `{col}_year` | Integer year |
   | `NominalDateRule` | `{col}_days` | Integer days since a configurable epoch |

## Design notes

- The package follows the **Strategy pattern**: `ColumnEnricher` is agnostic to the specific rules it runs; new enrichment rules can be added by implementing `EnrichmentRule` and registering the instance at construction time.
- Detection and transformation are intentionally separated into two phases so the orchestrator can log which rules matched before doing any mutation.
- Configuration values (`detection_sample_size`, `max_samples`, `nominal_date_epoch`) are read from `shared.config.Config` at runtime, keeping the enrichment logic decoupled from config storage.
