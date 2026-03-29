# Life Platform Handover — v3.7.17
**Date:** 2026-03-14
**Session type:** R8 gap closure sprint + SIMP-1 Phase 1a

---

## What Was Done

### SIMP-1 Phase 1a — Habits cluster
Merged 7 habit tools into `get_habits(view=...)` dispatcher:
- Removed: get_habit_adherence, get_habit_streaks, get_keystone_habits, get_group_trends, get_habit_stacks, get_habit_dashboard, get_habit_tier_report
- Added: `get_habits` with view enum (dashboard/adherence/streaks/tiers/stacks/keystones)
- Retained: `compare_habit_periods` standalone (4 required params, not dispatchable)
- Net: 116 → 109 tools (−7 removed, +1 added)
- Warmer.py unchanged — calls `tool_get_habit_dashboard` directly (function still exists)

### R8 gap closure — 8 items
**Risk-7 (compute pipeline timing):**
- `daily_brief_lambda.py`: emits `LifePlatform/ComputePipelineStaleness` CW metric (0 or 1) after reading computed_metrics
- `deploy/create_compute_staleness_alarm.sh`: alarm `life-platform-compute-pipeline-stale` created ✅

**R8-ST7 (HAE S3 scope):**
- `ingestion_hae()` in role_policies.py: raw/matthew/* → 5 explicit paths (cgm_readings, blood_pressure, state_of_mind, workouts, health_auto_export)

**R8-ST6 (CDK IAM blocking gate):**
- ci-cd.yml: IAM change in CDK diff now `::error` + `exit 1` (was `::warning`, non-blocking)

**R8-ST3 (maintenance mode):**
- `deploy/maintenance_mode.sh enable|disable|status`: disables 7 non-essential EventBridge rules for vacation/absence. Core ingestion + compute always kept running.

**R8-ST4 (OAuth token health):**
- `freshness_checker_lambda.py`: checks DescribeSecret LastChangedDate on 4 OAuth secrets. SNS alert if >60 days. Emits OAuthTokenStaleCount metric.
- `operational_freshness_checker()`: added OAuthSecretDescribe statement for 4 OAuth secrets.

**R8-ST2 (DDB PITR restore runbook):**
- RUNBOOK.md: full DynamoDB PITR Restore section — verify PITR, drill procedure (restore to test table, verify, delete), emergency restore steps, notes.
- Note: actual restore drill (running the commands) still recommended as a future exercise.

**R8-LT7 (hypothesis disclaimer):**
- get_hypotheses registry description: added "IMPORTANT: Active hypotheses are unconfirmed — require 3 confirming observations before promotion."

**R8-QS3 (COST_TRACKER model routing):**
- Haiku entry marked stale; actual routing is Sonnet (~$3/mo).

**PROJECT_PLAN corrections:**
- TB7-1, TB7-2: corrected to Done (were previously completed but never marked)
- R8-QS2, QS3, QS4: marked Done

---

## Platform Status
- Version: v3.7.17
- MCP tools: 109 (was 116)
- All alarms: OK (+ 1 new: life-platform-compute-pipeline-stale)
- All CI: 20/20
- DLQ: 0
- All CDK stacks: UPDATE_COMPLETE
- Post-reconcile smoke: 10/10 ✅

---

## R8 Findings Status (post-session)
All actionable R8 findings are now resolved or in progress:
- ✅ Finding-1 (COST-B IAM drift) — v3.7.15
- ✅ Finding-2 (webhook auth) — v3.7.15
- ✅ Finding-3 (deploy script proliferation) — v3.7.16
- ✅ Finding-4 (no integration test) — v3.7.16
- ⏳ Finding-5 (SIMP-1 tool count) — 109/≤80, Phase 1b+ next
- ✅ Finding-6 (DDB restore runbook) — v3.7.17
- ✅ Risk-7 (compute timing observability) — v3.7.17
- ✅ Risk-8 (DDB restore) — v3.7.17 (runbook; drill still recommended)
- ✅ Risk-9 (deploy proliferation) — v3.7.16
- ✅ Risk-10 (stale docs) — v3.7.17

---

## Next Session — Recommended Order
1. **SIMP-1 Phase 1b** — Data + Health + Nutrition clusters (~−7 tools, 109→~102)
   - `get_daily_snapshot` (merge get_daily_summary + get_latest)
   - `get_longitudinal_summary` (merge get_aggregated_summary + get_seasonal_patterns + get_personal_records)
   - `get_health` (merge get_health_dashboard + get_health_risk_profile + get_health_trajectory)
   - `get_nutrition` (merge get_nutrition_summary + get_macro_targets + get_meal_timing + get_micronutrient_report)
2. **PITR restore drill** — run `deploy/create_compute_staleness_alarm.sh` already done; actual PITR drill is still pending (run the restore-to-test-table commands in RUNBOOK)
3. **Google Calendar integration** (R8-ST1) — highest-priority unbuilt feature, ~6-8h

---

## Files Changed This Session
- `mcp/tools_habits.py` — tool_get_habits dispatcher added
- `mcp/registry.py` — 7 tools removed, get_habits added, hypothesis disclaimer
- `lambdas/daily_brief_lambda.py` — compute staleness CW metric
- `lambdas/freshness_checker_lambda.py` — OAuth token health check
- `cdk/stacks/role_policies.py` — 3 IAM changes (daily_brief CW, freshness OAuth, HAE S3 scope)
- `.github/workflows/ci-cd.yml` — IAM gate blocking
- `deploy/maintenance_mode.sh` (new)
- `deploy/create_compute_staleness_alarm.sh` (new)
- `docs/RUNBOOK.md` — PITR restore section
- `docs/COST_TRACKER.md` — model routing stale entry
- `docs/PROJECT_PLAN.md` — 10+ items marked Done
- `docs/CHANGELOG.md` — v3.7.17 entry
- `handovers/HANDOVER_v3.7.17.md` — this file
