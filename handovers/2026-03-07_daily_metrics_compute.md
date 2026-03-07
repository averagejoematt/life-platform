# Handover — 2026-03-07 — Daily Metrics Compute Lambda (#53)

## Session Summary

Built and deployed the Daily Brief compute refactor. New Lambda pre-computes all
derived metrics at 9:40 AM PT so the Daily Brief becomes a pure read + render operation.

---

## What Was Built

### Daily Metrics Compute Lambda (v2.82.0 — 32nd Lambda)

**`lambdas/daily_metrics_compute_lambda.py`**
- Scheduled at 9:40 AM PT (17:40 UTC) — between character-sheet-compute (9:35) and daily-brief (10:00)
- Imports `scoring_engine.py` for `compute_day_grade()`
- Inline: `compute_readiness()`, `compute_habit_streaks()`, `compute_tsb()`, `normalize_whoop_sleep()`, `dedup_activities()`
- Idempotent: skips if `computed_metrics` record already exists. Override: `{"force": true}`
- Backfill: `{"date": "2026-03-06", "force": true}`
- Timeout: 120s (needs 60d Strava range + 30d HRV range + 90d habit streak lookback)

**DDB writes (3 partitions):**
1. `SOURCE#computed_metrics` — primary output. Contains everything the Brief previously computed inline
2. `SOURCE#day_grade` — existing schema, preserved for MCP tools and regrade backfill
3. `SOURCE#habit_scores` — existing schema, preserved for habit trending MCP tools

**`computed_metrics` record schema:**
```
pk:                  USER#matthew#SOURCE#computed_metrics
sk:                  DATE#YYYY-MM-DD
date, computed_at, algo_version
day_grade_score      (Decimal)
day_grade_letter     (str)
component_scores     (map of name → Decimal)
component_details    (map of name → nested map)
readiness_score      (Decimal)
readiness_colour     (str: green/yellow/red/gray)
tier0_streak         (Decimal)
tier01_streak        (Decimal)
vice_streaks         (map of habit_name → Decimal)
tsb                  (Decimal)
hrv_7d, hrv_30d      (Decimal)
sleep_debt_7d_hrs    (Decimal)
latest_weight, week_ago_weight, avatar_weight  (Decimal)
```

**`deploy/deploy_daily_metrics_compute.sh`**
- Auto-detects IAM role from `life-platform-mcp` Lambda
- EventBridge: `cron(40 17 * * ? *)` = 9:40 AM PT
- Zip: `lambda_function.py` + `scoring_engine.py`
- Smoke test: invokes with yesterday's date on deploy

### Daily Brief Refactored

**`lambdas/daily_brief_lambda.py` — bumped to v2.82.0**

Three new conditional blocks in `lambda_handler()` right after the Strava dedup block:

**Block 1 — fetch + day grade:**
- Fetches `computed_metrics` for yesterday
- If found: reads pre-computed scores/details directly (skips `compute_day_grade` + `store_day_grade`)
- If not found: falls back to inline computation + stores (existing behavior unchanged)

**Block 2 — readiness:**
- If `_computed`: reads `readiness_score` / `readiness_colour`
- Else: calls `compute_readiness(data)` as before

**Block 3 — habit streaks:**
- If `_computed`: reads `tier0_streak`, `tier01_streak`, `vice_streaks`
- Else: calls `compute_habit_streaks()` + `store_habit_scores()` as before

**Log signals to watch:**
- `[INFO] Using pre-computed metrics for 2026-03-07` ← happy path (compute Lambda ran)
- `[WARN] No pre-computed metrics for ... — computing inline (fallback)` ← compute Lambda missed
- `[INFO] Day Grade (pre-computed): 78 (B+)` vs `[INFO] Day Grade (inline): 78 (B+)`

---

## Deploy Instructions

```bash
# Deploy the new Lambda + EventBridge schedule
bash deploy/deploy_daily_metrics_compute.sh

# Redeploy daily-brief with updated code
bash deploy/deploy_lambda.sh daily-brief

# Verify compute Lambda runs correctly
aws lambda invoke \
  --function-name daily-metrics-compute \
  --payload '{"date":"2026-03-06","force":true}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 /tmp/test.json && cat /tmp/test.json

# Verify Brief reads pre-computed record (check CloudWatch logs)
# Look for: [INFO] Using pre-computed metrics
```

---

## Platform State

- **Version:** v2.82.0
- **Lambdas:** 32 (added `daily-metrics-compute`)
- **MCP tools:** 124 (unchanged)
- **DDB partitions:** added `computed_metrics`

---

## What Changes for Tomorrow's Brief

First Brief after deploy will log `[WARN] No pre-computed metrics` and fall back to inline (today's `computed_metrics` record doesn't exist yet). From the next day onward, both Lambdas fire and the Brief reads pre-computed values.

To seed today's record immediately after deploying:
```bash
aws lambda invoke \
  --function-name daily-metrics-compute \
  --payload '{"date":"'"$(date -v-1d +%Y-%m-%d)"'","force":true}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 /tmp/seed.json && cat /tmp/seed.json
```

---

## Next Up

1. **CloudWatch alarm for `daily-metrics-compute`** — add error alarm (same pattern as other Lambdas)
2. **Set `BRITTANY_EMAIL`** env var — email address needed for Brittany Lambda
3. **Reward seeding** — prerequisite for Character Sheet Phase 4 completion
4. **Google Calendar** — #2 North Star gap, Board rank #9
