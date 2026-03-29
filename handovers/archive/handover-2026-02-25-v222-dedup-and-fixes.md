# Handover — 2026-02-25 Session 7: Day Grade Fix + Activity Dedup + Water Investigation

## What Happened

### v2.22.1 — Day Grade Zero-Score Fix (DEPLOYED ✅)
- **Root cause**: `score_journal()` returned `0` (not `None`) when no entries; `score_hydration()` scored Apple Health noise (11.83ml food-content water) as 0/100.
- **Fix**: Journal returns `None` when no entries. Hydration treats <118ml (4oz) as "not tracked". Algorithm version bumped 1.0→1.1.
- **Verified**: Feb 24 grade went from **69 C+ → 77 B**. Journal and hydration excluded (show "—" in scorecard).
- **Files**: `patch_day_grade_zero_score.py`, `deploy_daily_brief_v221.sh`

### Water Data Investigation
- **Symptom**: DynamoDB had 11.83ml for Feb 24; user saw 3,632ml in Apple Health.
- **Root cause**: The 11.83 was actually 11.83 fl_oz (350ml) from a tiny webhook sync — not noise. The full day's water was in the big 289KB payload that hit the Lambda **before** dietary_water was enabled (deployment timing issue from RCA incident).
- **Replay**: Wrote `replay_feb24_water.py` v2 that scans all 4 archived payloads. Found only 1 water reading for Feb 24 (11.83 fl_oz from tiny sync). The rest of the day's water never left the phone. Updated DynamoDB: 11.83ml → 350ml (unit conversion fix).
- **Status**: 350ml is correct for what was captured, but still incomplete vs 3,632ml actual. Tracked as known issue — depends on HAE sync cadence.

### v2.22.2 — Strava Activity Deduplication (READY TO DEPLOY)
- **Root cause**: WHOOP and Garmin both record the same walk and sync to Strava independently. Feb 24: "Afternoon Walk" appeared twice (WHOOP 19min no GPS + Garmin 33min with GPS).
- **Impact**: Training report showed duplicates; movement score inflated (3 activities, 125 min instead of 2 activities, 106 min).
- **Fix**: `dedup_activities()` detects overlapping activities (same sport_type, start times within 15 min) and keeps the richer record (prefers GPS/distance, then longer duration). Runs after `gather_daily_data()` so all downstream consumers (display, scoring, AI prompts) get clean data. Recomputes `activity_count` and `total_moving_time_seconds`.
- **Scope**: Daily brief only. Strava ingestion-level dedup tracked as known issue for future.
- **Files**: `patch_activity_dedup.py`, `deploy_daily_brief_v222.sh`

## Files Created
- `patch_day_grade_zero_score.py` — v2.22.1 patcher
- `deploy_daily_brief_v221.sh` — v2.22.1 deploy
- `replay_feb24_water.py` — Water data replay (v2, multi-payload scan)
- `patch_activity_dedup.py` — v2.22.2 patcher  
- `deploy_daily_brief_v222.sh` — v2.22.2 deploy

## Files Modified
- `daily_brief_lambda.py` — v2.2.1 patched (deployed)
- `CHANGELOG.md` — v2.22.1 + v2.22.2 entries
- `PROJECT_PLAN.md` — Version bumped, known issues added (Strava dedup, water sync), completed table updated
- `HANDOVER_LATEST.md` — Pointer updated

## Current State
- **Production**: v2.2.1 running. Day grade fixed. Tomorrow's 10 AM brief will be first with correct grading.
- **Pending deploy**: v2.2.2 (activity dedup) — `bash deploy_daily_brief_v222.sh`
- **Known issues added**: Strava ingestion dedup (Low), water HAE sync (Low)

## What's Next
1. **Deploy v2.22.2** — `bash deploy_daily_brief_v222.sh` (dedup fix)
2. **Day grade retrocompute** (2-3 hr) — Backfill historical grades with algo v1.1
3. **Weekly Digest v2** (3-4 hr) — Needs retrocompute for grade trending
4. **API gap closure deploy** (30 min) — 3 patches ready since v2.14.3
