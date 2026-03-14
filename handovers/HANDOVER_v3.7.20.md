# Life Platform Handover — v3.7.20
**Date:** 2026-03-14
**Session type:** R8-ST5 + R8-LT3 + R8-LT9

---

## What Was Done

### R8-ST5 — Composite Scores Pre-compute ✅
- Added `write_composite_scores()` to `lambdas/daily_metrics_compute_lambda.py`
- Called at end of `lambda_handler()` after all existing store calls
- Writes `SOURCE#composite_scores | DATE#<date>` partition
- Fields: day_grade_score, day_grade_letter, readiness_score, readiness_colour, tier0_streak, tier01_streak, tsb, hrv_7d, hrv_30d, latest_weight, component_scores, computed_at, algo_version
- Non-fatal: write failures logged, don't block Daily Brief
- Schema documented in `docs/SCHEMA.md`

### R8-LT3 — Unit Tests for Business Logic ✅
- Created `tests/test_business_logic.py` — 74 tests, 74/74 passing (0.17s)
- Module-level env var setup (USER_ID, TABLE_NAME, S3_BUCKET) + boto3 mock for dmc import
- Test classes:
  - `TestScoringHelpers` (13) — clamp, avg, safe_float
  - `TestLetterGrade` (12) — all grade boundaries
  - `TestScoreSleep` (6) — including oversleep penalty, clamping
  - `TestScoreRecovery` (4)
  - `TestScoreNutrition` (4) — protein floor, overeating penalty
  - `TestComputeDayGrade` (5) — weighted average, component scores, clamping
  - `TestCharacterHelpers` (16) — all helper functions
  - `TestGetTier` (4) — default and custom configs
  - `TestComputeTSB` (3) — zero load, recent heavy, distant past
  - `TestComputeReadiness` (4) — none/gray, high/green, low/red, clamping
- Key fix: score_movement always returns score (exercise_score=0) even with no data — test updated to reflect actual behavior

### R8-LT9 — Weekly Correlation Compute Lambda ✅
- New Lambda: `lambdas/weekly_correlation_compute_lambda.py`
- Schedule: Sunday 11:30 AM PT (`cron(30 18 ? * SUN *)`) — 30 min before hypothesis engine
- 20 Pearson correlation pairs, 90-day rolling window
- Writes to `SOURCE#weekly_correlations | WEEK#<iso_week>` (e.g. WEEK#2026-W11)
- Idempotent: skips if already computed for week (pass force=true to override)
- CDK wired in `cdk/stacks/compute_stack.py` + `cdk/stacks/role_policies.py`
- Schema documented in `docs/SCHEMA.md`

---

## Platform Status
- Version: v3.7.20
- MCP tools: 86
- Lambdas: 43 (added weekly-correlation-compute)
- All alarms: OK
- CI: 7/7 registry + 74/74 business logic
- Smoke: 10/10
- DLQ: 0

---

## R8 Review — All Actionable Items Resolved ✅

| ID | Item | Status |
|----|------|--------|
| R8-QS1 | SIMP-1 Phase 1a-1d | ✅ Done (116→86 tools) |
| R8-QS2 | Integration test in qa-smoke Lambda | ✅ Done |
| R8-QS3 | COST_TRACKER model routing update | ✅ Done |
| R8-QS4 | Archive deploy scripts | ✅ Done |
| R8-ST1 | Google Calendar integration | ⏳ Not started (highest-priority unbuilt) |
| R8-ST2 | DynamoDB restore runbook | ✅ Done |
| R8-ST3 | Maintenance mode script | ✅ Done |
| R8-ST4 | OAuth token health monitoring | ✅ Done |
| R8-ST5 | Composite scores pre-compute | ✅ Done (v3.7.20) |
| R8-ST6 | CDK diff IAM blocking gate | ✅ Done |
| R8-ST7 | HAE S3 scope tightening | ✅ Done |
| R8-LT1 | Architecture Review #9 | ⏳ Gated on SIMP-1 Phase 2 (~Apr 13) |
| R8-LT2 | IC-4/IC-5 readiness eval | ⏳ Gated on data (~May 2026) |
| R8-LT3 | Unit tests for business logic | ✅ Done (v3.7.20) |
| R8-LT4 | DynamoDB export to S3/Athena | ⏳ Deferred (premature) |
| R8-LT5 | SLO target review | ⏳ Gated on 90-day data |
| R8-LT6 | Lambda@Edge auth CDK verify | ✅ Done — manually managed, documented |
| R8-LT7 | Hypothesis disclaimer | ✅ Done |
| R8-LT8 | DLQ consumer model | ✅ Done — ADR-024, retain schedule model |
| R8-LT9 | Weekly correlation matrix | ✅ Done (v3.7.20) |

---

## Remaining Open Items

### Active (no gate)
| ID | Item | Notes |
|----|------|-------|
| R8-ST1 | **Google Calendar integration** | Highest-priority unbuilt feature (~6-8h) |

### Gated
| ID | Item | Gate |
|----|------|------|
| SIMP-1 Phase 2 | EMF-driven cuts of low-use tools | ~2026-04-13 (30-day EMF data) |
| R8-LT1 | Architecture Review #9 | After Phase 2 |
| R8-LT2 | IC-4/IC-5 readiness | ~May 2026 (data maturity) |
| R8-LT5 | SLO review | 90 days operational data |

---

## Next Session
**Google Calendar integration (R8-ST1)** — the only remaining unblocked R8 item. ~6-8 hours. OAuth token rotation pattern, new ingestion Lambda, CDK wiring, MCP tool.

---

## Files Changed This Session
- `lambdas/daily_metrics_compute_lambda.py` — write_composite_scores() added
- `lambdas/weekly_correlation_compute_lambda.py` — new Lambda (R8-LT9)
- `tests/test_business_logic.py` — 74-test business logic suite (R8-LT3)
- `cdk/stacks/compute_stack.py` — WeeklyCorrelationCompute Lambda wired
- `cdk/stacks/role_policies.py` — compute_weekly_correlations() IAM added
- `docs/SCHEMA.md` — composite_scores + weekly_correlations partitions documented
- `docs/CHANGELOG.md` — v3.7.20 entry
- `deploy/sync_doc_metadata.py` — PLATFORM_FACTS v3.7.20, 43 Lambdas
- `handovers/HANDOVER_v3.7.20.md` — this file
