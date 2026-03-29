# Handover — 2026-02-25 Session 8: Day Grade Retrocompute

## What Happened

### v2.23.0 — Day Grade Retrocompute (COMPLETE ✅)
- **Scope**: Backfilled 947 day grades from 2023-07-23 → 2026-02-24 using algo v1.1.
- **Architecture**: Batch-query approach — 8 source queries + 1 journal query upfront, indexed in memory. Processed 948 dates in 4.3s query + 24.5s writes (39 writes/sec), zero errors.
- **Scoring parity**: All 8 component scorers copied verbatim from `daily_brief_lambda.py` v2.2.3 to ensure identical results.
- **Strava dedup**: Same `dedup_activities()` logic from v2.22.2 applied per-day.
- **Chronicling fallback**: `score_habits_mvp` falls back to Chronicling data for pre-Habitify era (16 days captured).
- **`source: "retrocompute"` tag**: Every backfilled record tagged to distinguish from daily-brief-computed grades.

### Results
- **Average score: 66.9 (C+)**
- Grade distribution: A-range 23.5%, B-range 24.9%, C-range 20.3%, D 19.3%, F 11.9%
- Component coverage: movement 100%, sleep 91.9%, recovery 36.2%, glucose 14.6%, nutrition 9.6%, habits 1.8%, hydration 0%, journal 0%
- Early days (2023-2024) mostly 2-3 components (sleep + movement ± recovery)
- D/F skew (31.2%) partly driven by 2-component days where one weak score drags the average

### Profile Fix
- Updated `day_grade_algorithm_version` from "1.0" → "1.1" in DynamoDB profile. The daily brief was using the profile value, causing version mismatch with the actual v1.1 algorithm.

## Final Production State
- **Platform version**: v2.23.0
- **Day grade records**: 948 (947 retrocomputed + 1 daily brief from Feb 24)
- **Coverage**: 2023-07-23 → present (daily brief adds new grades going forward)

## Files Created This Session
- `retrocompute_day_grades.py` — standalone backfill script (dry run / stats / write / force modes)

## Files Modified This Session
- `CHANGELOG.md` — v2.23.0 entry
- `PROJECT_PLAN.md` — Version bumped, #1 completed, Tier 1 renumbered, grade trending gap marked done
- `SCHEMA.md` — Day grade section updated (coverage, source field, algo version)
- `ARCHITECTURE.md` — Header bumped to v2.23.0
- `HANDOVER_LATEST.md` — Pointer updated

## Observations for Future Work
- **D/F grade skew**: 31.2% of days scored D or F, largely from 2-component days where poor sleep with no counterbalancing data sources dragged the score. As more data sources accumulate (nutrition from Feb 22, habits from Feb 22, journal upcoming), recent and future grades will be more representative.
- **Recovery coverage only 36.2%**: Whoop recovery data seems sparse relative to 912 Whoop records. Worth investigating — may be that recovery_score field is null on many records even when other Whoop data exists.
- **Hydration/journal at 0%**: Expected — water tracking only started recently, journal Notion integration is very new. These will start contributing to future grades.

## What's Next (per updated PROJECT_PLAN)
1. **Weekly Digest v2** (3-4 hr) — Now unblocked. W-o-W deltas, day grade weekly trend, Zone 2, macro adherence.
2. **API gap closure deploy** (30 min) — 3 patches ready since v2.14.3.
3. **Glucose meal response** (#6, 4-6 hr) — Highest-ROI new analysis for weight loss.
