→ See handovers/HANDOVER_v3.8.4.md

This session (2026-03-22):
- Phase 2 /experiments/: Active Spotlight + delta chips + confirmed badges
- site_api handle_experiments(): now returns full field set (outcome, primary_metric, baseline/result values, etc.)
- Keystone group fix: handle_habits() cross-joins SOURCE#habitify by_group data
  (group data was never in habit_scores — lives in habitify partition as nested dict)
- VERIFIED LIVE: keystone_group="Nutrition" 63%, best_day=6 (Sunday), all 9 groups present
- Keystone Spotlight + DOW Pattern both rendering on /habits/

Next session entry point:
1. Phase 2 next: /discoveries/ — task 47 (empty state + data-days placeholder)
   Check: curl -s https://averagejoematt.com/api/correlations | python3 -m json.tool | head -20
2. Withings sync investigation — no weigh-ins since Mar 7, getting urgent
3. Mar 21 total_completed=0 in habitify DynamoDB — minor gap, low priority

Key context:
- by_group in habitify DynamoDB: {Group: {completed, possible, pct (0.0-1.0), habits_done}}
- pct is 0.0-1.0 NOT 0-100; conversion done in handle_habits() x100
- All 9 groups: Nutrition, Growth, Wellbeing, Data, Performance, Discipline, Recovery, Hygiene, Supplements
- Phase 2 status: habits ✅ experiments ✅ discoveries ⏳ live-expansion ⏳ character ⏳
