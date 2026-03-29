# Handover — 2026-02-25 Session 6: Day Grade Zero-Score Fix (v2.22.1)

## What Happened

### Root Cause Analysis
- **Journal bug**: `score_journal()` returned `0, {"entries": 0}` when no entries exist. All other scorers return `None` for missing data. This meant journal always counted as a 0-score component in the weighted average.
- **Hydration bug**: Apple Health record for Feb 24 had `water_intake_ml: 11.83` — half a tablespoon of food-content water auto-logged by Apple Health, not intentional tracking. The formula correctly scored this as 0/100 against the 2957ml target, but the real issue is this is noise, not data.
- **Impact**: Both at 5% weight, they dragged Feb 24 from 77 (B) → 69 (C+). A full letter grade of distortion.

### Fix (Algorithm v1.1)
1. **`score_journal`**: Returns `None` (not `0`) when no entries → excluded from weighted average
2. **`score_hydration`**: Added 118ml (4oz) minimum threshold. Below = "not tracked" (returns `None`). Nobody intentionally logs half a tablespoon.
3. **Algorithm version**: Default bumped 1.0 → 1.1 for retrocompute distinction
4. **Scorecard display**: `sc_cell()` already handles `None` → shows "—" in gray. No display changes needed.

### Verification
- Profile weights confirmed: journal=0.05, hydration=0.05 (10% total drag when both score 0)
- DynamoDB day_grade record for Feb 24 confirmed: journal=0, hydration=0
- Apple Health source key confirmed: `apple_health` (not `apple`)
- All 4 patch target strings verified against production code — exact match

## Files Created
- `patch_day_grade_zero_score.py` — Python patcher (3 fixes: journal, hydration, algo version)
- `deploy_daily_brief_v221.sh` — Deploy script (patch → package → deploy → test → verify)

## Files Modified
- `CHANGELOG.md` — v2.22.1 entry added
- `PROJECT_PLAN.md` — Version bumped, item #1 completed, known issue resolved, completed table updated
- `HANDOVER_LATEST.md` — Pointer updated

## Current State
- **Not yet deployed** — scripts written, awaiting Matthew to run `bash deploy_daily_brief_v221.sh`
- No config changes needed (same timeout, memory, IAM)

## What's Next (per updated PROJECT_PLAN)
1. **Day grade retrocompute** (2-3 hr) — Backfill historical grades with algo v1.1. No dependency blocker now.
2. **Weekly Digest v2** (3-4 hr) — Needs retrocompute for grade trending
3. **API gap closure deploy** (30 min) — 3 patches ready since v2.14.3
