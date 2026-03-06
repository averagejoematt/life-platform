# Handover — 2026-03-02 — Character Sheet Phase 2: Compute Lambda + Daily Brief Integration (v2.59.0)

## Session Summary
Built the standalone character-sheet-compute Lambda (architectural decision to separate from Daily Brief for future extensibility) and completed the Daily Brief integration that was started but cut off in a prior session. Both deployed and verified.

## Version
v2.59.0 (deployed)

## What Was Built

### New Lambda: `character-sheet-compute` (25th Lambda)
- **`lambdas/character_sheet_lambda.py`** (~290 lines) — Standalone compute Lambda
  - Queries 8 DDB source partitions + 5 rolling windows (sleep 14d, strava 7d/42d, macrofactor 14d, withings 30d)
  - Loads previous day's character_sheet for level/streak continuity
  - Rebuilds 21-day raw_score histories for EMA smoothing
  - Imports `character_engine.py` (bundled in zip)
  - Idempotent: skips if already computed, override with `{"force": true}`
  - Date override for testing: `{"date": "2026-03-01", "force": true}`
  - Schedule: EventBridge `character-sheet-compute` at 9:35 AM PT (17:35 UTC)
  - 512 MB, 60s timeout, python3.12
- **`deploy/deploy_character_sheet_compute.sh`** — Creates Lambda + EventBridge rule, auto-detects IAM role from existing MCP Lambda

### Daily Brief v2.59.0 (code from prior session, deploy script from this session)
- `lambda_handler` — fetches `character_sheet` record from DDB after day_grade computation
- `build_html` — new Character Sheet section (placed after Scorecard):
  - Overall level + tier with tier-colored styling (Foundation gray → Elite purple)
  - 7 pillar mini-bars with level, tier colors, raw scores
  - Level-up/down event callouts (tier transitions, character level changes)
  - Active effects display (Sleep Drag, Synergy Bonus, etc.)
  - Demo mode compatible (`<!-- S:character_sheet -->` markers)
- `call_board_of_directors` — receives character context for commentary
- `write_dashboard_json` — character_sheet summary in dashboard JSON
- `write_buddy_json` — character_sheet summary in buddy JSON
- **`deploy/deploy_daily_brief_v259.sh`** — This was the missing piece from the cut-off session

### Architecture Decision
Character sheet computation lives in its own Lambda rather than inside the Daily Brief. Rationale:
- **Compute → Store → Read** pattern matches anomaly detector, day_grade, habit_scores
- Future consumers (gamification digest, push notifications, Chronicle) read pre-computed records with zero coupling
- Single-purpose Lambda = easier debugging and independent scaling
- 25-minute timing gap (9:35 → 10:00) provides comfortable margin

## Deploy Flow
```
9:35 AM PT — character-sheet-compute Lambda fires
             → queries all source data
             → loads previous day's state + 21-day histories
             → computes via character_engine.compute_character_sheet()
             → stores to DDB (SOURCE#character_sheet)

10:00 AM PT — daily-brief Lambda fires
              → fetch_date("character_sheet", yesterday) reads pre-computed record
              → renders Character Sheet HTML section
              → feeds character context into BoD AI prompt
              → includes in dashboard + buddy JSON
```

## Docs Updated
- **`docs/CHANGELOG.md`** — v2.59.0 entry
- **`docs/PROJECT_PLAN.md`** — v2.59.0, 25 Lambdas, ingestion schedule updated, completed table
- **`docs/ARCHITECTURE.md`** — header updated
- **`docs/RUNBOOK.md`** — schedule table: character-sheet-compute at 9:35 AM, daily-brief version bump

## Verification
- ✅ character-sheet-compute Lambda deployed + EventBridge rule created
- ✅ Daily Brief v2.59.0 deployed
- ⏳ First full run: tomorrow morning (9:35 AM → 10:00 AM PT)
- Note: Today's character sheet already exists from backfill, so compute Lambda will skip (idempotency)

## What's Next
- **Verify tomorrow's brief** — check for Character Sheet section in email + CloudWatch logs
- **Phase 3:** Dashboard radar chart + pixel-art avatar + buddy page Character Sheet tile + Chronicle hooks
- **Phase 4:** User-defined rewards, protocol recommendations, Weekly Digest integration
- **DST warning:** March 8 is DST spring forward — character-sheet-compute cron is fixed UTC, verify timing still correct
- **Other roadmap:** Brittany weekly email, Monarch Money, Google Calendar, Annual Health Report

## Open Questions
1. Avatar generation method (AI tools vs commissioned pixel art)
2. Dashboard Character Sheet layout (radar chart vs bar chart vs both)
3. Chronicle integration depth (tier transitions as installment hooks vs sidebar mentions)
4. Phase 3 vs moving to Monarch Money / Google Calendar next
