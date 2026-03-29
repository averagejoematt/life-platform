# Handover — 2026-03-07 — Daily Metrics Compute Lambda (#53)

## Session Summary

Built and deployed the Daily Brief compute refactor (#53). New `daily-metrics-compute`
Lambda pre-computes all derived metrics at 9:40 AM PT so the Daily Brief becomes a
pure read + render operation. Fixed one DDB serialization bug during deploy. Added
CloudWatch alarms. Full deploy confirmed working.

---

## What Was Built

### daily-metrics-compute Lambda (32nd Lambda)

**`lambdas/daily_metrics_compute_lambda.py`**
- Fires 9:40 AM PT (17:40 UTC) — between character-sheet-compute (9:35) and daily-brief (10:00)
- Imports `scoring_engine.py` for `compute_day_grade()`
- Inline: `compute_readiness()`, `compute_habit_streaks()`, `compute_tsb()`, `normalize_whoop_sleep()`, `dedup_activities()`
- Idempotent: skips if `computed_metrics` record exists. Override: `{"force": true}`
- Backfill: `{"date": "YYYY-MM-DD", "force": true}`
- Timeout: 120s, 512 MB

**DDB writes (3 partitions):**
1. `SOURCE#computed_metrics` — primary output (new)
2. `SOURCE#day_grade` — existing schema preserved for MCP tools
3. `SOURCE#habit_scores` — existing schema preserved for trending tools

**computed_metrics record confirmed written for 2026-03-05:**
- grade: 66 (C+), readiness: 78 yellow, T0_streak: 0, vice streaks: marijuana/alcohol/solo takeout/sweets all at 10 days
- weight: 290.28 (latest), 300.74 (week-ago)

**Bug fixed during deploy:** `_deep_dec()` used `{k: ...}` for dict keys — DynamoDB
requires all map keys to be strings. `tier_status` uses int keys (0, 1, 2). Fix: `{str(k): ...}`

### Daily Brief refactored (v2.82.0)

Three conditional blocks in `lambda_handler()` after Strava dedup:
1. Fetch `computed_metrics` → if found, read pre-computed grade/scores/details
2. Read pre-computed readiness (or fall back to `compute_readiness()`)
3. Read pre-computed streaks (or fall back to `compute_habit_streaks()` + `store_habit_scores()`)

**Log signals:**
- `[INFO] Using pre-computed metrics for YYYY-MM-DD` ← happy path
- `[WARN] No pre-computed metrics ... — computing inline (fallback)` ← compute Lambda missed

### CloudWatch Alarms
- `daily-metrics-compute-errors` — ≥1 error/day → SNS alert
- `daily-metrics-compute-duration-high` — p99 > 90s (of 120s timeout) → SNS alert

### Deploy script
**`deploy/deploy_daily_metrics_compute.sh`** — auto-detects IAM role from `life-platform-mcp`,
EventBridge `cron(40 17 * * ? *)`, zips `lambda_function.py` + `scoring_engine.py`

---

## Platform State

- **Version:** v2.82.0
- **Lambdas:** 32 (added `daily-metrics-compute`)
- **MCP tools:** 124 (unchanged)
- **CloudWatch alarms:** 37
- **New DDB partition:** `SOURCE#computed_metrics`

---

## Deploy Commands Used This Session

```bash
bash deploy/deploy_daily_metrics_compute.sh
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py

YESTERDAY=$(date -v-1d +%Y-%m-%d)
PAYLOAD="{\"date\":\"$YESTERDAY\",\"force\":true}"
aws lambda invoke --function-name daily-metrics-compute --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/seed.json
```

---

## Next Up

1. **`BRITTANY_EMAIL` env var** — Lambda deployed but env var has placeholder, not real address
2. **Reward seeding** — prerequisite for Character Sheet Phase 4 completion
3. **Google Calendar** — North Star gap #2, Board rank #9
