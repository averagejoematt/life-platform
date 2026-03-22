# SIMP-1 Phase 2 — MCP Architecture Elevation Plan
**Date:** 2026-03-21 | **Status:** Planning | **Target:** ~April 13, 2026 (Week 5)

---

## Executive Summary

The MCP layer has 95 tools across 22 modules. Usage frequency is a poor signal in alpha/beta. The right question is architectural: which tools compute at query time what could be pre-computed by a Lambda and stored in DynamoDB?

**Guiding principle:** MCP tools should be one of:
1. **Thin reads** — read pre-computed DynamoDB records (character_sheet, computed_metrics, etc.)
2. **Raw data queries** — fetch date ranges, snapshots, search (these ARE the point of MCP)
3. **Write tools** — log events, save insights, create tasks (never move these)
4. **Free-form analysis** — cross-source correlations, ad-hoc exploration (keep, this is MCP's value)

What belongs **upstream in a compute Lambda**: composite scores, rolling window aggregations, multi-source joins that produce daily metrics that don't change until the next day's data arrives.

---

## Current Tool Inventory (95 tools)

### Category breakdown
| Category | Count | Already correct? |
|----------|-------|-----------------|
| Data access (fetch/query) | 7 | ✅ Yes — keep |
| Write / log tools | 17 | ✅ Yes — never move |
| Strength training (fetch + light calc) | 8 | ⚠️ 2 should migrate |
| Training load (EWA models) | 6 | ⚠️ 2 should thin |
| Health & body (multi-source composites) | 10 | ⚠️ 4 should thin/migrate |
| Sleep (fetch + analysis) | 2 | ✅ Keep |
| Nutrition (fetch + daily agg) | 6 | ⚠️ 1 should migrate |
| Correlation (Pearson/regression) | 8 | ✅ These ARE the MCP use case — keep |
| Labs & genome (fetch) | 5 | ✅ Keep |
| CGM (fetch + aggregation) | 2 | ✅ Keep |
| Habits (fetch + streak calc) | 8 | ⚠️ 1 should migrate |
| Journal (fetch + AI analysis) | 4 | ⚠️ 1 should migrate |
| Character sheet (reads pre-computed) | 4 | ✅ Already correct |
| Board of directors | 2 | ⚠️ 1 needs fix |
| Memory & decisions (write + fetch) | 7 | ✅ Keep |
| Experiments & hypotheses | 5 | ✅ Keep |
| Social & lifestyle | 5 | ⚠️ 1 should migrate |
| Adaptive mode (reads pre-computed) | 3 | ✅ Already correct |
| Sick days (write + fetch) | 3 | ✅ Keep |
| Rewards (write + fetch) | 2 | ✅ Keep |
| Todoist (API integration) | 5 | ✅ Keep |

---

## Specific Tool-by-Tool Plan

## Phase 1 Status: ✅ COMPLETE (2026-03-21)

**`tool_get_readiness_score` thinned:**
- Eliminated duplicate 7d Whoop query (lines 173/192 — now reuses `whoop_recent`)
- Eliminated 30d Whoop query for HRV trend → reads `computed_metrics.hrv_7d` + `hrv_30d`
- Eliminated `tool_get_training_load` call (264d Strava + Banister model) → reads `computed_metrics.tsb`
- Added `_precomputed_cross_check` field to show `daily-metrics-compute` values for comparison
- DynamoDB queries: 5+ → 3 (computed_metrics, whoop 7d, garmin) with full fallback to live if pre-compute absent
- Verified: `training_form.source = pre_computed_metrics`, `hrv_trend.source = pre_computed_metrics`, 3 queries
- Deployed to `life-platform-mcp` Lambda 2026-03-21

---

### ✅ KEEP AS-IS (already architecturally correct)

These tools are thin DynamoDB reads, write operations, or free-form query tools. No changes needed.

**Already reading pre-computed partitions:**
- `get_character_sheet` / `get_character` / `get_pillar_detail` / `get_level_history` → reads `character_sheet` partition ✅
- `get_adaptive_mode` → reads `adaptive_mode` partition ✅

**Fetch-only / raw data access (correct MCP layer):**
- `get_sources`, `get_latest`, `get_daily_snapshot`, `get_date_range`, `get_daily_snapshot` ✅
- `get_habits`, `get_habit_registry`, `get_essential_seven`, `get_habit_tier_report` ✅
- `get_journal_entries`, `search_journal` ✅
- `get_labs`, `get_lab_results`, `search_biomarker`, `get_genome_insights` ✅
- `get_cgm` ✅
- `get_board_of_directors` ✅
- `get_food_log`, `get_nutrition`, `get_meal_timing` ✅
- `get_garmin_summary`, `get_gait_analysis`, `get_blood_pressure_dashboard` ✅
- All Todoist tools, all write/log tools, all sick day tools, all memory tools ✅

**Free-form analysis (this is MCP's purpose — never move):**
- `get_cross_source_correlation` — user-specified field pairs, can't pre-compute ✅
- `get_caffeine_sleep_correlation`, `get_alcohol_sleep_correlation`, `get_exercise_sleep_correlation` ✅
- `get_meditation_correlation`, `get_weather_correlation`, `get_glucose_sleep_correlation`, `get_supplement_correlation` ✅
- `get_field_stats`, `find_days`, `search_activities` ✅
- `get_experiment_results`, `get_hypotheses`, `get_journal_insights` (AI-powered, keep) ✅

---

### 🔧 PHASE 1 — Thin existing tools to read pre-computed data

These tools re-compute metrics that `daily-metrics-compute` (9:40 AM) already pre-computes into `computed_metrics`. The tools need to be thinned to read that partition first; fall back to live computation only if pre-computed record is missing (e.g., before 9:40 AM).

**Tool: `get_readiness_score`**
- Currently: queries 5 sources (Whoop 35%, HRV trend 25%, TSB 20%, Garmin 15%, sleep debt 5%)
- `computed_metrics` already stores: `readiness_score`, `readiness_color`, `sleep_debt_hours`, `tsb`, `hrv_7d_avg`
- Fix: read `readiness_score` + `readiness_color` from `computed_metrics` first; only fall back to live calc if pre-computed record is missing
- Effort: XS (30 min)

**Tool: `get_hr_recovery_trend`**
- Currently: fetches 30 days of Whoop HRV, applies 7d EWA at query time
- `computed_metrics` already stores: `hrv_7d_avg`, `hrv_30d_avg`
- Fix: read pre-computed averages; supplement with date-range spark for the trend line
- Effort: XS (30 min)

**Tool: `get_health` (pillar health view)**
- Currently: reads character_sheet (already pre-computed ✅) but also re-assembles from sub-sources
- Fix: consolidate to read fully from `character_sheet` + `computed_metrics` partitions
- Effort: S (1h)

**Tool: `get_training` (load view)**
- Currently: queries 84-day Strava window, computes CTL/ATL/TSB + HRV join in-tool
- `computed_metrics` already stores `tsb` and `acwr`
- Fix: read TSB/ACWR from `computed_metrics`; only compute extended Banister model (CTL/ATL slope, periodization flags) if user asks for depth > today's snapshot
- Effort: S (1h)

---

### 🏗️ PHASE 2 — Migrate computation into existing Lambdas

These tools do genuine computation that runs at query time and should run once daily instead.

**Tool: `get_autonomic_balance` → add to `daily-metrics-compute`**
- Currently: fetches 30d Whoop HRV + RHR at query time, computes HRV/RHR ratio trend + Garmin backup
- This is a daily metric — doesn't change until tomorrow's data
- Migrate: add `autonomic_balance_score`, `hrv_rhr_ratio`, `autonomic_trend` to `computed_metrics`
- Tool becomes: single DynamoDB read of `computed_metrics` + format output
- Effort: S (1-2h)

**Tool: `get_deficit_sustainability` → add to `daily-metrics-compute`**
- Currently: joins Withings weight + MacroFactor TDEE + Apple Health calories at query time, computes LBM loss risk, energy availability, adaptation likelihood
- This is a daily metric — safe to pre-compute at 9:40 AM
- Migrate: add `caloric_deficit_rate`, `lbm_loss_risk`, `energy_availability`, `adaptation_likelihood` to `computed_metrics`
- Tool becomes: single DynamoDB read + interpretation
- Effort: M (2-3h)

**Tool: `get_habit_stacks` → add to `daily-insight-compute` (or hypothesis-engine)**
- Currently: correlates habit completion patterns across all habits at query time to find keystone habits
- This is weekly-stable computation (habit patterns don't shift daily)
- Migrate: add keystone habit analysis to weekly hypothesis-engine Sunday run
- Store: `keystone_habits[]`, `correlation_matrix` in new `habit_intelligence` field in `computed_insights`
- Tool becomes: read from `computed_insights`
- Effort: M (3h)

**Tool: `get_social_dashboard` → add to `daily-insight-compute`**
- Currently: computes social connection score from interaction log + state_of_mind at query time
- This is a daily signal used by coaching
- Migrate: add `social_connection_score`, `interaction_frequency_7d`, `loneliness_risk` to `computed_insights`
- Tool becomes: read from `computed_insights`
- Effort: S (1-2h)

---

### 🏗️ PHASE 3 — New weekly strength compute (new Lambda or extend hypothesis-engine)

**Tools: `get_muscle_volume` + `get_strength_progress`**
- Currently: scan all Hevy records at query time to compute weekly volume per muscle group + regression on volume trends
- Could be expensive with large datasets; good candidate for Sunday compute
- Migrate: add weekly strength job (Sun 11:30 AM, same EventBridge cron pattern as hypothesis-engine)
- Writes: `SOURCE#computed_strength` | `WEEK#YYYY-WW` with `volume_by_muscle{}`, `pr_chronology{}`, `strength_trends{}`
- Tools become: thin reads + formatting
- Effort: M (4h)
- Note: Lower priority than Phase 2 — Hevy dataset is still relatively small; defer if Phase 1+2 deliver enough value

---

### 🏗️ PHASE 4 — Triggered compute (low frequency)

**Tool: `get_health_risk_profile`**
- Currently: joins labs + metabolic panel + immune markers at query time, computes cardiovascular/metabolic/immune risk flags
- Lab data changes 2x/year — this should NOT run on every MCP call
- Migrate: trigger compute when new lab data is written to DynamoDB (via EventBridge pipe or S3 trigger on lab upload)
- Writes: `SOURCE#computed_health_risk` | `DATE#YYYY-MM-DD` (date of last lab draw)
- Tool becomes: read latest computed risk record + present
- Effort: M (3h)
- Note: Only matters if labs are frequently queried. Low priority.

---

## What Stays Out of Scope

| What | Why |
|------|-----|
| Removing tools based on usage frequency | Alpha/beta phase — usage isn't signal yet |
| Merging tools with overlapping names | Keep surface area; each tool has distinct query context |
| Moving correlation tools upstream | These ARE the MCP use case — on-demand cross-source analysis |
| Write/log tools | Nothing to change — correctly at the MCP boundary |
| Journal AI analysis (get_journal_insights) | Already cached in-tool; fine where it is |
| All fetch-only tools | Zero computation; nothing to migrate |

---

## New DynamoDB Fields Required

All new fields go into **existing partitions** (no new tables, no GSIs):

| Partition | New Fields | Written By | Notes |
|-----------|-----------|------------|-------|
| `computed_metrics` | `autonomic_balance_score`, `hrv_rhr_ratio`, `autonomic_trend`, `caloric_deficit_rate`, `lbm_loss_risk`, `energy_availability`, `adaptation_likelihood` | daily-metrics-compute | Phase 2 additions |
| `computed_insights` | `social_connection_score`, `interaction_frequency_7d`, `loneliness_risk`, `keystone_habits[]` | daily-insight-compute (daily/weekly) | Phase 2 additions |
| `computed_strength` | `volume_by_muscle{}`, `pr_chronology{}`, `strength_trends{}` | new weekly-strength-compute | Phase 3, new partition |
| `computed_health_risk` | `cardiovascular_risk`, `metabolic_risk`, `immune_risk`, `risk_flags[]`, `computed_from_draw_date` | lab-triggered compute | Phase 4, new partition, triggered not daily |

**ADR required for:** `computed_strength` partition (new source partition) and `computed_health_risk` partition.

---

## Implementation Order

```
Phase 1 (~2h total) — Thin existing tools, zero Lambda changes:
  ├── Thin get_readiness_score → read computed_metrics
  ├── Thin get_hr_recovery_trend → read computed_metrics
  ├── Thin get_health → consolidate to character_sheet + computed_metrics
  └── Thin get_training → read TSB/ACWR from computed_metrics

Phase 2 (~7h total) — Add to existing Lambdas:
  ├── daily-metrics-compute: + autonomic_balance, + deficit_sustainability
  ├── daily-insight-compute: + social_connection_score
  └── hypothesis-engine (Sunday): + keystone habit analysis
  Thin corresponding MCP tools after Lambda deploy

Phase 3 (~4h) — New weekly strength compute (if needed):
  └── new Lambda or extend hypothesis-engine Sunday job
  └── ADR for computed_strength partition

Phase 4 (~3h) — Lab-triggered risk profile (low priority):
  └── EventBridge pipe or S3 trigger on lab write
  └── ADR for computed_health_risk partition

Final (~2h):
  ├── Write docs/MCP_TOOL_CATALOG.md (tool-by-tool reference)
  ├── Update SCHEMA.md with new computed_metrics fields
  ├── Full test suite (pytest tests/ -v)
  └── Smoke test: verify thinned tools return correct data
```

---

## Success Criteria

**Not** a tool count target. Instead:

1. `get_readiness_score` responds in <50ms (was ~500ms) — reads one DynamoDB record
2. `get_deficit_sustainability` and `get_autonomic_balance` respond in <100ms
3. `daily-metrics-compute` still completes in <60s total (add new fields without blowing budget)
4. All 95 tools pass wiring coverage test (`tests/test_wiring_coverage.py`)
5. Full pytest suite passes
6. MCP_TOOL_CATALOG.md exists with each tool classified

---

## What This Is NOT

- Not a tool deletion sprint
- Not about hitting an arbitrary tool count
- Not replacing MCP tools with pre-computed snapshots for tools that need genuine ad-hoc queries (correlations, date ranges, search)

The MCP layer's job is to give Claude flexible, on-demand access to any slice of data. The compute layer's job is to run expensive daily aggregations once and store results. These are complementary, not competing.

---

*Plan derived from full 95-tool audit conducted 2026-03-21. See `docs/reviews/BOARD_SUMMIT_2026-03-16.md` for original SIMP-1 Phase 2 rationale.*
