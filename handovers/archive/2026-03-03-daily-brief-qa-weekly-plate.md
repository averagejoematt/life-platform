# Session Handover — 2026-03-03 (Evening)

**Sessions:** 1 session (Daily Brief QA + Weekly Plate deploy)
**Version:** v2.61.0 → v2.63.0
**Theme:** Daily Brief QA fixes + The Weekly Plate launch (26th Lambda)

---

## What Was Done

### 1. Daily Brief QA — v2.62.0

Four fixes based on Matthew's feedback from recent daily briefs:

**Subject line wrong date** — subject showed yesterday's date (e.g. "Mon Mar 2" on Tuesday). Brief runs Tuesday morning FOR Tuesday. Fixed: `yesterday` → `today` in subject line formatting.

**Subject line cryptic readiness code** — `G/M/E/-` replaced with `🟢/🟡/🔴/⚪` emoji. The "M" was yellow readiness mapped to... "M" for unknown reasons.

**"Losing 117 lbs" hardcoded in 4 AI prompts** — training coach, journal coach, BoD intro (config + fallback), and TL;DR/guidance all had static `302->185` / `losing 117 lbs`. AI misinterpreted as "already lost 117 lbs." New `_build_weight_context(data, profile)` helper dynamically computes from `latest_weight`, `journey_start_weight_lbs`, `goal_weight_lbs` → e.g. "Started at 302 lbs, currently 290 lbs, goal 185 lbs (12 lost so far, 105 to go)".

**Training coach panics on rest days** — only saw yesterday's activities. On a walk day after strength sessions, warned about "zero strength training" and "hemorrhaging muscle." New `_build_recent_training_summary(data)` builds 7-day activity summary from `strava_7d` (filtered from existing 60d fetch, no extra DDB call). Prompt now includes LAST 7 DAYS TRAINING CONTEXT + explicit instruction not to panic about rest days.

### 2. The Weekly Plate — v2.63.0 (26th Lambda)

New Friday evening food magazine email — personalized from actual MacroFactor data.

- **Schedule:** Friday 6:00 PM PT (Saturday 02:00 UTC via EventBridge)
- **Lambda:** `weekly-plate`, Sonnet 4.5, temperature 0.6, ~63s execution, ~$0.04/week
- **Data:** 14 days MacroFactor (177 food items typical) + 30 days Withings weight + DynamoDB profile
- **5 sections:**
  1. *This Week on Your Plate* — narrative week recap with weight trend
  2. *Your Greatest Hits* — most frequent meals/ingredients, why they work
  3. *Try This* — 2-3 recipe riffs on actual ingredients (macros, difficulty, key ingredients)
  4. *The Wildcard* — one missing ingredient + Met Market recommendation
  5. *The Grocery Run* — screenshot-able grocery list by store section
- **Design:** Dark theme (#1a1a2e), gold accent (#f59e0b), mobile-first 600px
- **Tone:** Food magazine column — fun, warm, Brittany-readable

### Deploy Issues Resolved

- **Profile source mismatch:** Lambda was written to load profile from S3 (`config/profile.json`) which doesn't exist. Daily Brief loads from DynamoDB (`pk=USER#matthew`, `sk=PROFILE#v1`). Fixed `fetch_profile()` to query DynamoDB.
- **S3 permissions:** `lambda-weekly-digest-role` lacked `s3:ListBucket`. Added inline policy `s3-life-platform-read` with both `s3:GetObject` and `s3:ListBucket`.
- **CLI timeout:** Lambda takes ~63s (Sonnet call) which exceeds CLI default timeout. Lambda completed successfully despite CLI timeout. Two test emails sent.

---

## Files Changed

| File | Changes |
|------|---------|
| `lambdas/daily_brief_lambda.py` | Subject: today not yesterday, emoji readiness, `_build_weight_context()`, `_build_recent_training_summary()`, `strava_7d` in data dict, dynamic weight in 4 AI prompts, 7-day training context in training coach |
| `lambdas/weekly_plate_lambda.py` | New Lambda (455 lines). Fixed: `fetch_profile()` S3→DynamoDB, subject date formatting |
| `deploy/deploy_daily_brief_qa_fixes.sh` | New deploy script for v2.62.0 |
| `deploy/deploy_weekly_plate.sh` | New deploy script (create/update, EventBridge, test invoke) |
| `docs/CHANGELOG.md` | v2.62.0 + v2.63.0 entries |
| `docs/PROJECT_PLAN.md` | Version bump, Lambda count 25→26, email cadence table, completed versions table |

---

## Deployed To

| Target | Status |
|--------|--------|
| Lambda `daily-brief` | ✅ v2.62.0 (QA fixes) |
| Lambda `weekly-plate` | ✅ v1.0.0 (new, 26th Lambda) |
| EventBridge `weekly-plate` | ✅ `cron(0 2 ? * SAT *)` — Friday 6 PM PT |
| IAM `lambda-weekly-digest-role` | ✅ Added `s3-life-platform-read` inline policy |

---

## Verified

- ✅ Daily Brief deployed, awaiting tomorrow's email for QA verification
- ✅ Weekly Plate: 2 test emails received and confirmed "looks great"
- ✅ 13 days MacroFactor data, 177 food items, 9 days Withings — all flowing
- ✅ Sonnet call ~63s, well within 120s timeout

---

## Known Issues / Not Yet Fixed

1. **DST cron fix** — **CRITICAL: 5 days until March 8.** Script exists: `deploy/deploy_dst_spring_2026.sh`. Character sheet compute (9:35 AM PT = 17:35 UTC) will shift to 10:35 AM PDT, AFTER the Daily Brief at 10:00 AM.

2. **Weekly Plate CLI timeout** — Lambda takes ~63s which exceeds CLI invoke timeout. Not a problem for EventBridge (async). For manual testing, use `--invocation-type Event` for async invoke.

3. **Strava duplicates in DynamoDB** — Raw activity data still has WHOOP+Garmin dupes. Dedup is read-time only.

---

## Pending from Previous Sessions

| Item | Status | Notes |
|------|--------|-------|
| DST cron fix (March 8) | ⏸️ CRITICAL | 5 days away, script ready |
| Daily Brief QA verification | ⏸️ | Tomorrow's email — check subject date + training commentary |
| Notion journal test with real entry | ⏸️ | Lambda deployed, needs manual test |
| Character Sheet Phase 3 | ⏸️ | Dashboard radar chart, avatar, buddy tile, Chronicle hooks |
| Brittany weekly email | ⏸️ | Accountability feature expansion |
| Strava ingestion-time dedup | ⏸️ | DDB cleanup for MCP tools |
| Monarch Money integration | ⏸️ | Financial tracking |
| Google Calendar integration | ⏸️ | Demand-side scheduling data |
| Annual Health Report | ⏸️ | |
