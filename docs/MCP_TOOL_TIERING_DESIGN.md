# MCP Tool Tiering System Design
**Version:** v1.0 | **Created:** 2026-03-13 | **Status:** Design (pre-SIMP-1)
**Prerequisite for:** SIMP-1 (tool rationalization, ~2026-04-08)

---

## Purpose

144 tools is too many. The MCP context overhead, the token cost of tool descriptions, and the cognitive overhead for Claude of selecting from a dense catalog all argue for reduction. SIMP-1 targets ~100 genuinely ad-hoc tools (remove ~44). This document defines:

1. The tiering taxonomy and criteria
2. Preliminary tier assignments for all 144 tools
3. SIMP-1 data requirements (usage analytics needed before final decisions)
4. Implementation mechanism

---

## 1. Tiering Taxonomy

Four tiers. Tier 1–3 survive SIMP-1. Tier 4 are removal/merge candidates.

| Tier | Label | Target Count | Criteria |
|------|-------|-------------|---------|
| **T1** | Core | ~25 | High-frequency, no substitutes. Always registered. |
| **T2** | Domain | ~40 | Medium-frequency, domain-specific value. Always registered. |
| **T3** | Specialty | ~35 | Low-frequency, narrow use case, but irreplaceable when needed. Always registered. |
| **T4** | Candidates | ~44 | Duplicate capability, low unique value, rarely invoked, or replaceable by T1–T3. SIMP-1 removal targets. |

**Rule for write tools:** Write tools (`log_*`, `create_*`, `update_*`, `close_*`, `delete_*`) are always T1 or T2 regardless of frequency. Frequency-based demotion only applies to read tools.

---

## 2. Tiering Criteria

For each tool, score on five axes:

| Axis | Weight | Question |
|------|--------|---------|
| **Query frequency** | 40% | How often is this invoked in a typical week? (SIMP-1 data required) |
| **Unique capability** | 30% | Can another tool answer this question? If yes, is the delta material? |
| **Response utility** | 15% | Does the response actionably change behavior? Or is it informational noise? |
| **Write side effect** | 10% | Does calling this tool mutate state? (Write tools get +1 tier) |
| **Platform dependency** | 5% | Does this require a data source that may be absent? (penalizes fragile tools) |

**T1 threshold:** Frequency = high OR (unique + utility = both high)
**T2 threshold:** Frequency = medium OR unique = high
**T3 threshold:** Irreplaceable in its narrow domain, even if infrequent
**T4 threshold:** Replaceable + low frequency OR pure duplicate of another tool

---

## 3. Preliminary Tier Assignments

### TIER 1 — Core (~25 tools)

Always active. These are the backbone of every session.

| Tool | Rationale |
|------|-----------|
| `get_health_dashboard` | Daily morning briefing — highest single-tool value |
| `get_readiness_score` | Unified training/life decision signal |
| `get_character_sheet` | RPG scoring overlay — used every session |
| `get_daily_summary` | Full-day snapshot, no substitute |
| `get_latest` | Quick check on any source |
| `get_habit_dashboard` | Habit state at a glance |
| `get_habit_adherence` | Core habit analysis |
| `get_habit_tier_report` | T0/T1/T2 breakdown — drives daily behavior |
| `get_habit_registry` | Browse habit metadata |
| `get_sleep_analysis` | Clinical sleep breakdown |
| `get_training_load` | CTL/ATL/TSB — injury risk, readiness |
| `get_nutrition_summary` | Macro overview |
| `get_macro_targets` | Actual vs targets with hit rate |
| `get_journal_entries` | Retrieve Notion entries |
| `search_journal` | Full-text search |
| `get_mood_trend` | Mood/energy/stress trend |
| `list_todoist_tasks` | Current task state |
| `create_todoist_task` | Task creation (write) |
| `update_todoist_task` | Task edit (write) |
| `close_todoist_task` | Task completion (write) |
| `get_task_load_summary` | Cognitive load snapshot |
| `get_health_trajectory` | Forward-looking projections |
| `log_decision` | Decision logging (write, IC-25) |
| `read_platform_memory` | IC memory retrieval |
| `write_platform_memory` | IC memory write |

---

### TIER 2 — Domain (~40 tools)

Active by default. High value for their domain, used at least monthly.

**Weight & Body Composition (4)**
- `get_weight_loss_progress` — phase tracking, plateau detection
- `get_body_composition_trend` — fat vs lean mass deltas
- `get_energy_expenditure` — TDEE + calorie target
- `get_non_scale_victories` — fitness improvements independent of scale

**Strength Training (5)**
- `get_exercise_history` — single-exercise deep dive
- `get_strength_prs` — all-exercise 1RM leaderboard
- `get_muscle_volume` — sets vs MEV/MAV/MRV
- `get_workout_frequency` — adherence and streaks
- `get_strength_progress` — longitudinal 1RM + plateau

**Labs & Genome (5)**
- `get_lab_results` — blood work by date/category
- `get_lab_trends` — biomarker trajectories
- `get_out_of_range_history` — persistent out-of-range flags
- `get_genome_insights` — 110 SNP interpretations
- `get_health_risk_profile` — CV/metabolic/longevity synthesis

**Blood Glucose (3)**
- `get_cgm_dashboard` — time in range, variability
- `get_glucose_meal_response` — postprandial analysis
- `get_fasting_glucose_validation` — CGM vs venous lab comparison

**Journal & Coaching (3)**
- `get_journal_insights` — cross-entry patterns
- `get_journal_correlations` — mood vs wearable divergence
- `save_insight` — insight logging (write)

**N=1 Experiments (4)**
- `create_experiment` — start tracking (write)
- `list_experiments` — view all
- `get_experiment_results` — before vs during comparison
- `end_experiment` — close experiment (write)

**Hypothesis Engine (2)**
- `get_hypotheses` — generated weekly hypotheses
- `update_hypothesis_outcome` — record verdict (write)

**Decisions (2)**
- `get_decisions` — trust calibration stats
- `update_decision_outcome` — record outcome (write)

**Longevity (4)**
- `get_biological_age` — PhenoAge from blood biomarkers
- `get_metabolic_health_score` — composite CGM+labs+weight+BP
- `get_food_response_database` — personal glycemic food leaderboard
- `get_defense_patterns` — journal defense mechanism patterns

**Character Sheet (2)**
- `get_pillar_detail` — deep pillar breakdown
- `get_level_history` — level/tier change timeline

**Social & Behavioral (4)**
- `log_interaction` — social interaction logging (write)
- `get_social_dashboard` — contact frequency, connection quality
- `log_temptation` — resist/succumb logging (write)
- `get_temptation_trend` — resist rate, triggers

**Miscellaneous (2)**
- `get_adaptive_mode` — brief mode + engagement score
- `get_pillar_detail` — (already counted above)

---

### TIER 3 — Specialty (~35 tools)

Always registered, invoked for specific deep-dive analyses.

**Core Data Access (5)**
- `get_date_range` — time-series for any source
- `find_days` — threshold-based day finder
- `compare_periods` — side-by-side period comparison
- `get_aggregated_summary` — monthly/yearly averages
- `get_weekly_summary` — weekly training totals

**Garmin (2)**
- `get_garmin_summary` — Body Battery, HRV, stress
- `get_device_agreement` — Whoop vs Garmin cross-validation

**Nutrition Deep Dive (3)**
- `get_food_log` — per-meal entries
- `get_micronutrient_report` — ~25 micronutrients vs RDA
- `get_meal_timing` — eating window, circadian alignment

**Correlations (5)**
- `get_cross_source_correlation` — any two metric Pearson r
- `get_exercise_sleep_correlation` — exercise timing vs sleep
- `get_alcohol_sleep_correlation` — dose vs HRV/recovery
- `get_caffeine_sleep_correlation` — personal cutoff finder
- `get_nutrition_biometrics_correlation` — 10 nutrition × 9 outcome matrix

**Habits (4)**
- `get_keystone_habits` — habits most correlated with P40
- `get_habit_stacks` — co-occurrence analysis
- `get_habit_streaks` — streaks with days-since-last
- `compare_habit_periods` — side-by-side adherence comparison

**CGM (2)**
- `get_glucose_sleep_correlation` — glucose vs sleep quality
- `get_glucose_exercise_correlation` — exercise vs rest day glucose

**Gait & Movement (3)**
- `get_gait_analysis` — walking speed, asymmetry, composite
- `get_energy_balance` — Apple Watch TDEE vs intake
- `get_movement_score` — NEAT, step tracking, sedentary flags

**Labs (2)**
- `search_biomarker` — free-text biomarker search
- `get_next_lab_priorities` — recommended tests

**Strength Standards (1)**
- `get_strength_standards` — bodyweight-relative classification

**Travel (3)**
- `log_travel` — trip start/end (write)
- `get_travel_log` — all trips
- `get_jet_lag_recovery` — post-trip recovery analysis

**Blood Pressure (2)**
- `get_blood_pressure_dashboard` — BP status, AHA classification
- `get_blood_pressure_correlation` — BP vs lifestyle factors

**Social (3)**
- `log_life_event` — life event logging (write)
- `get_life_events` — retrieve events
- `get_exercise_variety` — Shannon diversity index

---

### TIER 4 — Removal/Merge Candidates (~44 tools)

SIMP-1 evaluation targets. Each needs usage data before final decision.
Rationale for preliminary T4 assignment noted.

| Tool | Current Category | Removal Rationale |
|------|-----------------|-------------------|
| `get_sources` | Core Data Access | Rarely used ad-hoc; replaced by knowing the system |
| `get_field_stats` | Core Data Access | `get_date_range` + `get_aggregated_summary` cover this |
| `get_seasonal_patterns` | Core Data Access | Low-frequency, `compare_periods` partially substitutes |
| `get_personal_records` | Core Data Access | Duplicate of `get_strength_prs` + other PRs; rarely invoked standalone |
| `get_zone2_breakdown` | Correlation | `get_training_load` covers Zone 2; standalone rarely needed |
| `get_group_trends` | Habits | `get_habit_tier_report` subsumes weekly trend view |
| `get_habit_health_correlations` | Habits | `get_cross_source_correlation` covers this more generically |
| `get_day_type_analysis` | Day Classification | Low unique value; `get_daily_summary` + `compare_periods` substitute |
| `get_cgm_dashboard` (demote?) | Blood Glucose | Debate: may stay T2 pending usage data |
| `get_state_of_mind_trend` | State of Mind | Partial duplicate of `get_mood_trend`; data sparse |
| `get_board_of_directors` | Board Management | Not useful ad-hoc; board personas used internally by email Lambdas |
| `update_board_member` | Board Management | Admin tool; not ad-hoc |
| `remove_board_member` | Board Management | Admin tool; not ad-hoc |
| `update_character_config` | Character Sheet Phase 4 | Admin tool; not ad-hoc |
| `set_reward` | Character Sheet Phase 4 | Rarely changed; could be a one-time script |
| `get_rewards` | Character Sheet Phase 4 | Low frequency |
| `get_insights` | Coaching Log | `read_platform_memory` with category=insight covers this |
| `update_insight_outcome` | Coaching Log | Rarely used; insights workflow not well adopted |
| `get_supplement_log` | Supplements | Low unique value; `get_daily_summary` includes supplements |
| `log_supplement` | Supplements | Low frequency; could use `write_platform_memory` instead |
| `get_hydration_score` | Hydration | Data often sparse; `get_daily_summary` includes hydration |
| `get_sick_days` | Sick Days | Rarely needed ad-hoc |
| `log_sick_day` | Sick Days | Rarely needed |
| `clear_sick_day` | Sick Days | Admin tool |
| `log_exposure` | Social & Behavioral | Low frequency |
| `get_exposure_log` | Social & Behavioral | Low frequency |
| `get_exposure_correlation` | Social & Behavioral | Rarely invoked |
| `get_vice_streak_history` | Vice Tracking | Low frequency; `get_temptation_trend` covers it |
| `delete_platform_memory` | Platform Memory | Admin tool; not ad-hoc |
| `list_memory_categories` | Platform Memory | Admin tool; `read_platform_memory` more useful |
| `get_todoist_day` | Todoist | `get_task_load_summary` + `list_todoist_tasks` substitute |
| `get_todoist_projects` | Todoist | Rarely needed standalone |
| `get_project_activity` | Todoist | Low frequency |
| `get_task_completion_trend` | Todoist | `get_task_load_summary` covers trend; standalone rarely needed |
| `get_decision_fatigue_signal` | Todoist | IC-specific; partially subsumed by `get_adaptive_mode` |
| `delete_todoist_task` | Todoist | Rarely used; close_todoist_task more common |
| `get_training_recommendation` | Training | Partially covered by `get_readiness_score` + `get_training_load` |
| `get_training_periodization` | Training | Low frequency; advanced feature |
| `get_social_connection_trend` | Social | Low frequency; `get_social_dashboard` covers it |
| `get_hr_recovery_trend` | Garmin | `get_garmin_summary` covers HRR |
| `get_exercise_efficiency_trend` | Garmin | Very narrow; low frequency |
| `get_lactate_threshold_estimate` | Garmin | Very narrow; advanced feature |
| `get_hypotheses` | Hypothesis Engine | (May promote to T2 based on usage) |
| `get_fasting_glucose_validation` | CGM | Very narrow clinical tool |

**Total T4:** ~44. Final decisions require SIMP-1 usage data.

---

## 4. Implementation Mechanism

### Option A: Metadata in TOOLS dict (recommended)
Add a `"tier"` field to each tool's registration dict in `mcp/registry.py`:

```python
TOOLS = {
    "get_health_dashboard": {
        "description": "...",
        "input_schema": {...},
        "tier": 1,  # ← NEW
    },
    ...
}
```

`mcp/handler.py` advertises only tools where `tier <= ACTIVE_TIER_THRESHOLD`. Default threshold = 3 (all T1–T3 active). During SIMP-1, set to 2 temporarily to test reduced surface.

Benefits: simple, backward compatible, no config file dependency, easy to query.

### Option B: External config file
Store tier assignments in `s3://matthew-life-platform/config/tool_tiers.json`. Hot-reloadable without Lambda redeploy.

Benefits: change tiers without code deployment.
Drawbacks: adds S3 read on cold start; more moving parts.

**Recommendation: Option A.** Tier changes are infrequent; a Lambda deploy is acceptable. Simpler.

### Implementation steps (SIMP-1 session):
1. Add `"tier": N` to all 144 tool entries in `mcp/registry.py`
2. Add `ACTIVE_TIER_THRESHOLD = int(os.environ.get("MCP_TIER_THRESHOLD", "3"))` to `mcp/config.py`
3. Modify `mcp/handler.py` tool listing to filter by tier
4. Verify T4 removals don't break any downstream consumers (daily-brief, email lambdas)
5. CDK: add `MCP_TIER_THRESHOLD` env var to MCP Lambda (default 3)

---

## 5. SIMP-1 Data Collection Requirements

Before finalizing T4 removals, collect 6 weeks of actual usage data (2026-03-13 → ~2026-04-24).

### Instrumentation (add now, before SIMP-1):
In `mcp/handler.py`, after tool dispatch, emit a CloudWatch metric:

```python
import boto3
cw = boto3.client("cloudwatch", region_name="us-west-2")
cw.put_metric_data(
    Namespace="LifePlatform/MCP",
    MetricData=[{
        "MetricName": "ToolInvocation",
        "Dimensions": [{"Name": "ToolName", "Value": tool_name}],
        "Value": 1,
        "Unit": "Count",
    }]
)
```

Or use CloudWatch Embedded Metric Format (EMF) via `platform_logger.py` — lower latency, batched.

### Decision rules for SIMP-1:
- **T4 with 0 invocations** in 6 weeks → remove
- **T4 with <3 invocations** → remove (consider stub/manual script)
- **T4 with ≥10 invocations** → promote to T3
- **T3 with 0 invocations** → demote to T4 candidate
- **T1/T2 with 0 invocations** → flag for review (may have wrong tier; do not auto-remove)

---

## 6. Known Dependencies to Check Before Removal

Before removing any tool, verify it is not:

1. Called by a Lambda (grep `lambdas/` for tool name)
2. Referenced in `ai_calls.py` prompt templates
3. Used in the Daily Brief, Weekly Digest, or any email Lambda output generation
4. Mentioned in USER_GUIDE.md examples (update docs if removing)

Tools with non-MCP consumers (internal Lambda calls):
- `get_health_dashboard` — Daily Brief calls this via MCP
- `get_habit_dashboard` — Daily Brief
- `get_readiness_score` — Anomaly detector, Daily Brief
- `get_movement_score` — Dashboard Refresh

These must stay T1 regardless of ad-hoc invocation frequency.

---

## 7. SIMP-1 Session Plan (~2026-04-08, ~4 hours)

1. **Review 6-week usage data** from CloudWatch `LifePlatform/MCP` namespace
2. **Validate T4 list** against usage data — adjust tier assignments
3. **Add `tier` field** to all 144 tool entries in `mcp/registry.py`
4. **Update `handler.py`** to filter by tier threshold
5. **Remove T4 tools** whose function implementations can be deleted
6. **For merged tools**: consolidate and update MCP_TOOL_CATALOG.md
7. **CDK**: update MCP Lambda env var, deploy McpStack
8. **Smoke test**: verify T1/T2/T3 tools all respond correctly
9. **Update docs**: MCP_TOOL_CATALOG.md, ARCHITECTURE.md (tool count), USER_GUIDE.md

Target: 144 → ~100 tools (-44), all T1–T3.
