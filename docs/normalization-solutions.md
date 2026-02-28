# Multi-Dimensional Normalization: Concrete Solutions

**Date:** 2026-02-28
**Problem:** When a numeric column is qualified by two or more categorical columns (e.g., `salary_amount` qualified by both `salary_currency` and `salary_type`), the LLM consistently normalizes only one dimension and ignores the others, producing incorrect aggregation results.

**Root causes identified in the interaction analysis:**
1. The system prompt tells the LLM to "combine all dimensions" but gives no concrete example of a multi-column CASE expression.
2. The `get_schema()` output lists columns as a flat list with no indication that certain text columns *qualify* a numeric column.
3. The tool docstrings show a transform example that normalizes only one dimension (`salary_type`), reinforcing single-dimension thinking.
4. There is no enrichment-time or query-time guardrail that detects when a numeric column has multiple qualifier columns.

---

## Solution 1: Richer Transform Examples in Tool Docstrings

### What

Replace the single-dimension transform example in the `select_rows` and `aggregate` tool descriptions with a multi-dimension example. The example the LLM sees in the tool spec is the single strongest influence on the shape of the transforms it constructs. Currently both tools show:

```json
{"source_column": "salary_amount", "cases": [
    {"when": [{"column": "salary_type", "value": "Monthly"}], "then_multiply": 12},
    {"when": [{"column": "salary_type", "value": "Hourly"}], "then_multiply": 2080}
], "else_multiply": 1, "alias": "annual_salary"}
```

This teaches the LLM that a single `when` list contains a single condition. Replace it with an example that shows compound conditions across two qualifier columns.

### Where

File: `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/tool_handlers.py`

In `select_rows` docstring (around line 96-101), replace the transform example:

```python
    - transform: compute a derived column using conditional math (CASE WHEN logic). Structure:
        {"source_column": "price", "cases": [
            {"when": [{"column": "currency", "value": "GBP"}], "then_multiply": 1.25},
            {"when": [{"column": "currency", "value": "EUR"}], "then_multiply": 1.08}
        ], "else_multiply": 1, "alias": "price_usd"}
      Each "when" can contain MULTIPLE conditions (AND logic). Use this when a value needs
      normalization across more than one dimension (e.g., both currency AND pay period):
        {"source_column": "salary_amount", "cases": [
            {"when": [{"column": "currency", "value": "GBP"}, {"column": "pay_period", "value": "Hourly"}], "then_multiply": 2600},
            {"when": [{"column": "currency", "value": "GBP"}, {"column": "pay_period", "value": "Yearly"}], "then_multiply": 1.25},
            {"when": [{"column": "currency", "value": "ILS"}, {"column": "pay_period", "value": "Monthly"}], "then_multiply": 3.24}
        ], "else_multiply": 1, "alias": "annual_salary_usd"}
      IMPORTANT: if a numeric column has TWO qualifier columns, you must create cases for each
      combination of values, not just each value of one qualifier.
      The computed column is added to each row. You can sort by the alias via order_by.
```

Apply the same change in the `aggregate` docstring (around line 161-168).

### Tradeoff

| Pros | Cons |
|------|------|
| Zero code changes -- docstring only | Docstrings become longer, increasing token usage per tool call |
| Directly addresses the root cause: the LLM imitates what it sees | Still depends on the LLM generalizing from the example |
| Works for any CSV, not dataset-specific | No hard guarantee the LLM will follow it |

### Effort

**Low.** Two docstring edits in one file, no logic changes, no tests to update.

---

## Solution 2: Pre-Aggregation Checklist in the System Prompt

### What

Add a structured "pre-flight checklist" to the system prompt that the LLM must follow before constructing any transform. The current prompt says "combine all dimensions" as a passing remark. The new version makes it a numbered procedure that forces the LLM to enumerate qualifier columns explicitly before writing the CASE expression.

### Where

File: `/Users/nadavfrank/Desktop/projects/shapes_mcp/shared/config.py`

Add the following block to the system prompt, after the existing "DATA QUALITY RULES" section:

```python
"NORMALIZATION CHECKLIST (follow before every transform):\n"
"1. Identify the target numeric column you are about to aggregate (e.g., salary_amount).\n"
"2. List ALL text columns that qualify or describe the unit/scale of that numeric column.\n"
"   Ask: 'Does this text column change what the number MEANS?' If yes, it is a qualifier.\n"
"   Common qualifier patterns: currency, unit, pay period, frequency, measurement type.\n"
"3. Count the qualifiers. If there are N qualifiers, your transform must have cases for\n"
"   the cross-product of their distinct values (e.g., 3 currencies x 3 pay periods = up to 9 cases).\n"
"4. For each combination, compute the combined conversion factor.\n"
"   Example: GBP + Hourly -> hourly_to_yearly * gbp_to_usd = 2080 * 1.25 = 2600.\n"
"5. Only THEN construct the transform with compound 'when' conditions.\n"
"6. Double-check: every qualifier column must appear in at least one 'when' condition.\n"
"   If a qualifier column is absent from all conditions, you have missed a dimension.\n"
"\n"
```

### Tradeoff

| Pros | Cons |
|------|------|
| Forces a deliberate enumeration step, reducing the chance of skipping a dimension | Adds ~200 tokens to the system prompt |
| Generalizable to any dataset and any number of qualifiers | LLMs may still skip the checklist under complex reasoning |
| The "cross-product" framing explicitly addresses the multi-dimension gap | Requires the LLM to identify qualifiers from column names (heuristic) |
| No code changes beyond the prompt string | |

### Effort

**Low.** One string edit in `config.py`.

---

## Solution 3: Schema Annotations -- Qualifier Metadata in `get_schema()` Output

### What

Extend `ColumnInfo` to carry an optional `qualifiers` list, and extend the ingestion pipeline to detect qualifier relationships heuristically. When `get_schema()` returns the schema, numeric columns would include metadata like:

```json
{
  "name": "salary_amount",
  "detected_type": "numeric",
  "samples": ["85000", "45000", "16"],
  "qualifiers": [
    {"column": "salary_currency", "distinct_values": ["USD $", "GBP £", "ILS ₪"]},
    {"column": "salary_type", "distinct_values": ["Yearly", "Monthly", "Hourly"]}
  ]
}
```

This makes the relationship between `salary_amount` and its qualifiers explicit in the schema, so the LLM does not need to infer it from column names.

### Detection Heuristic

A new enrichment rule (`QualifierDetectionRule`) would run at ingestion time. For each numeric column, it examines text columns whose names share a prefix or semantic stem with the numeric column (e.g., `salary_amount` -> `salary_currency`, `salary_type`). The heuristic:

1. Extract the stem of each numeric column: `salary_amount` -> `salary`.
2. Find text columns whose name starts with the same stem: `salary_currency`, `salary_type`.
3. Verify the text column has low cardinality (fewer than ~10 distinct values) -- high-cardinality text columns are not qualifiers, they are identifiers.
4. Attach these as qualifiers on the numeric column.

### Where

**New file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/enrichment/rules/qualifier_detection_rule.py`

```python
from __future__ import annotations

import logging
from collections import defaultdict

from enrichment.enrichment_rule import EnrichmentRule
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)

_MAX_QUALIFIER_CARDINALITY = 10


class QualifierDetectionRule(EnrichmentRule):
    """Detect text columns that qualify numeric columns by sharing a name prefix."""

    def __init__(self) -> None:
        self._qualifier_map: dict[str, list[dict]] = {}  # numeric_col -> [{column, distinct_values}]

    def infer_derived_columns(
        self, columns: list[ColumnInfo], sample_rows: list[dict],
    ) -> list[ColumnInfo]:
        # This rule does not add new columns; it annotates existing ones.
        # We store the qualifier map for later retrieval.
        numeric_cols = [c for c in columns if c.detected_type == "numeric"]
        text_cols = [c for c in columns if c.detected_type == "text"]

        for num_col in numeric_cols:
            stem = self._extract_stem(num_col.name)
            if not stem:
                continue
            qualifiers = []
            for text_col in text_cols:
                if text_col.name.startswith(stem + "_") and text_col.name != num_col.name:
                    distinct_values = list(set(
                        str(row.get(text_col.name, "")).strip()
                        for row in sample_rows
                        if str(row.get(text_col.name, "")).strip()
                    ))
                    if 1 < len(distinct_values) <= _MAX_QUALIFIER_CARDINALITY:
                        qualifiers.append({
                            "column": text_col.name,
                            "distinct_values": sorted(distinct_values),
                        })
            if qualifiers:
                self._qualifier_map[num_col.name] = qualifiers
                logger.info(
                    "QualifierDetection: %s is qualified by %s",
                    num_col.name,
                    [q["column"] for q in qualifiers],
                )

        return []  # No new columns added

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        return rows  # No row-level changes

    @property
    def qualifier_map(self) -> dict[str, list[dict]]:
        return self._qualifier_map

    @staticmethod
    def _extract_stem(column_name: str) -> str | None:
        parts = column_name.rsplit("_", 1)
        return parts[0] if len(parts) > 1 else None
```

**Modified file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/shared/modules/data/column_info.py`

Add an optional `qualifiers` field:

```python
class ColumnInfo(ShapesBaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    detected_type: str
    samples: list[str] = []
    qualifiers: list[dict] | None = None  # [{"column": "...", "distinct_values": [...]}]
```

**Modified file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/tool_handlers.py`

In `get_schema`, include qualifiers in the column output:

```python
"columns": [
    {
        "name": c.name,
        "detected_type": c.detected_type,
        "samples": c.samples,
        **({"qualifiers": c.qualifiers} if c.qualifiers else {}),
    }
    for c in schema.columns
],
```

**Modified file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/server.py`

Register the rule and propagate qualifier metadata back onto the `ColumnInfo` objects after enrichment:

```python
from enrichment.rules.qualifier_detection_rule import QualifierDetectionRule

def build_data_store(csv_path: str) -> SqliteDataStore:
    parsed_csv = CSVParser.parse(csv_path)

    qualifier_rule = QualifierDetectionRule()
    enricher = ColumnEnricher(
        rules=[NominalDateRule(), MonthExtractionRule(), YearExtractionRule(), qualifier_rule]
    )
    enriched_csv = enricher.enrich(parsed_csv)

    # Attach qualifier metadata to column info objects
    if qualifier_rule.qualifier_map:
        updated_columns = []
        for col in enriched_csv.columns:
            if col.name in qualifier_rule.qualifier_map:
                updated_columns.append(ColumnInfo(
                    name=col.name,
                    detected_type=col.detected_type,
                    samples=col.samples,
                    qualifiers=qualifier_rule.qualifier_map[col.name],
                ))
            else:
                updated_columns.append(col)
        enriched_csv = ParsedCSV(
            table_name=enriched_csv.table_name,
            columns=updated_columns,
            rows=enriched_csv.rows,
        )

    ingester = SqliteIngester()
    table_schema = ingester.ingest(enriched_csv)
    return SqliteDataStore(table_schema=table_schema)
```

### Tradeoff

| Pros | Cons |
|------|------|
| Makes qualifier relationships explicit -- the LLM sees them in schema, not just column names | Name-prefix heuristic will miss qualifiers that do not share a naming convention (e.g., `amount` + `currency_code`) |
| Includes distinct values, so the LLM knows exactly what cases to build | Adds complexity to the enrichment pipeline |
| Generalizable: works on any CSV where naming conventions hold | Heuristic may produce false positives (e.g., `order_id` and `order_status` -- `order_id` is numeric but `order_status` is not a unit qualifier) |
| Reduces the cognitive load on the LLM significantly | Requires changes to four files and new tests |

### Effort

**Medium.** One new file, three modified files, needs unit tests for the detection heuristic.

---

## Solution 4: Tool-Level Warning When Aggregating Qualified Columns

### What

Add a validation step in the `aggregate` tool handler that detects when the LLM is aggregating a numeric column that has known qualifiers but the transform does not reference all qualifier columns. Instead of silently producing a wrong answer, the tool returns a warning in the response that tells the LLM to add the missing dimension.

This is a "guardrail" approach -- it does not prevent the LLM from making the first mistake, but it catches it before the wrong result reaches the user and gives the LLM a chance to self-correct.

### Where

**Modified file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/tool_handlers.py`

Add a validation function and call it from `aggregate`:

```python
def _check_transform_covers_qualifiers(
    transform: TransformExpression | None,
    field: str | None,
    schema: TableSchema,
) -> str | None:
    """Return a warning string if the transform does not cover all qualifier columns,
    or None if everything looks fine."""
    # Determine which column is being aggregated
    target_col_name = transform.source_column if transform else field
    if not target_col_name:
        return None

    # Find the column in the schema
    target_col = next((c for c in schema.columns if c.name == target_col_name), None)
    if not target_col or not target_col.qualifiers:
        return None

    qualifier_col_names = {q["column"] for q in target_col.qualifiers}

    if not transform:
        # Aggregating a qualified column with no transform at all
        return (
            f"WARNING: '{target_col_name}' has qualifier columns {sorted(qualifier_col_names)} "
            f"that indicate mixed units/scales. You should use a transform with cases that "
            f"normalize across ALL qualifier dimensions before aggregating. "
            f"Without normalization, the result will be meaningless (mixing different units)."
        )

    # Check which qualifier columns are referenced in the transform's when conditions
    referenced_cols = set()
    for case in transform.cases:
        for fc in case.when:
            referenced_cols.add(fc.column)

    missing = qualifier_col_names - referenced_cols
    if missing:
        return (
            f"WARNING: Your transform normalizes '{target_col_name}' using "
            f"{sorted(referenced_cols)} but does NOT account for qualifier column(s) "
            f"{sorted(missing)}. The column has these qualifiers: "
            f"{target_col.qualifiers}. You must add cases for the missing dimension(s) "
            f"to get a correct result. Please rebuild the transform with cases covering "
            f"ALL qualifier combinations."
        )

    return None
```

In `aggregate()`, call this check before executing the query:

```python
async def aggregate(...) -> str:
    data_store = _get_data_store(context)
    schema = await data_store.get_schema()

    # Guardrail: check transform coverage
    warning = _check_transform_covers_qualifiers(transform, field, schema)
    if warning:
        return json.dumps({"warning": warning})

    # ... rest of existing logic ...
```

### Tradeoff

| Pros | Cons |
|------|------|
| Catches the exact failure mode observed: aggregating with an incomplete transform | Requires Solution 3 (qualifier metadata) to be implemented first |
| Returns a clear, actionable message to the LLM | Adds a round-trip: the LLM must call aggregate again after fixing |
| Does not produce incorrect results -- fails safe | May be overly cautious for cases where partial normalization is intentional |
| Generalizable: works on any column with qualifier metadata | The LLM could theoretically get stuck in a loop if it keeps missing dimensions |

### Effort

**Medium.** Depends on Solution 3 being in place. One function added, one function modified, needs integration tests.

---

## Solution 5: Enrichment-Time Pre-Normalization (Normalized Column Generation)

### What

Add an enrichment rule that detects numeric columns with qualifier columns and pre-computes a "best-effort normalized" column at ingestion time. For the salary example, this would produce a column like `salary_amount_normalized` that contains the annualized USD-equivalent value for every row, computed using conversion factors derived from the qualifier values.

The key challenge is that the system does not know conversion factors (exchange rates, period multipliers) at ingestion time. This solution addresses that by:

1. **Not performing actual conversion** -- instead, it normalizes only the *period dimension* (Hourly -> multiply by 2080, Monthly -> multiply by 12), because period multipliers are universal and stable.
2. Leaving currency conversion to the LLM, since exchange rates are external knowledge.

Alternatively, the rule could produce the normalized column *without* any conversion, but with a clear indication of what it represents, effectively separating the "easy" normalization (period) from the "hard" one (currency).

### Where

**New file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/enrichment/rules/period_normalization_rule.py`

```python
from __future__ import annotations

import logging
import re

from enrichment.enrichment_rule import EnrichmentRule
from shared.modules.data.column_info import ColumnInfo

logger = logging.getLogger(__name__)

# Maps period-type values to annualization multipliers
_PERIOD_MULTIPLIERS = {
    "hourly": 2080,
    "daily": 260,
    "weekly": 52,
    "biweekly": 26,
    "monthly": 12,
    "quarterly": 4,
    "yearly": 1,
    "annual": 1,
    "annually": 1,
}

_PERIOD_KEYWORDS = {"period", "type", "frequency", "interval", "basis"}


class PeriodNormalizationRule(EnrichmentRule):
    """Detect a numeric column paired with a period/frequency qualifier and
    pre-compute an annualized version of the numeric column."""

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str, str]] = []  # (numeric_col, period_col, derived_col)

    def infer_derived_columns(
        self, columns: list[ColumnInfo], sample_rows: list[dict],
    ) -> list[ColumnInfo]:
        self._pairs = []
        numeric_cols = [c for c in columns if c.detected_type == "numeric"]
        text_cols = [c for c in columns if c.detected_type == "text"]
        existing = {c.name for c in columns}

        for num_col in numeric_cols:
            stem = num_col.name.rsplit("_", 1)[0] if "_" in num_col.name else None
            if not stem:
                continue
            for text_col in text_cols:
                if not text_col.name.startswith(stem + "_"):
                    continue
                suffix = text_col.name[len(stem) + 1:]
                if suffix not in _PERIOD_KEYWORDS:
                    continue
                # Verify that the text column values match known period terms
                sample_values = [
                    str(row.get(text_col.name, "")).strip().lower()
                    for row in sample_rows
                    if str(row.get(text_col.name, "")).strip()
                ]
                if not sample_values:
                    continue
                match_ratio = sum(1 for v in sample_values if v in _PERIOD_MULTIPLIERS) / len(sample_values)
                if match_ratio < 0.8:
                    continue

                derived = f"{num_col.name}_annualized"
                if derived not in existing:
                    self._pairs.append((num_col.name, text_col.name, derived))
                    logger.info(
                        "PeriodNormalization: will add '%s' from '%s' x '%s'",
                        derived, num_col.name, text_col.name,
                    )

        return [
            ColumnInfo(name=derived, detected_type="numeric", samples=[])
            for _, _, derived in self._pairs
        ]

    def add_derived_columns(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            for num_col, period_col, derived in self._pairs:
                raw_amount = row.get(num_col)
                period = str(row.get(period_col, "")).strip().lower()
                multiplier = _PERIOD_MULTIPLIERS.get(period)

                if raw_amount is None or multiplier is None:
                    row[derived] = None
                    continue

                try:
                    row[derived] = float(raw_amount) * multiplier
                except (ValueError, TypeError):
                    row[derived] = None

        return rows
```

**Modified file:** `/Users/nadavfrank/Desktop/projects/shapes_mcp/mcp-server/src/server.py`

Register the rule:

```python
from enrichment.rules.period_normalization_rule import PeriodNormalizationRule

enricher = ColumnEnricher(rules=[
    NominalDateRule(), MonthExtractionRule(), YearExtractionRule(),
    PeriodNormalizationRule(),
])
```

### Tradeoff

| Pros | Cons |
|------|------|
| Eliminates one entire dimension of normalization at query time -- the LLM only needs to handle currency | Only handles the period dimension; currency still requires LLM reasoning |
| Deterministic and correct -- no LLM judgment involved for period conversion | Heuristic detection (name prefix + keyword suffix + value matching) may miss or misfire on unconventional column names |
| Reduces the multi-dimensional problem to a single-dimensional one, which the LLM handles more reliably | Adds a column to the schema that may confuse the LLM if it does not understand the column's purpose |
| Universally applicable period multipliers (hours/day/month/year conversions are not dataset-specific) | The annualized column name needs to be self-documenting or the LLM may not use it |

### Effort

**Medium.** One new file, one line changed in `server.py`, needs unit tests for the rule logic and for edge cases (missing values, non-numeric values).

---

## Recommended Implementation Order

| Priority | Solution | Reason |
|----------|----------|--------|
| 1 | **Solution 1** (tool docstring examples) | Highest impact-to-effort ratio. The existing single-dimension example is actively teaching the LLM the wrong pattern. Fix this first. |
| 2 | **Solution 2** (system prompt checklist) | Low effort, reinforces Solution 1 by giving the LLM a procedure to follow rather than just an example to imitate. |
| 3 | **Solution 3** (schema qualifier annotations) | Medium effort, but creates the infrastructure needed for Solution 4 and makes the system fundamentally more informative. |
| 4 | **Solution 4** (tool-level guardrail) | The safety net. Even if the LLM ignores the prompt and examples, it cannot produce an incorrect result because the tool will reject incomplete transforms. Requires Solution 3. |
| 5 | **Solution 5** (period pre-normalization) | Solves one specific dimension class permanently, but does not generalize to all qualifier types (only period/frequency). Implement if period qualifiers are common in your user base. |

Solutions 1 and 2 should be implemented together as a single change. They are complementary: the docstring teaches by example, the prompt teaches by procedure. Together they address the problem from two angles at the prompt-engineering level.

Solutions 3 and 4 should be implemented together. Solution 3 without Solution 4 is informational-only (the LLM sees qualifiers but can still ignore them). Solution 4 without Solution 3 is impossible (the guardrail needs qualifier metadata to function).

Solution 5 is independent and can be implemented at any time. It is most valuable if combined with Solutions 1-2, because the LLM still needs to handle the remaining currency dimension via a transform.

---

## Combined Effect

If all five solutions are implemented, the system would handle the original failing query as follows:

1. **At ingestion time:** `PeriodNormalizationRule` creates `salary_amount_annualized` (salary * period multiplier). `QualifierDetectionRule` annotates `salary_amount` with qualifiers `[salary_currency, salary_type]` and `salary_amount_annualized` with qualifier `[salary_currency]`.

2. **At schema time:** `get_schema()` returns the qualifier annotations. The LLM sees that `salary_amount_annualized` exists and is qualified only by `salary_currency`.

3. **At query time:** The LLM follows the normalization checklist (Solution 2), identifies that `salary_amount_annualized` needs only currency conversion, and builds a single-dimension transform (which it handles reliably). Alternatively, if the LLM uses `salary_amount` directly, the checklist forces it to enumerate both qualifiers and build compound cases.

4. **If the LLM still misses a dimension:** The tool-level guardrail (Solution 4) rejects the incomplete transform with an actionable error message, giving the LLM a second chance.

This defense-in-depth approach means no single point of failure: the LLM has better examples (Solution 1), a procedure to follow (Solution 2), explicit qualifier data (Solution 3), a safety net (Solution 4), and a simpler problem to solve (Solution 5).
