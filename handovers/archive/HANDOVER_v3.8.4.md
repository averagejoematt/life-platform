# Handover v3.8.4 — 2026-03-22

## Session Summary
Phase 2 continues. /experiments/ depth + root-cause fix for empty Keystone group data.
All three new Phase 2 sections now confirmed live with real data.

## What Was Done

### Phase 2: /experiments/ content depth
**site/experiments/index.html:**
- Active Experiment Spotlight: accent-bordered card above the filter list.
  Shows name, hypothesis, day counter, optional progress bar, metric chips.
  Hidden until an active experiment exists in DynamoDB.
- Delta chips on completed cards: ↑/↓ color-coded before/after values.
  Lower-is-better metrics (weight, rhr, glucose) auto-flip color logic.
- Confirmed/refuted badges from `hypothesis_confirmed` field.
- Primary metric replaces Category field when available.
- `renderSpotlight()` and `deltaChip()` added to JS, wired into fetch callback.

**site_api_lambda.py — handle_experiments():**
Previously silently dropped: outcome, result_summary, primary_metric, baseline_value,
result_value, metrics_tracked, duration_days, days_in, progress_pct, confirmed,
hypothesis_confirmed. All now returned.

### Keystone group data fix
**Root cause:** `handle_habits()` looked for flat `group_*` fields on `SOURCE#habit_scores`
records. But group breakdown is in `SOURCE#habitify` as a nested `by_group` dict
(structure: `{Group: {completed, possible, pct, habits_done}}`). The two partitions
were never cross-joined.

**Fix:** Added second DynamoDB query in `handle_habits()` against `SOURCE#habitify`
for the same 90-day window. For each day, if habit_scores has no group_* fields,
falls back to habitify by_group.pct × 100.

**Verified live:**
- `keystone_group: "Nutrition"`, `keystone_group_pct: 63`
- `best_day: 6` (Sunday)
- All 9 groups present: Nutrition, Growth, Wellbeing, Data, Performance,
  Discipline, Recovery, Hygiene, Supplements
- Keystone Spotlight + DOW Pattern both active on /habits/

### Also confirmed: total_completed: 0 on Mar 21
DynamoDB spot-check showed `total_completed: 0` for 2026-03-21 habitify record.
This is a data gap, not a code bug — likely a sync/missed day. Not blocking.

## Files Changed

| File | Change |
|------|--------|
| `lambdas/site_api_lambda.py` | handle_habits(): habitify cross-join; handle_experiments(): full field set |
| `site/experiments/index.html` | Active Spotlight + delta chips + confirmed badges |
| `docs/CHANGELOG.md` | v3.8.4 entry |
| `handovers/HANDOVER_LATEST.md` | Updated |

## Phase 2 Status

| Page | Status | Sections added |
|------|--------|---------------|
| `/habits/` | ✅ Done | Keystone Spotlight + DOW Pattern (both live with real data) |
| `/experiments/` | ✅ Done | Active Spotlight + delta chips + confirmed badges |
| `/discoveries/` | ⏳ Next | Empty state + placeholder if no confirmed discoveries |
| `/live/` expansion | ⏳ Later | Multi-metric dashboard |
| `/character/` enhancement | ⏳ Later | Avatar + intro narrative |

## Next Session Entry Point

1. **Phase 2 next: `/discoveries/` page** — WEBSITE_STRATEGY.md task 47:
   "If no confirmed discoveries yet, show: 'X days of data collected. This page
   unlocks after Y more days of analysis.' Don't show a blank page."
   Check current state: `curl -s https://averagejoematt.com/api/correlations | python3 -m json.tool | head -20`

2. **Withings sync** — still no weigh-ins since Mar 7. Should investigate before
   the data gap gets any wider. Check: last Withings Lambda run + CloudWatch logs.

3. **Mar 21 total_completed: 0** — minor data gap, not urgent. Could backfill if
   Habitify API still has that day's data.

## Platform State
- Version: v3.8.4
- Architecture grade: A- (R13, March 2026)
- Running cost: ~$10/month
- Phase 0: ✅ | Phase 1: ✅ | Phase 2: 🔄 (habits ✅, experiments ✅, discoveries next)
