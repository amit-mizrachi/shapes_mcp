# LLM interaction analysis: multi-dimensional normalization failure

**Date of interaction:** 2026-02-28
**User query:** "What's the average salary for people aged 30 or more?"

## Overview

This document analyzes a two-attempt LLM agent interaction where the user asked a seemingly simple aggregation question against a bakery company employee dataset (~107 rows). The question required the LLM to normalize salary values across **two independent dimensions** -- currency and pay period -- before computing an average. The LLM failed to fully normalize in both attempts, producing incorrect results each time.

## Dataset context

The CSV contains employee records with the following relevant columns:

| Column | Example values | Notes |
|--------|---------------|-------|
| `salary_amount` | 85000, 45000, 16 | Raw numeric value |
| `salary_currency` | USD $, GBP £, ILS ₪ | Three currencies |
| `salary_type` | Yearly, Monthly, Hourly | Three pay periods |
| `date_of_birth` | 15/03/1990 | dd/mm/yyyy format |
| `date_of_birth_days` | 7378 | Days since 1970-01-01 epoch (enriched) |
| `date_of_birth_year` | 1990 | Extracted year (enriched) |

Currency distribution: ~29 USD, ~48 GBP, ~30 ILS.
Pay period distribution: ILS employees are Monthly; GBP includes some Hourly; USD employees are Yearly.

The system provides a `date_context` object via `get_schema()` with `nominal_date_epoch: "1970-01-01"` and `today_as_nominal_days: 20512` (for 2026-02-28).

The system prompt explicitly instructs the LLM:

> "A single value may need MULTIPLE normalizations... Combine all dimensions into one transform -- do not normalize only one and ignore the others."

---

## Attempt 1: currency partially handled, pay period ignored

### What the LLM did

1. Called `get_schema()` and discovered the full schema including `salary_amount`, `salary_currency`, `salary_type`, `date_of_birth_days`, and the date context.
2. Correctly computed the age threshold: `(20512 - x) / 365.25 >= 30` yields `x <= 9554.5`.
3. Called `aggregate` with a transform that handled only one currency conversion (GBP to USD) and filtered on `date_of_birth_days <= 9554.5`.

### Equivalent SQL

```sql
SELECT AVG(
  CASE
    WHEN salary_currency = 'GBP £' THEN salary_amount * 1.25
    ELSE salary_amount * 1
  END
) AS annual_salary_usd
FROM employees
WHERE date_of_birth_days <= 9554.5
```

### Assessment

| Aspect | Status | Detail |
|--------|--------|--------|
| Age filter | Correct | Used `date_of_birth_days <= 9554.5`, precise to the day |
| GBP to USD | Correct | Applied `* 1.25` multiplier |
| ILS to USD | **Missed** | ILS amounts treated as USD (fell through to `else_multiply: 1`) |
| Salary type normalization | **Missed** | Monthly and Hourly salaries not annualized |

**Result returned:** $57,272.38 (incorrect).

### Impact of the errors

- ~30 ILS employees had their salary amounts treated as USD. A monthly salary of 45,000 ILS was counted as $45,000/year instead of the correct $145,800/year (45,000 * 12 * 0.27).
- 2 Hourly GBP employees had values like 16 GBP counted as $20 (16 * 1.25) instead of $41,600 (16 * 2080 * 1.25).

### User correction

> "There is also salary in NIS which you ignored."

The user identified the missing ILS currency handling but did not mention the missing salary type normalization.

---

## Attempt 2: ILS added, pay period still ignored, age filter regressed

### What the LLM did

1. First attempted to filter on a non-existent `age` column, which failed with an error.
2. Called `get_schema()` again.
3. Ran an exploratory aggregation to count employees by `salary_currency`, confirming three currencies exist.
4. Called `aggregate` with an updated transform that now included ILS conversion, but switched the age filter from `date_of_birth_days` to `date_of_birth_year <= 1996`.

### Equivalent SQL

```sql
SELECT AVG(
  CASE
    WHEN salary_currency = 'GBP £' THEN salary_amount * 1.25
    WHEN salary_currency = 'ILS ₪' THEN salary_amount * 0.27
    ELSE salary_amount * 1
  END
) AS salary_in_usd
FROM employees
WHERE date_of_birth_year <= 1996
```

### Assessment

| Aspect | Status | Detail |
|--------|--------|--------|
| ILS to USD | **Fixed** | Added `* 0.27` multiplier |
| GBP to USD | Correct | Retained `* 1.25` multiplier |
| Salary type normalization | **Still missed** | Monthly and Hourly salaries still not annualized |
| Age filter | **Regressed** | Switched from precise `_days` filter to approximate `_year <= 1996` |

**Result returned:** $53,650.35 (still incorrect).

### Why the age filter regressed

The `date_of_birth_year <= 1996` filter is less precise than the `date_of_birth_days <= 9554.5` filter from Attempt 1. Someone born on December 31, 1996 would be only 29 years old on February 28, 2026, yet they pass the `year <= 1996` check. The LLM fixed one problem (ILS) while inadvertently degrading another (age precision).

### Ongoing salary type errors

The salary type dimension remained completely unaddressed:

| Employee example | Raw value | Attempt 2 calculation | Correct calculation |
|-----------------|-----------|----------------------|---------------------|
| Monthly ILS employee | 45,000 ILS/month | 45,000 * 0.27 = **$12,150** | 45,000 * 12 * 0.27 = **$145,800** |
| Hourly GBP employee | 16 GBP/hour | 16 * 1.25 = **$20** | 16 * 2080 * 1.25 = **$41,600** |
| Yearly USD employee | 85,000 USD/year | 85,000 * 1 = **$85,000** | 85,000 * 1 = **$85,000** |

Monthly salaries were undervalued by a factor of 12. Hourly salaries were undervalued by a factor of 2,080.

---

## What the correct solution looks like

A correct approach must normalize **both** currency and pay period in a single transform using multi-column conditions. Each case matches on a (currency, salary_type) pair and applies the combined multiplier.

### Correct transform definition

```json
{
  "source_column": "salary_amount",
  "cases": [
    {
      "when": [
        {"column": "salary_currency", "value": "GBP £"},
        {"column": "salary_type", "value": "Yearly"}
      ],
      "then_multiply": 1.25
    },
    {
      "when": [
        {"column": "salary_currency", "value": "GBP £"},
        {"column": "salary_type", "value": "Hourly"}
      ],
      "then_multiply": 2600
    },
    {
      "when": [
        {"column": "salary_currency", "value": "ILS ₪"},
        {"column": "salary_type", "value": "Monthly"}
      ],
      "then_multiply": 3.24
    },
    {
      "when": [
        {"column": "salary_currency", "value": "ILS ₪"},
        {"column": "salary_type", "value": "Yearly"}
      ],
      "then_multiply": 0.27
    }
  ],
  "else_multiply": 1,
  "alias": "annual_salary_usd"
}
```

### Equivalent SQL

```sql
SELECT AVG(
  CASE
    WHEN salary_currency = 'GBP £' AND salary_type = 'Yearly'  THEN salary_amount * 1.25
    WHEN salary_currency = 'GBP £' AND salary_type = 'Hourly'  THEN salary_amount * 2600
    WHEN salary_currency = 'ILS ₪' AND salary_type = 'Monthly' THEN salary_amount * 3.24
    WHEN salary_currency = 'ILS ₪' AND salary_type = 'Yearly'  THEN salary_amount * 0.27
    ELSE salary_amount
  END
) AS annual_salary_usd
FROM employees
WHERE date_of_birth_days <= 9554.5
```

### Multiplier derivations

| Currency | Pay period | Multiplier breakdown | Combined |
|----------|-----------|---------------------|----------|
| GBP £ | Yearly | 1.25 (GBP->USD) | 1.25 |
| GBP £ | Hourly | 2080 (hours/year) * 1.25 (GBP->USD) | 2,600 |
| ILS ₪ | Monthly | 12 (months/year) * 0.27 (ILS->USD) | 3.24 |
| ILS ₪ | Yearly | 0.27 (ILS->USD) | 0.27 |
| USD $ | Yearly | 1 (identity) | 1 |

---

## Summary of issues

### 1. Consistent failure at multi-dimensional normalization

Across both attempts, the LLM treated normalization as a single-axis problem. In Attempt 1 it considered only currency (and only partially). In Attempt 2, after being corrected on ILS, it added the missing currency but never considered that `salary_type` is a second, independent axis that also requires normalization. The concept of combining two qualifier columns into a single CASE expression with compound conditions did not surface in the LLM's reasoning.

### 2. User correction caused tunnel vision

When the user pointed out the missing ILS handling, the LLM focused narrowly on that single gap. It did not step back to ask "what else might I be missing?" or re-examine the full set of qualifier columns. This is a known pattern: corrective feedback can inadvertently narrow the LLM's attention rather than triggering a broader reassessment.

### 3. Age filter regression

The LLM's age filter quality moved backward between attempts:

| Attempt | Filter | Precision |
|---------|--------|-----------|
| 1 | `date_of_birth_days <= 9554.5` | Day-level accuracy |
| 2 | `date_of_birth_year <= 1996` | Year-level accuracy (can include 29-year-olds) |

This regression happened silently -- the LLM did not acknowledge the tradeoff or explain why it switched approaches.

### 4. System prompt guidance was insufficient

The system prompt already contains explicit guidance about multi-dimensional normalization: *"A single value may need MULTIPLE normalizations... Combine all dimensions into one transform."* Despite this, the LLM did not apply the instruction. The guidance was either not attended to during generation, or the LLM failed to map the abstract instruction to the concrete columns in front of it.

### 5. Schema lacks "unit qualifier" annotations

The schema presents `salary_currency` and `salary_type` as independent columns with no explicit relationship to `salary_amount`. The LLM must infer from column names and values that these columns qualify the numeric column. A human analyst recognizes "salary_amount + salary_currency + salary_type" as a single composite measurement, but the LLM treated them as unrelated attributes.

---

## Key takeaways

**For system prompt design:**

- Abstract instructions ("normalize multiple dimensions") are not enough. The prompt should provide a concrete example showing a multi-column CASE expression that combines currency and pay period. LLMs follow examples more reliably than abstract rules.
- Consider adding a "pre-flight checklist" instruction: before constructing a transform, list all columns that qualify the target numeric column, then confirm each is accounted for.

**For schema design:**

- Annotating numeric columns with their qualifier columns would make the relationship explicit. For example, `salary_amount` could carry metadata like `qualifiers: ["salary_currency", "salary_type"]`, signaling to the LLM that both must be addressed in any normalization.
- Alternatively, the schema could include a `units` field (e.g., `units: "{salary_currency}/{salary_type}"`) that makes the composite nature of the measurement visible.

**For interaction patterns:**

- When a user corrects one error, the system should prompt the LLM to re-validate the entire approach, not just patch the specific issue mentioned. A "re-check all dimensions" step after any correction would help prevent tunnel vision.
- Exploratory aggregations (like the count-by-currency in Attempt 2) are valuable. Extending this pattern to also count by `salary_type` would have surfaced the Monthly and Hourly values and likely triggered the LLM to handle them.

**For evaluation and testing:**

- Multi-dimensional normalization queries should be a dedicated test category. A test suite should include cases where the correct answer requires combining two or more qualifier columns in a single transform, since this is a reliable failure mode.
- Regression testing should verify that fixing one aspect of a query does not degrade another (as happened with the age filter).
