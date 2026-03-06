# Session 35 — Resilient Gap-Aware Backfill

**Date:** 2026-02-28
**Version:** v2.45.0 → v2.46.0
**Focus:** Self-healing data gap detection across all 6 API-based ingestion Lambdas

---

## What Happened

### Problem
All API-based ingestion Lambdas fetched exactly one day (yesterday). If a run failed (Lambda error, API outage, rate limit, device sync delay), that day's data was permanently missing unless manually backfilled via AWS Console. This caused Daily Briefs with missing sections, Weekly/Monthly Digests with reduced sample sizes, and MCP tools returning less accurate correlations.

### Solution: Gap-Aware Lookback Pattern
Each Lambda now checks DynamoDB for the last 7 days of records on every scheduled run, identifies missing dates, and fetches only those from the upstream API. Self-bootstrapping — no schema changes, no last-sync marker, no seed data needed. Existing records ARE the reference point.

### Implementation Across 6 Lambdas

| Lambda | Change | Strategy |
|--------|--------|----------|
| **Garmin** | Already had gap-fill (v1.6.0) | No changes needed |
| **Whoop** | New `find_missing_dates()` + cleaned duplicate helpers | Check-then-fetch, 3 modes (date override/today/gap-fill) |
| **Eight Sleep** | New `_ensure_auth()` + `_ingest_with_retry()` | Check-then-fetch, preserves 401 retry logic |
| **Strava** | Widened default fetch window to `LOOKBACK_DAYS` | API returns all activities in window, `put_item` upserts |
| **Withings** | New `_ingest_single_day()` helper | Check-then-fetch, graceful empty returns on no-weigh days |
| **Habitify** | New gap-fill preserving range backfill mode | 3 modes: range/single/gap-fill |

### Key Design Decisions
- `LOOKBACK_DAYS` env var (default 7), tunable per Lambda without redeployment
- Rate-limit pacing: 0.5–1s between gap-day API calls
- Whoop: filters `#WORKOUT#` sub-items from gap detection (only base DATE# records)
- Whoop: cleaned up duplicate `_sleep_onset_minutes` and `_compute_sleep_consistency` blocks
- Withings: fixed duplicate `compute_body_comp_deltas()` call in original handler
- Normal day with no gaps = 1 DynamoDB query + 0 API calls (negligible cost)

---

## Files Modified
- `lambdas/whoop_lambda.py` — gap-fill + code cleanup
- `lambdas/eightsleep_lambda.py` — gap-fill with auth retry
- `lambdas/strava_lambda.py` — widened default window
- `lambdas/withings_lambda.py` — gap-fill + bug fix
- `lambdas/habitify_lambda.py` — gap-fill preserving range mode
- `deploy/deploy_gap_fill.sh` — sequential deploy of all 5
- `deploy/install_gap_fill.sh` — copy + deploy helper

## Docs Updated
- CHANGELOG.md — v2.46.0 entry
- PROJECT_PLAN.md — version bump + header
- ARCHITECTURE.md — version bump + gap-aware backfill section in Ingest Layer

---

## Current State
- **Version:** v2.46.0
- **All 5 Lambdas deployed** with gap-aware backfill ✅
- **No schema changes needed** — self-bootstrapping from existing data
- Tonight's scheduled runs will be the first gap-aware executions

## Pending / Next Steps
1. **Monitor CloudWatch logs** tomorrow morning — look for `[GAP-FILL]` log lines confirming gap detection ran
2. **Feature #2: Google Calendar** — demand-side data, highest remaining roadmap priority
3. **Feature #1: Monarch Money** — financial stress pillar
4. **Feature #13: Annual Health Report** — year-in-review email
5. **Infrastructure audit** — remaining phases from earlier audit
