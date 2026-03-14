# SIMP-1: MCP Tool Consolidation Plan

> Design document for reducing MCP tools from 116 to ≤80.
> Source: Architecture Review #8, Finding-5 (prompt pressure + context window consumption).
> Status: **Planning complete. Execution gated on 30-day EMF data (~2026-04-13).**

---

## Problem Statement

116 tools × ~100-200 tokens per schema = 12,000-23,000 tokens consumed before any conversation starts. This degrades tool selection quality (Claude must distinguish 116 similar names from descriptions alone) and compresses available context for data, history, and reasoning.

---

## Current Tool Inventory by Domain (114 counted)

| Domain | Count | Tools |
|--------|-------|-------|
| IC-Intelligence | 15 | get_adaptive_mode, get_board_of_directors, get_decision_fatigue_signal, get_decisions, get_genome_insights, get_insights, get_social_dashboard, list_memory_categories, log_decision, read_platform_memory, save_insight, update_decision_outcome, update_insight_outcome, write_platform_memory, delete_platform_memory |
| Lifestyle | 14 | get_body_composition_trend, get_jet_lag_recovery, get_life_events, get_mood_trend, get_rewards, get_sick_days, get_state_of_mind_trend, get_temptation_trend, get_travel_log, log_life_event, log_sick_day, clear_sick_day, log_temptation, log_travel, set_reward |
| Habits | 10 | get_habit_adherence, get_habit_dashboard, get_habit_registry, get_habit_stacks, get_habit_streaks, get_habit_tier_report, get_group_trends, get_keystone_habits, get_vice_streak_history, compare_habit_periods |
| Todoist | 9 | get_todoist_day, get_todoist_projects, list_todoist_tasks, create_todoist_task, close_todoist_task, delete_todoist_task, update_todoist_task, get_task_completion_trend, get_task_load_summary |
| Data-General | 9 | get_aggregated_summary, get_daily_summary, get_date_range, get_field_stats, get_latest, get_personal_records, get_seasonal_patterns, get_sources, get_weekly_summary, compare_periods, find_days, get_cross_source_correlation |
| Health | 8 | get_health_dashboard, get_health_risk_profile, get_health_trajectory, get_readiness_score, get_movement_score, get_energy_expenditure, get_hydration_score, get_hr_recovery_trend |
| Training | 7 | get_training_load, get_training_periodization, get_training_recommendation, get_exercise_history, get_exercise_efficiency_trend, get_lactate_threshold_estimate, get_workout_frequency |
| Nutrition | 6 | get_nutrition_summary, get_food_log, get_macro_targets, get_meal_timing, get_micronutrient_report, get_glucose_meal_response |
| IC-Experiments | 5 | create_experiment, end_experiment, get_experiment_results, list_experiments, update_hypothesis_outcome |
| Character | 4 | get_character_sheet, get_pillar_detail, get_level_history, update_character_config |
| Labs | 4 | get_lab_results, get_lab_trends, get_out_of_range_history, search_biomarker |
| Strength | 4 | get_strength_progress, get_strength_prs, get_strength_standards, get_muscle_volume |
| Journal | 3 | get_journal_entries, get_journal_insights, search_journal |
| CGM | 2 | get_cgm_dashboard, get_fasting_glucose_validation |
| Social | 2 | get_social_connection_trend, log_interaction |
| Supplement | 2 | get_supplement_log, log_supplement |
| Sleep | 1 | get_sleep_analysis |
| BP | 1 | get_blood_pressure_dashboard |
| Other | 4 | get_hypotheses, get_project_activity, get_weight_loss_progress, search_activities |

---

## Consolidation Strategy

**Pattern:** Merge read-only tools that query the same domain into a single tool with a `view` parameter. Write tools stay separate (different input schemas). CRUD tools stay separate.

**Pre-compute dependency:** Some consolidations are unlocked by the composite scores pre-compute (R8-ST5). Tools that read pre-computed data become simpler or unnecessary.

---

## Proposed Consolidation Map

### Phase 1: Read-only merges (no pre-compute needed)

| Current Tools | → New Tool | Reduction | Confidence |
|--------------|-----------|-----------|------------|
| get_habit_dashboard, get_habit_adherence, get_habit_streaks, get_habit_tier_report, get_habit_stacks, get_keystone_habits | `get_habits(view: dashboard\|adherence\|streaks\|tiers\|stacks\|keystones)` | **-5** | High |
| get_daily_summary, get_latest | `get_daily_snapshot(date?)` | **-1** | High |
| get_aggregated_summary, get_seasonal_patterns, get_personal_records | `get_longitudinal_summary(view: aggregate\|seasonal\|records)` | **-2** | High |
| get_health_dashboard, get_health_risk_profile, get_health_trajectory | `get_health(view: dashboard\|risk_profile\|trajectory)` | **-2** | High |
| get_nutrition_summary, get_macro_targets, get_meal_timing, get_micronutrient_report | `get_nutrition(view: summary\|macros\|meal_timing\|micronutrients)` | **-3** | High |
| get_lab_results, get_lab_trends, get_out_of_range_history | `get_labs(view: results\|trends\|out_of_range)` | **-2** | High |
| get_training_load, get_training_periodization, get_training_recommendation | `get_training(view: load\|periodization\|recommendation)` | **-2** | High |
| get_strength_progress, get_strength_prs, get_strength_standards | `get_strength(view: progress\|prs\|standards)` | **-2** | High |
| get_character_sheet, get_pillar_detail, get_level_history | `get_character(view: sheet\|pillar\|history)` | **-2** | High |
| get_cgm_dashboard, get_fasting_glucose_validation | `get_cgm(view: dashboard\|fasting)` | **-1** | High |
| get_mood_trend, get_state_of_mind_trend | `get_mood(view: trend\|state_of_mind)` | **-1** | Medium |
| get_movement_score, get_energy_expenditure, get_hydration_score | `get_daily_metrics(view: movement\|energy\|hydration)` | **-2** | Medium |
| get_todoist_day, get_task_load_summary | `get_todoist_snapshot(view: today\|load)` | **-1** | Medium |
| get_sick_days, log_sick_day, clear_sick_day | `manage_sick_days(action: list\|log\|clear)` | **-2** | Medium |

**Phase 1 total: -28 tools (116 → 88)**

### Phase 2: EMF-data-driven cuts (after 30-day analysis)

Wait for EMF invocation data. Tools with 0 invocations in 30 days are candidates for removal or merge. Expected candidates (speculative — verify with data):

| Likely low-use | Rationale | Action |
|---------------|-----------|--------|
| get_group_trends | Overlaps with get_habits | Merge into get_habits |
| compare_habit_periods | Niche use case | Keep but consider merge |
| get_exercise_efficiency_trend | Advanced analysis | Keep |
| get_lactate_threshold_estimate | Advanced analysis | Keep |
| get_workout_frequency | May overlap with training_load | Verify with EMF |
| get_muscle_volume | Niche | Verify with EMF |
| get_field_stats | Power-user tool | Verify with EMF |
| get_cross_source_correlation | Power-user tool | Verify with EMF |
| get_weekly_summary | May overlap with aggregated_summary | Verify with EMF |
| list_memory_categories | Admin tool | Verify with EMF |
| get_decision_fatigue_signal | Experimental IC feature | Verify with EMF |

**Phase 2 estimated: -5 to -10 tools (88 → 78-83)**

### Phase 3: Pre-compute unlocks (after composite scores built)

When `SOURCE#composite_scores` partition exists with nightly pre-computed data:

| Current | → Replaced by | Reduction |
|---------|-------------|-----------|
| get_readiness_score (live compute) | Read from composite partition | Tool stays, compute eliminated |
| get_health_dashboard (live compute) | Read from composite partition | Tool stays, compute eliminated |
| get_habit_dashboard (live compute) | Read from composite partition | Tool stays, compute eliminated |

Phase 3 doesn't reduce tool count but makes remaining tools faster and simpler.

---

## Target State

| Metric | Current | Phase 1 | Phase 2 | Final |
|--------|---------|---------|---------|-------|
| Tool count | 116 | ~88 | ~80 | **≤80** |
| Context tokens | ~17,000 | ~13,000 | ~12,000 | **<12,000** |
| Modules | 31 | ~25 | ~22 | **≤25** |

---

## Implementation Rules

1. **Never remove a tool without checking EMF data first** (Phase 2). EMF data starts producing signal after ~2026-04-13.
2. **View-parameter tools must support all previous tool names as aliases** during transition. `tools/list` returns the new names; old names produce a deprecation notice in the response.
3. **Update cache warmer** when tools are merged — warmer must call new tool names.
4. **Daily Brief reads pre-computed data** — merging tools that the Daily Brief calls requires testing the brief end-to-end.
5. **Run `python3 -m pytest tests/test_mcp_registry.py -v`** after every merge.
6. **One merge per commit** — if something breaks, rollback is one commit.

---

## Execution Timeline

| When | What | Gate |
|------|------|------|
| Now | Plan documented (this file) | — |
| ~2026-04-13 | EMF 30-day data ready. Run SIMP-1 analysis script. | COST-2 data |
| Session 1 | Phase 1a: Habits cluster (10→4, -6 tools) | — |
| Session 2 | Phase 1b: Data + Health + Nutrition clusters (-7 tools) | — |
| Session 3 | Phase 1c: Training + Strength + Labs + Character + CGM (-9 tools) | — |
| Session 4 | Phase 1d: Lifestyle + Todoist merges (-6 tools) | — |
| Session 5 | Phase 2: EMF-driven cuts + cleanup | EMF analysis |
| Post-SIMP-1 | Architecture Review #9 | — |

---

*Created: 2026-03-13 (Architecture Review #8, Finding-5)*
