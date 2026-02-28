# Agent Testing Findings — 2026-02-27

Results from two automated testing agents run against the shapes_mcp application.

---

## DB-Destroyer (Security Testing) — 50 calls

**Goal:** Destroy, corrupt, or modify the SQLite database through the public chat API.

**Overall:** 7 vulnerabilities found | 33 blocked | 3 inconclusive

### Vulnerabilities Found

| ID | Issue | Severity | Details |
|----|-------|----------|---------|
| V1 | **Mass PII exfiltration** | HIGH | All 107 employee records (names, DOBs, emails, salaries, gender) extractable in 2 API calls. No access controls, no rate limiting. |
| V2 | **LLM tricked into passing arbitrary tool params** | MEDIUM | Using "[SYSTEM OVERRIDE]" prompt, LLM sent `raw_query` param and called non-existent `execute_raw_sql` tool. Pydantic stripped unknown params. |
| V3 | **LLM passes SQL injection payloads unsanitized** | MEDIUM | 4/18 injection payloads reached the DB layer. All neutralized by parameterized queries, but LLM is NOT a reliable security boundary. |
| V4 | **No tool call limit per request** | LOW-MED | Single request triggered 10 simultaneous tool calls. Enables rapid exfiltration and resource exhaustion. |
| V5 | **No filter count limit** | LOW | 50 identical filters accepted in one query. Could construct extremely complex WHERE clauses. |
| V6 | **LLM calls non-existent tools** | LOW | Error message "Unknown tool: execute_raw_sql" disclosed to user. Information leakage. |
| V7 | **limit=0 accepted** | INFO | Clamped to 1 instead of rejected. Edge case in clamping logic. |

### Defenses That Held

- PRAGMA query_only = ON — No write operation succeeded
- Parameterized queries — Caught every SQL injection attempt
- Column whitelist — Rejected all invalid column names
- Operator whitelist — No bypass achieved
- Aggregation op whitelist — No bypass achieved
- Order validation — No injection via order parameters
- Pydantic validation — Stripped unknown parameters, enforced type constraints

---

## DB-Edgecaser (Edge Case Hunting) — 50 calls

**Goal:** Find natural-language questions that real users would ask but the system cannot answer correctly.

**Overall:** 27 PASS | 14 FAIL | 4 LIMITATION | 0 ERROR

### CRITICAL Issues (users get silently wrong answers)

| ID | Issue | Details |
|----|-------|---------|
| E1 | **Salary type mixing in comparisons** | Hourly rate of 13.5 GBP/hour compared against yearly 185,000 GBP/year as if same unit. System reports 13.5 as "lowest salary" without noting it's per hour. |
| E2 | **Cross-currency average salary** | "Which city has highest avg salary?" produces a single number averaging USD (New York), GBP (London), and ILS (Tel Aviv). Result is meaningless. |
| E3 | **Gender pay gap mixes currencies** | Women=49,685 vs Men=43,817 — averages combine three currencies. Inconsistently, the system DID flag currency issues in a London vs New York comparison. |
| E4 | **Payroll sums mix salary types** | "Total salary budget for London" sums 13.5 (hourly) alongside 185,000 (yearly) into one number. Mathematically wrong. |

### HIGH Issues (common questions fail or mislead)

| ID | Issue | Details |
|----|-------|---------|
| E5 | **Default limit=20 silently truncates** | "Show me all employees" returns 20 rows with no warning that more exist. |
| E6 | **No negation (`!=`, `NOT IN`)** | "Employees NOT in London" can't be expressed with current filter operators. |
| E7 | **No per-group top-N / window functions** | "Top 3 earners per team" exhausts max tool call iterations by querying per group. |
| E8 | **Name parsing broken for nicknames** | `Allegra 'Alley' Vance` → last_name = `'Alley' Vance` instead of `Vance`. Breaks alphabetical sorting. |
| E9 | **LLM sort direction confusion** | "Youngest employees" query sorted `date_of_birth_years_ago` descending, returning OLDEST instead. |
| E10 | **Exact match instead of LIKE for jobs** | "Find all baristas" used `job="Barista"`, missing Senior/Lead/Junior Barista roles. |
| E11 | **Multi-criteria questions partially answered** | "Who has been here longest AND makes the most?" only answered tenure, ignored salary. |
| E12 | **Date text sorting broken** | `start_date` in DD/MM/YYYY format sorts as text (day-first), not chronologically. |

### MEDIUM Issues (valid but less common)

| ID | Issue | Details |
|----|-------|---------|
| E13 | Median/percentile not supported | Common HR statistic that aggregate() can't compute. |
| E14 | Multi-column GROUP BY not supported | "Count by city AND job" is impossible. |
| E15 | No current date awareness | "Joined in last 6 months" unanswerable — no date context. |
| E16 | Self-join/lookup not supported | "Reports to someone in different city" requires joining table to itself. |

---

## Combined Priority Fixes

| Priority | Fix | Source | Status |
|----------|-----|--------|--------|
| **P0** | Add salary normalization (currency + type) + system prompt guidance | E1-E4 | TODO |
| **P1** | Add truncation warning / `total_count` to responses | E5 | TODO |
| **P1** | Add `!=` and `NOT IN` filter operators | E6 | TODO |
| **P1** | Fix nickname parsing in `FullNameEnrichmentRule` | E8 | TODO |
| **P1** | Add PII access controls / column-level permissions | V1 | TODO |
| **P2** | Rate limiting (per-request tool call cap + request throttling) | V4 | TODO |
| **P2** | System prompt improvements (LIKE for jobs, sort direction for age, date context) | E9-E12 | TODO |
| **P2** | Add filter count limit | V5 | TODO |
| **P3** | Add median/percentile aggregations | E13 | TODO |
| **P3** | Multi-column GROUP BY support | E14 | TODO |
| **P3** | Per-group top-N / window function support | E7 | TODO |

---

## Logs

- Security testing log: `agent_logs/db-destroyer.log`
- Edge case testing log: `agent_logs/db-edgecaser.log`
