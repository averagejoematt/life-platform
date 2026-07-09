# MCP Tool Audit Ledger — the AUDITED_AT ratchet

Dated, reviewable record of every batch of MCP registry removals (issue #395, epic #345
"Less machine, same power", finding ER-04). Nothing disappears from the registry without
an entry here citing the usage telemetry that justified it. Git history is the archive —
every deleted function is recoverable from the commit referenced by each batch.

Companion ratchet: `tests/test_mcp_orphan_tools.py` (`AUDITED_AT`, orphan count, now 0)
and `tests/test_mcp_registry.py` (`EXPECTED_MIN/MAX_TOOLS`, now 50–70).

## Ratchet history

| AUDITED_AT | Registered tools | `tool_` orphans | Event |
|---|---|---|---|
| 2026-05-16 | 116 | 70 | Allowlist born (Phase 4.8) |
| 2026-05-17 | 116 | 64 | V2 P4.1 — tools_calendar.py deleted (ADR-030) |
| **2026-07-08** | **143 → 60** | **64 → 0** | **#395 ER-04 prune — this record** |
| 2026-07-08 | 60 → 62 | 0 | #422 addition — `get_habit_reflection_queue` + `log_habit_reflection` (habit causality reflection loop, `mcp/tools_habits.py`). Deliberate add, not drift; within the 50–70 band. |

---

## AUDITED_AT 2026-07-08 — the ER-04 prune (#395)

### Telemetry snapshot (the evidence every decision below cites)

- **Source:** CloudWatch metrics, namespace `LifePlatform/MCP`, metric `ToolInvocations`,
  dimension `ToolName` — emitted per dispatch by `mcp/handler.py::_emit_tool_metric` (EMF, COST-2).
- **Window:** 2026-06-08 → 2026-07-08 UTC (trailing 30 days), period=30d, statistic=Sum.
- **Account/region:** 205930651321 / us-west-2. Snapshot taken 2026-07-08.
- **Result:** 31 of 143 registered tools served at least one request. All 31 are kept —
  **no tool with a request in the window was removed.**

```json
{
 "window_utc": {
  "start": "2026-06-08",
  "end": "2026-07-08"
 },
 "namespace": "LifePlatform/MCP",
 "metric": "ToolInvocations",
 "tools_registered_at_snapshot": 143,
 "tools_invoked": 31,
 "invocations_by_tool": {
  "get_weight_loss_progress": 194,
  "get_sources": 102,
  "get_todoist_snapshot": 102,
  "manage_hevy_routine": 58,
  "get_workout_detail": 20,
  "get_readiness_score": 19,
  "get_workouts": 18,
  "get_coach_thread": 17,
  "get_mood": 13,
  "save_insight": 13,
  "get_deficit_sustainability": 12,
  "get_freshness_status": 12,
  "get_acwr_status": 11,
  "get_muscle_volume": 10,
  "get_nutrition": 10,
  "manage_reading": 10,
  "search_activities": 6,
  "get_daily_metrics": 3,
  "get_training": 3,
  "log_decision": 3,
  "get_coach_track_record": 2,
  "get_predictions": 2,
  "get_zone2_breakdown": 2,
  "create_experiment": 1,
  "find_days": 1,
  "get_constellation": 1,
  "get_intelligence_quality": 1,
  "get_reading_shelf": 1,
  "get_social_connection_trend": 1,
  "get_social_dashboard": 1,
  "list_experiments": 1
 }
}
```

Every registered tool NOT in the table above recorded **zero** invocations in the window
(no `ToolName` dimension value exists for it at all in the namespace).

### Keep set — 60 tools

**31 used in window (hard keep):**

`create_experiment`, `find_days`, `get_acwr_status`, `get_coach_thread`, `get_coach_track_record`, `get_constellation`, `get_daily_metrics`, `get_deficit_sustainability`, `get_freshness_status`, `get_intelligence_quality`, `get_mood`, `get_muscle_volume`, `get_nutrition`, `get_predictions`, `get_readiness_score`, `get_reading_shelf`, `get_social_connection_trend`, `get_social_dashboard`, `get_sources`, `get_todoist_snapshot`, `get_training`, `get_weight_loss_progress`, `get_workout_detail`, `get_workouts`, `get_zone2_breakdown`, `list_experiments`, `log_decision`, `manage_hevy_routine`, `manage_reading`, `save_insight`, `search_activities`

**29 kept-anyway (each with its reason):**

| Tool | Reason kept despite 0 invocations |
|---|---|
| `list_available_tools` | meta/plumbing — the tool-discovery surface itself |
| `get_date_range` | core data-access primitive — the only generic per-source time-series read |
| `get_daily_snapshot` | core data-access primitive — the only all-sources single-day read |
| `get_decisions` | read pair of used log_decision (decision-journal loop) |
| `update_decision_outcome` | lifecycle pair of used log_decision |
| `get_experiment_results` | lifecycle of used create_experiment/list_experiments (pre-registered experiment live) |
| `end_experiment` | lifecycle of used create_experiment |
| `get_insights` | read pair of used save_insight |
| `update_insight_outcome` | lifecycle pair of used save_insight |
| `evaluate_prediction` | lifecycle pair of used get_predictions (R21 prediction-integrity program active) |
| `write_platform_memory` | cross-session memory plumbing |
| `read_platform_memory` | cross-session memory plumbing |
| `list_memory_categories` | cross-session memory plumbing |
| `delete_platform_memory` | cross-session memory plumbing (hygiene path of the CRUD set) |
| `get_reading_recommendation` | ADR-097 Mind domain shipped 2026-06-30 — window under-covers (8 of 30 days) |
| `get_reading_profile` | ADR-097 shipped 2026-06-30 — window under-covers |
| `get_reading_history` | ADR-097 shipped 2026-06-30 — window under-covers |
| `get_due_recalls` | ADR-097 recall loop — shipped 2026-06-30, window under-covers |
| `get_reading_track_record` | ADR-097 shipped 2026-06-30 — window under-covers |
| `create_todoist_task` | write path beside heavily-used get_todoist_snapshot (102 invocations) |
| `update_todoist_task` | write path beside used get_todoist_snapshot |
| `close_todoist_task` | write path beside used get_todoist_snapshot |
| `get_exercise_notes` | shipped 2026-06-21 (window under-covers) — designed as standard pre-flight pull beside used hevy tools |
| `get_benchmark` | BENCH-1/ADR-089 (2026-06-19) — episodic by design; also gates via internal metabolic-adaptation signal |
| `manage_sick_days` | episodic write — the sole sick-day logging path; 30d without illness is expected, not evidence of death |
| `get_labs` | labs are quarterly-episodic; no lab draw fell inside the window |
| `get_cgm` | CGM sensor is worn episodically; sole CGM read surface |
| `get_field_notes` | field-notes program live; #533 interaction write-back shipped 2026-07-05 — window under-covers |
| `log_field_note_response` | #533 field-note→coach write-back shipped 2026-07-05 — the write path of a 3-day-old live program |

### Batch 1 — the 64-entry KNOWN_ORPHANS allowlist resolved (allowlist now EMPTY)

**22 renamed to underscore-named view implementations** (live code behind a
registered dispatcher; the `tool_` prefix now unambiguously means MCP-callable):

| Was | Now | Why it lives |
|---|---|---|
| `tool_get_cgm_dashboard` | `_get_cgm_dashboard` | view of kept get_cgm |
| `tool_get_fasting_glucose_validation` | `_get_fasting_glucose_validation` | view of kept get_cgm |
| `tool_get_daily_summary` | `_get_daily_summary` | view of kept get_daily_snapshot |
| `tool_get_latest` | `_get_latest` | view of kept get_daily_snapshot |
| `tool_get_lab_results` | `_get_lab_results` | view of kept get_labs |
| `tool_get_lab_trends` | `_get_lab_trends` | view of kept get_labs |
| `tool_get_out_of_range_history` | `_get_out_of_range_history` | view of kept get_labs |
| `tool_get_nutrition_summary` | `_get_nutrition_summary` | view of kept get_nutrition (USED) |
| `tool_get_macro_targets` | `_get_macro_targets` | view of kept get_nutrition (USED) |
| `tool_get_meal_timing` | `_get_meal_timing` | view of kept get_nutrition (USED) |
| `tool_get_micronutrient_report` | `_get_micronutrient_report` | view of kept get_nutrition (USED) |
| `tool_get_training_load` | `_get_training_load` | view of kept get_training (USED); also called by get_readiness_score (USED) |
| `tool_get_training_periodization` | `_get_training_periodization` | view of kept get_training (USED) |
| `tool_get_training_recommendation` | `_get_training_recommendation` | view of kept get_training (USED) |
| `tool_get_mood_trend` | `_get_mood_trend` | view of kept get_mood (USED) |
| `tool_get_state_of_mind_trend` | `_get_state_of_mind_trend` | view of kept get_mood (USED) |
| `tool_get_sick_days` | `_get_sick_days` | view of kept manage_sick_days |
| `tool_log_sick_day` | `_log_sick_day` | view of kept manage_sick_days |
| `tool_clear_sick_day` | `_clear_sick_day` | view of kept manage_sick_days |
| `tool_get_movement_score` | `_get_movement_score` | view of kept get_daily_metrics (USED) |
| `tool_get_energy_expenditure` | `_get_energy_expenditure` | view of kept get_daily_metrics (USED) |
| `tool_get_hydration_score` | `_get_hydration_score` | view of kept get_daily_metrics (USED) |

**42 deleted** (defined, never registered, unreachable from any kept tool;
cited telemetry: their would-be dispatchers also recorded 0 invocations):

`tool_get_aggregated_summary`, `tool_get_alcohol_sleep_correlation`, `tool_get_blood_pressure_correlation`, `tool_get_body_composition_snapshot`, `tool_get_caffeine_sleep_correlation`, `tool_get_character_sheet`, `tool_get_day_type_analysis`, `tool_get_energy_balance`, `tool_get_exercise_sleep_correlation`, `tool_get_exercise_variety`, `tool_get_exposure_correlation`, `tool_get_exposure_log`, `tool_get_gait_analysis`, `tool_get_glucose_exercise_correlation`, `tool_get_glucose_sleep_correlation`, `tool_get_group_trends`, `tool_get_habit_adherence`, `tool_get_habit_dashboard`, `tool_get_habit_health_correlations`, `tool_get_habit_stacks`, `tool_get_habit_streaks`, `tool_get_health_dashboard`, `tool_get_health_risk_profile`, `tool_get_health_trajectory`, `tool_get_journal_correlations`, `tool_get_keystone_habits`, `tool_get_level_history`, `tool_get_meditation_correlation`, `tool_get_next_lab_priorities`, `tool_get_non_scale_victories`, `tool_get_nutrition_biometrics_correlation`, `tool_get_personal_records`, `tool_get_pillar_detail`, `tool_get_ruck_log`, `tool_get_seasonal_patterns`, `tool_get_social_isolation_risk`, `tool_get_supplement_correlation`, `tool_get_weather_correlation`, `tool_log_exposure`, `tool_log_ruck`, `tool_remove_board_member`, `tool_update_board_member`

Also deleted, same rationale (imported by the registry but never registered, so they never
appeared on the orphan list): `tool_get_habit_tier_report`, `tool_get_strength_progress`,
`tool_get_strength_prs`, `tool_get_strength_standards`.

### Batch 2 — 83 registered-but-unused tools removed (0 invocations in window, each)

`activate_challenge`, `annotate_discovery`, `capture_baseline`, `checkin_challenge`, `compare_habit_periods`, `compare_periods`, `complete_action`, `complete_challenge`, `create_challenge`, `create_protocol`, `delete_todoist_task`, `get_adaptive_mode`, `get_allergies`, `get_autonomic_balance`, `get_blood_pressure_dashboard`, `get_board_of_directors`, `get_body_composition_trend`, `get_centenarian_benchmarks`, `get_character`, `get_coach_disagreements`, `get_coaching_summary`, `get_cross_source_correlation`, `get_decision_fatigue_signal`, `get_device_agreement`, `get_discovery_annotations`, `get_essential_seven`, `get_exercise_efficiency_trend`, `get_exercise_history`, `get_field_stats`, `get_food_delivery`, `get_food_log`, `get_garmin_summary`, `get_genome_insights`, `get_glucose_meal_response`, `get_habit_registry`, `get_habits`, `get_health`, `get_hr_recovery_trend`, `get_hypotheses`, `get_jet_lag_recovery`, `get_journal_entries`, `get_journal_insights`, `get_journal_sentiment_trajectory`, `get_lab_deltas`, `get_lactate_threshold_estimate`, `get_life_events`, `get_longitudinal_summary`, `get_measurement_trends`, `get_measurements`, `get_metabolic_adaptation`, `get_project_activity`, `get_rewards`, `get_sleep_analysis`, `get_strength`, `get_supplement_log`, `get_task_completion_trend`, `get_temptation_trend`, `get_todoist_projects`, `get_travel_log`, `get_vacation_fund`, `get_vice_streak_history`, `get_vice_streaks`, `get_weekly_summary`, `get_workout_frequency`, `get_workout_source_status`, `list_actions`, `list_challenges`, `list_protocols`, `list_todoist_tasks`, `log_interaction`, `log_ledger_entry`, `log_life_event`, `log_supplement`, `log_temptation`, `log_travel`, `manage_meals`, `retire_protocol`, `search_biomarker`, `search_journal`, `set_reward`, `update_character_config`, `update_hypothesis_outcome`, `update_protocol`

Function bodies were deleted with the registrations. Ten modules emptied entirely and were
removed: `tools_adaptive`, `tools_board`, `tools_challenges`, `tools_character`,
`tools_food_delivery`, `tools_habits`, `tools_hypotheses`, `tools_measurements`,
`tools_protocols`, `tools_vacation`; plus `tools_meals` and `tools_sleep`.

Notes:
- `get_metabolic_adaptation` was removed as a tool but its implementation survives as
  `tools_nutrition._get_metabolic_adaptation` — kept `get_benchmark` consults it as a gate signal.
- `mcp/warmer.py` was trimmed to the surviving surface (training views + CGM dashboard).
- `delete_todoist_task` and `log_supplement` were removed from `_RATE_LIMITED_TOOLS` in
  `mcp/handler.py` (their tools no longer exist).
- Tests covering deleted tools went with them (`test_training_trend_regression.py`,
  trimmed sections of `test_business_logic.py`, `test_journal_signal_wiring.py`,
  `test_todoist_filters.py`, `test_health_window_guards.py`). `test_di1_movement_integrity.py`
  survives against the renamed `_get_movement_score` view.

### Judgment risks flagged (reversal is one `git revert` + re-register away)

- `get_sleep_analysis` removed — sleep is a core domain, but the tool logged 0 invocations in a
  fully-covered window; sleep questions are served by `get_daily_metrics`, `get_readiness_score`,
  and `get_date_range(source=whoop|eightsleep)`.
- `get_character`, `get_board_of_directors`, challenges, hypotheses, protocols: all site/email-served
  features whose MCP read surfaces went unused; engine and site are untouched.

## How to remove a tool after this record

1. Snapshot the trailing-30d `LifePlatform/MCP` ToolInvocations telemetry (as above).
2. Add a dated `AUDITED_AT` section here: telemetry, the removal list, each keep-anyway reason.
3. Delete registrations AND function bodies; keep `tests/test_mcp_orphan_tools.py` at zero orphans.
4. Update `EXPECTED_MIN/MAX_TOOLS` consciously and run `deploy/sync_doc_metadata.py --apply`.

