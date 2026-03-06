# Phase 2: Database / Schema Review
**Date:** 2026-02-28 | **Version:** v2.47.1 | **Reviewer:** Claude (Expert Panel)

---

## 2.1 Table Health

**DynamoDB Stats:**
- Items: 15,316
- Size: 21.8 MB (~1.4 KB avg per item)
- Billing: PAY_PER_REQUEST (on-demand) ✅
- Deletion protection: enabled ✅
- PITR: enabled (35-day rolling recovery) ✅
- GSI: none (by design) ✅
- TTL: enabled on `ttl` attribute (cache partition) ✅

**Grade: A** — The table is healthy, well-protected, and appropriately sized. At 15K items and 21MB, you're nowhere near DynamoDB limits. On-demand billing is correct for bursty, low-volume workloads.

### Capacity assessment
At ~15K items growing by ~20-30/day (19 sources × 1 record/day + journal entries + cache + derived), you'll reach ~26K items by end of 2026. At 1.4KB average, that's ~36MB. DynamoDB handles this trivially. No capacity concerns for the foreseeable future.

---

## 2.2 Key Design Review

**Grade: A** — The composite key pattern is well-suited to the access patterns.

- `PK: USER#matthew#SOURCE#<source>` + `SK: DATE#YYYY-MM-DD` supports all time-range queries per source
- Profile at `USER#matthew` / `PROFILE#v1` is cleanly separated
- Cache at `CACHE#matthew` / `TOOL#<key>` with TTL is a good pattern
- Journal entries use `DATE#YYYY-MM-DD#journal#<template>` — good SK extension for multiple entries per day

No GSI is needed because every query starts with a known source + date range. If you ever need cross-source queries (e.g., "show me all data from Feb 24 regardless of source"), you'd need a GSI on `sk` with `pk` as sort key — but the MCP server handles this by doing parallel queries per source, which is fine at 19 sources.

---

## 2.3 Schema Findings

#### F2.1 — Strava item size risk (MEDIUM)
Strava day records contain a nested `activities` list with full activity details. A day with 5+ activities (e.g., multi-sport days or someone tracking walks + runs + rides) could grow large. The 400KB DynamoDB limit is documented as a known risk.

**Current state:** Likely well under 400KB (average person does 0-2 activities/day). But no monitoring exists to flag when items approach the limit.

**Recommendation:** Add a size check in the Strava Lambda: if the item would exceed 350KB, log a warning. Alternatively, consider moving individual activity details to `SK: DATE#YYYY-MM-DD#ACTIVITY#<strava_id>` as separate items. Low priority given actual usage patterns.

#### F2.2 — MacroFactor food_log nesting (MEDIUM)
`food_log` is a nested list within each day record. A day with 30+ food entries (common with detailed tracking) produces large nested structures. Same 400KB risk as Strava.

**Recommendation:** Same as F2.1 — add size monitoring. If items ever approach 300KB, move food_log entries to separate items with `SK: DATE#YYYY-MM-DD#FOOD#<index>`.

#### F2.3 — Inconsistent field naming between sources (LOW)
Some sources use `total_sleep_seconds` (Whoop, Eight Sleep) while the schema documents different sleep fields per source. Apple Health uses `active_energy_kcal` (XML) vs `active_calories` (webhook). This is documented but creates complexity in cross-source correlation tools.

**Recommendation:** No action needed — the MCP tools abstract this away. The SOT domain architecture means consumers only see one source's fields per domain. Just noting that the schema doc accurately reflects reality, which is good.

#### F2.4 — habit_scores partition is new and sparse (INFO)
Only 5 records exist (4 backfilled + 1 from today's brief). The MCP tools `get_habit_tier_report` and `get_vice_streak_history` will return minimal data until the partition accumulates 30+ days. This is expected — the backfill script is designed to be re-run.

**Recommendation:** Re-run the backfill monthly as Habitify data accumulates. In 30 days the trending tools will be meaningful.

#### F2.5 — No data validation at write time (LOW)
Ingestion Lambdas write to DynamoDB without schema validation. If an upstream API changes a field name or type, the bad data silently enters the table. The freshness checker catches missing data but not malformed data.

**Recommendation:** Consider adding lightweight validation in 2-3 critical Lambdas (Whoop, Strava, Eight Sleep) that checks for expected fields and logs a warning if key fields are missing. Not a schema change — just a code guardrail. Example: if Whoop returns a record without `recovery_score`, log `WARN: missing recovery_score` rather than writing an empty field.

#### F2.6 — Chronicling → Habitify habit name mismatch (INFO)
Documented in the handover: Chronicling (Oct-Nov 2025) uses different habit names than the current 65-habit registry. The backfill script correctly handles this by only scoring against the registry. Historical gap (2025-11-10 → 2026-02-22) is permanent — no fix possible.

**Status:** Working as designed. No action needed.

#### F2.7 — Profile record is growing (LOW)
The `PROFILE#v1` record now contains the 65-habit registry with full metadata per habit (mechanism, context, synergy groups). This is a large nested map. As more config moves into the profile (demo_mode_rules, source_of_truth, weight_loss_phases, day_grade_weights, habit_registry), this item could approach 100KB+.

**Recommendation:** Monitor profile item size. If it exceeds 200KB, consider splitting the habit registry into a separate `SK: PROFILE#habit_registry` item. Currently not an issue.

---

## 2.4 Schema Documentation Quality

**Grade: A+** — SCHEMA.md is one of the best-documented DynamoDB schemas I've seen. Every source, every field, every nested structure is documented with types and descriptions. The notes about SOT domains, webhook versions, and ingestion methods are exceptionally thorough.

Minor gap: The SCHEMA doc says "97 MCP tools" in the header but MCP_TOOL_CATALOG.md says "72 tools." Update the catalog to match current count.

---

## 2.5 Summary

| Area | Grade | Critical Findings | Action Items |
|------|-------|-------------------|-------------|
| Table Health | A | None | None |
| Key Design | A | None | None |
| Schema Design | A- | Item size risk (Strava, MacroFactor) | Add size monitoring |
| Data Quality | B+ | No write-time validation | Add field presence checks to top 3 Lambdas |
| Documentation | A+ | Minor catalog count mismatch | Update MCP_TOOL_CATALOG.md |

**Top 3 recommendations:**
1. Add item size monitoring to Strava and MacroFactor Lambdas (low effort, prevents silent failures)
2. Add lightweight field validation to Whoop/Strava/Eight Sleep ingestion (medium effort, catches API changes early)
3. Update MCP_TOOL_CATALOG.md to reflect 97 tools (documentation hygiene)
