# Session Handover — 2026-03-03

**Sessions:** 3 sessions (Notion journal v1.2, buddy food fix, buddy/hydration/dedup fixes)
**Version:** v2.60.1 → v2.61.0
**Theme:** Data integrity sweep — field mismatches, duplicate activities, missing hydration, day grade regrade

---

## What Was Done

### 1. Notion Journal Integration — Schema-Flexible v1.2 (earlier session)
- Deployed `notion_lambda.py` with dynamic property extraction (no hardcoded field names)
- Handles any Notion database schema — extracts Template, Date, and body text regardless of property UUIDs
- Pending: test with real journal entry, create Notion templates, hide 36 property fields

### 2. Buddy Page — MacroFactor Food Logging Fix
- **Bug:** "No food logged in 99 days" despite daily MacroFactor logging
- **Root cause:** Field name mismatch — code checked `calories`/`energy_kcal`, data uses `total_calories_kcal`
- **Fix:** Updated `write_buddy_json()` in both standalone and daily_brief_lambda.py
- **Fields:** `total_calories_kcal` → `calories` → `energy_kcal` (fallback chain)
- **Protein:** `total_protein_g` → `protein_g` → `protein` (fallback chain)

### 3. Buddy Page — Three UX Fixes
- **Subtitle:** "For Tom · Updated Monday morning, March 2" → "Thank you for looking out for me! · Updated Tuesday morning, March 3 at 9:43am PT"
- **Exercise count:** Changed from rolling 7-day to true Monday–Sunday weekly reset
  - `monday = today_dt - timedelta(days=today_dt.weekday())`
  - Only activities with `date_str >= monday_str` count toward `week_count`
  - Status text adapts to day of week (Mon/Tue get grace period for 0 sessions)
- **CloudFront invalidation:** Added to deploy script (distribution `ETTJ44FT0Z4GO`)

### 4. Activity Dedup — WHOOP + Garmin → Strava Duplicates
- **Problem:** Both WHOOP and Garmin push to Strava independently. Same session appears twice (e.g., "Afternoon Pickleball" from Garmin + "Afternoon Workout" from WHOOP)
- **Fix:** `_dedup_activities()` function added to both `daily_brief_lambda.py` and standalone `write_buddy_json.py`
- **Algorithm:** If two activities start within 15 min and durations within 40%, keep higher-priority device (Garmin > Apple > WHOOP)
- **Scope:** Read-time dedup in buddy page and daily brief. DynamoDB still has raw duplicates. MCP tools not yet deduped.

### 5. Hydration Data Pipeline Fix
- **Problem:** Health Auto Export app wasn't including Dietary Water/Caffeine in automatic webhook pushes — only sending activity metrics
- **Evidence:** 7 days of water data showing 0–350ml when actual intake was 3,000+ ml daily
- **Discovery:** Before today, app sent 0 metrics per push (only workouts). User's change to hourly sync fixed it — 3/4 automatic pushes today included `dietary_water`
- **Backfill:** User forced a 7-day water push from the app, data now correct in DynamoDB

### 6. Day Grade Regrade (Feb 24 – Mar 2)
- **Added `regrade_dates` mode** to `lambda_handler` — invoke with `{"regrade_dates": ["2026-02-24",...]}` to recompute grades without sending email
- **Regraded 7 days** with corrected hydration data:
  - Feb 24: 73→76 (B-→B), hydration 12→100
  - Feb 25: 58→65 (C-→C+), hydration 9→100
  - Feb 26: 72→72 (B-), hydration 0→100
  - Feb 27: 56→58 (C-), hydration 0→100
  - Feb 28: 77→72 (B→B-), hydration 0→100
  - Mar 1: 77→78 (B), hydration 0→100
  - Mar 2: 71→74 (B-), hydration 44→100
- **Regrade feature is permanent** — useful for any future data corrections

---

## Files Changed

| File | Changes |
|------|---------|
| `lambdas/daily_brief_lambda.py` | MacroFactor field fix, `_dedup_activities()`, weekly exercise count, PST timestamp, `_regrade_handler()` |
| `lambdas/buddy/write_buddy_json.py` | MacroFactor field fix, `_dedup_activities()`, weekly exercise count, PST timestamp |
| `lambdas/buddy/index.html` | Subtitle text, "Thank you for looking out for me!" |
| `lambdas/notion_lambda.py` | Schema-flexible v1.2 (earlier session) |
| `deploy/deploy_buddy_fixes_v256.sh` | CloudFront invalidation step added |
| `deploy/deploy_regrade_hydration.sh` | New — regrade script with verification |
| `deploy/deploy_buddy_food_fix.sh` | New — initial food field fix |

---

## Deployed To

| Target | Status |
|--------|--------|
| Lambda `daily-brief` | ✅ Updated (regrade mode + dedup + field fixes + weekly count) |
| S3 `buddy/index.html` | ✅ Updated (subtitle + timestamp) |
| S3 `buddy/data.json` | ✅ Regenerated (correct food, deduped exercise, weekly count) |
| CloudFront `ETTJ44FT0Z4GO` | ✅ Cache invalidated |
| DynamoDB `day_grade` records | ✅ 7 days regraded (Feb 24 – Mar 2) |
| DynamoDB `apple_health` records | ✅ Water data backfilled by user's forced push |

---

## Known Issues / Not Yet Fixed

1. **Strava duplicates in DynamoDB** — Raw activity data still contains WHOOP+Garmin dupes. Dedup is read-time only (buddy page + daily brief). MCP tools querying Strava directly may still double-count exercise minutes/sessions. Fix: add dedup at ingestion time in Strava Lambda.

2. **Health Auto Export** — Water/caffeine now flowing with hourly sync, but root cause unclear why the app wasn't sending these metrics before. Monitor over next few days to confirm stability.

3. **DST cron fix** — **CRITICAL: 5 days until March 8.** All EventBridge crons use fixed UTC. Spring forward shifts all scheduled Lambdas 1 hour later unless updated. Script exists: `deploy/deploy_dst_spring_2026.sh` — needs review and execution.

---

## Pending from Previous Sessions

| Item | Status | Notes |
|------|--------|-------|
| DST cron fix (March 8) | ⏸️ CRITICAL | 5 days away, script ready |
| Notion journal test with real entry | ⏸️ | Lambda deployed, needs manual test |
| Create Notion templates (Morning/Evening) | ⏸️ | Pre-set Template + Date |
| Hide 36 Notion property fields | ⏸️ | Database view cleanup |
| Chronicle v1.1 integration | ⏸️ | Fetch character_sheet from DDB |
| Brittany weekly email | ⏸️ | Accountability feature expansion |
| Prologue fix script deployment | ⏸️ | |
| Avatar v2 integration into dashboard | ⏸️ | |
| Strava ingestion-time dedup | ⏸️ | DDB cleanup for MCP tools |
| Monarch Money integration | ⏸️ | Financial tracking |
| Google Calendar integration | ⏸️ | Demand-side scheduling data |
| Annual Health Report | ⏸️ | |
