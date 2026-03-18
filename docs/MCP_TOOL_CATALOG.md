# Life Platform — MCP Tool Catalog

**Version:** v3.7.72 | **Last updated:** 2026-03-18 | **Total tools:** 95

> SIMP-1 Phase 1 complete (v3.7.17–19): 116 → 86 tools via 13 view-dispatchers. ADR-030 (v3.7.46): `get_calendar_events` + `get_schedule_load` retired (Google Calendar integration blocked by IT policy). 88 → 87 tools.
> Many previously standalone tools are now `view=` parameters of a parent dispatcher.
> For usage examples and natural language queries, see USER_GUIDE.md.

---

## What Changed in SIMP-1 Phase 1

| Old Tools (removed) | New Dispatcher | Views |
|---------------------|---------------|-------|
| get_latest, get_daily_summary | **get_daily_snapshot** | latest, summary |
| get_aggregated_summary, get_seasonal_patterns, get_personal_records | **get_longitudinal_summary** | aggregate, seasonal, records |
| get_health_dashboard, get_health_risk_profile, get_health_trajectory | **get_health** | dashboard, risk_profile, trajectory |
| get_nutrition_summary, get_macro_targets, get_meal_timing, get_micronutrient_report | **get_nutrition** | summary, macros, meal_timing, micronutrients |
| get_lab_results, get_lab_trends, get_out_of_range_history | **get_labs** | results, trends, out_of_range |
| get_training_load, get_training_periodization, get_training_recommendation | **get_training** | load, periodization, recommendation |
| get_strength_progress, get_strength_prs, get_strength_standards | **get_strength** | progress, prs, standards |
| get_character_sheet, get_pillar_detail, get_level_history | **get_character** | sheet, pillar, history |
| get_cgm_dashboard, get_fasting_glucose_validation | **get_cgm** | dashboard, fasting |
| get_mood_trend, get_state_of_mind_trend | **get_mood** | trend, state_of_mind |
| get_movement_score, get_energy_expenditure, get_hydration_score | **get_daily_metrics** | movement, energy, hydration |
| get_task_load_summary, get_todoist_day | **get_todoist_snapshot** | load, today |
| get_sick_days, log_sick_day, clear_sick_day | **manage_sick_days** | — (action= param) |

---

## Quick Reference — All 95 Tools

### Core Data Access
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_sources` | — | List all data sources and date ranges |
| `get_daily_snapshot` | view= (summary\|latest), date= | Daily data: all sources for a date (summary) or most recent per source (latest) |
| `get_date_range` | source, start_date, end_date | Time-series for one source |
| `find_days` | source, start_date, end_date, filters[] | Find days where metrics meet thresholds |
| `get_longitudinal_summary` | view= (aggregate\|seasonal\|records), source=, period= | Long-horizon data: aggregates, seasonal patterns, all-time PRs |
| `get_field_stats` | source, field | Min/max/avg, top-5 highs/lows, trend direction |
| `search_activities` | name_contains=, sport_type=, min_distance_miles= | Search Strava activities with percentile ranking |
| `compare_periods` | period_a_start, period_a_end, period_b_start, period_b_end | Side-by-side comparison of two date ranges |
| `get_weekly_summary` | start_date=, end_date=, sort_by= | Weekly training totals ranked by distance |
| `get_cross_source_correlation` | source_a, field_a, source_b, field_b, lag_days= | Pearson correlation between any two metrics |

### Health Intelligence (Dispatchers)
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_health` | view= (dashboard\|risk_profile\|trajectory), domain= | Unified health: morning briefing / CV+metabolic risk / forward projections. risk_profile and trajectory warmed nightly. |
| `get_autonomic_balance` | start_date=, end_date=, days= | BS-MP1: 4-quadrant ANS model (Flow/Stress/Recovery/Burnout). Balance score 0-100, 7d trend, state transitions |
| `get_daily_metrics` | view= (movement\|energy\|hydration), step_target= | Daily activity: NEAT/steps / calorie balance / water intake |
| `get_labs` | view= (results\|trends\|out_of_range), biomarker=, category= | Lab intelligence: draws / trajectory / chronic flags |
| `get_training` | view= (load\|periodization\|recommendation), weeks= | Training intelligence: CTL/ATL/TSB / mesocycle analysis / today's workout. All warmed nightly. |
| `get_cgm` | view= (dashboard\|fasting), days= | CGM: time-in-range + variability / fasting glucose validation. Dashboard warmed nightly. |
| `get_mood` | view= (trend\|state_of_mind), days= | Mood intelligence: journal-derived scores / Apple Health HWF valence |
| `get_nutrition` | view= (summary\|macros\|meal_timing\|micronutrients), calorie_target=, protein_target= | Nutrition intelligence: macro breakdown / adherence / eating window / RDA scoring |
| `get_deficit_sustainability` | start_date=, end_date=, days= | BS-12: 5-channel deficit early warning (HRV, sleep, recovery, habits, training). 3+ degradations → flag |
| `get_metabolic_adaptation` | start_date=, end_date=, weeks= | IC-29: TDEE divergence tracker. Expected vs actual weight loss, adaptation ratio, diet break recs |

### Weight & Body Composition
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_weight_loss_progress` | start_date=, end_date= | Weekly rate, BMI milestones, plateau detection, goal date |
| `get_body_composition_trend` | start_date=, end_date= | Fat vs lean mass, 14-day rolling deltas |
| `get_non_scale_victories` | end_date= | Fitness improvements independent of scale |

### Strength Training
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_strength` | view= (progress\|prs\|standards), exercise=, muscle_group= | Strength intelligence: volume trends / PR leaderboard / bodyweight-relative levels |
| `get_exercise_history` | exercise_name, start_date=, end_date= | Deep dive on a single exercise |
| `get_muscle_volume` | start_date=, end_date= | Weekly sets per muscle group vs MEV/MAV/MRV |
| `get_workout_frequency` | start_date=, end_date= | Adherence, streaks, top exercises |

### Character Sheet
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_character` | view= (sheet\|pillar\|history), pillar=, days= | Character Sheet: level + pillar scores / pillar deep-dive / level-up timeline. Reads pre-computed DDB partition. Warmed nightly. |
| `set_reward` | title, condition_type | Create reward milestone tied to Character Sheet progress |
| `get_rewards` | status= | View reward milestones |
| `update_character_config` | action | View or update Character Sheet configuration |

### Sleep
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_sleep_analysis` | start_date=, end_date=, target_sleep_hours= | Clinical analysis: architecture %, WASO, circadian timing, debt |
| `get_sleep_environment_analysis` | start_date=, end_date=, days= | BS-SL1: Eight Sleep temp × Whoop staging. Temperature band analysis, optimal band detection, Pearson correlations |

### Habits
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_habit_adherence` | start_date=, end_date=, group= | Per-habit and per-group completion rates |
| `get_habit_streaks` | start_date=, end_date=, habit_name= | Current streak, longest streak |
| `get_keystone_habits` | start_date=, end_date= | Habits most correlated with P40 score |
| `get_habit_health_correlations` | health_source, health_field | Correlate habits against biometrics |
| `get_group_trends` | start_date=, end_date= | Weekly P40 group scores |
| `compare_habit_periods` | period_a_start, period_a_end, period_b_start, period_b_end | Side-by-side habit adherence |
| `get_habit_stacks` | start_date=, end_date= | Co-occurrence analysis |
| `get_habit_dashboard` | end_date= | Current-state P40 briefing. ⚡ warmed nightly |
| `get_habit_registry` | tier=, category= | Browse 65-habit registry with tiers, weights, synergy groups |
| `get_habit_tier_report` | start_date=, end_date= | Tier-weighted scoring: T0/T1/T2, synergy completion |
| `get_vice_streak_history` | start_date=, end_date= | Vice-free streak tracking |

### Sick Days
| Tool | Key Params | Description |
|------|-----------|-------------|
| `manage_sick_days` | action= (list\|log\|clear), date=, dates=[], reason= | Manage sick/rest day flags (suppresses streak breaks and anomaly noise) |

### Garmin Biometrics
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_garmin_summary` | start_date=, end_date= | Body Battery, stress, HRV, RHR, training load |
| `get_device_agreement` | start_date=, end_date= | Whoop vs Garmin HRV/RHR cross-validation |

### Labs & Genome
| Tool | Key Params | Description |
|------|-----------|-------------|
| `search_biomarker` | query | Free-text biomarker search across all draws |
| `get_genome_insights` | category=, risk_level=, gene= | 110 SNP interpretations |
| `get_body_composition_snapshot` | date= | DEXA: FFMI, visceral fat, BMD, posture. ⚡ warmed |
| `get_next_lab_priorities` | — | Recommended tests based on genetic risk |

### Blood Glucose / CGM
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_glucose_sleep_correlation` | start_date=, end_date= | Glucose buckets vs same-night sleep |
| `get_glucose_meal_response` | start_date=, end_date= | Postprandial analysis with letter grades |
| `get_glucose_exercise_correlation` | start_date=, end_date= | Exercise vs rest day glucose |

### Gait & Movement
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_gait_analysis` | start_date=, end_date= | Walking speed, step length, asymmetry. Composite 0-100 |
| `get_energy_balance` | start_date=, end_date= | Apple Watch TDEE vs MacroFactor intake |

### Correlation & Sleep Impact
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_exercise_sleep_correlation` | start_date=, end_date= | Exercise timing vs sleep quality |
| `get_zone2_breakdown` | start_date=, end_date=, weekly_target_minutes= | 5-zone HR distribution vs 150 min target |
| `get_alcohol_sleep_correlation` | start_date=, end_date= | Dose buckets vs HRV/recovery |

### Journal & Mood
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_journal_entries` | start_date=, end_date=, template= | Retrieve entries with AI-enriched fields |
| `search_journal` | query, start_date=, end_date= | Full-text search across all journal fields |
| `get_journal_insights` | start_date=, end_date= | Cross-entry patterns: themes, emotions, avoidance |
| `get_journal_sentiment_trajectory` | start_date=, end_date=, days= | BS-MP2: Mood/energy/stress regression, divergence detection, inflection points |
| `get_journal_correlations` | start_date=, end_date= | Journal mood/stress vs wearable data |

### Coaching Log / Insights
| Tool | Key Params | Description |
|------|-----------|-------------|
| `save_insight` | text, tags=, source= | Save new insight or hypothesis |
| `get_insights` | status_filter=, limit= | List open/acted/resolved insights |
| `update_insight_outcome` | insight_id, outcome_notes=, status= | Record outcome when acting on insight |

### Travel & Jet Lag
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_travel` | action | Start or end a trip with timezone offset |
| `get_travel_log` | status= | All trips with status |
| `get_jet_lag_recovery` | trip_id=, recovery_window_days= | Post-trip recovery analysis |

### Blood Pressure
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_blood_pressure_dashboard` | start_date=, end_date= | AHA classification, trends, morning vs evening |
| `get_blood_pressure_correlation` | start_date=, end_date= | BP vs 11 lifestyle factors |

### Day Classification
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_day_type_analysis` | start_date=, end_date= | Classify days rest/light/moderate/hard/race. ⚡ warmed |

### N=1 Experiments
| Tool | Key Params | Description |
|------|-----------|-------------|
| `create_experiment` | name, hypothesis | Start tracking a protocol change |
| `list_experiments` | status_filter= | View all experiments |
| `get_experiment_results` | experiment_id | Auto-compare 16 metrics before vs during |
| `end_experiment` | experiment_id, outcome_notes=, status= | Close experiment |

### Social & Behavioral
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_life_event` | title, type=, date= | Log structured life events |
| `get_life_events` | start_date=, end_date=, type=, person= | Retrieve life events with filters |
| `log_interaction` | person, type=, depth=, date= | Log social interactions |
| `get_social_dashboard` | start_date=, end_date= | Contact frequency, depth, Murthy threshold |
| `get_social_connection_trend` | start_date=, end_date= | Social connection quality trend |
| `get_social_isolation_risk` | — | Isolation risk signal |
| `log_temptation` | category, resisted | Log resist/succumb moments |
| `get_temptation_trend` | start_date=, end_date= | Resist rate, trigger patterns |
| `log_exposure` | type, date=, duration_min= | Log cold/heat exposure sessions |
| `get_exposure_log` | start_date=, end_date= | Exposure history and stats |
| `get_exposure_correlation` | start_date=, end_date= | Exposure vs HRV/sleep/recovery |

### Longevity & Metabolic Intelligence
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_biological_age` | draw_date= | Levine PhenoAge from 9 biomarkers |
| `get_metabolic_health_score` | start_date=, end_date= | Composite: CGM + labs + weight + BP |
| `get_food_response_database` | start_date=, end_date= | Personal food glycemic leaderboard |
| `get_defense_patterns` | start_date=, end_date= | Defense mechanism patterns from journal |
| `get_exercise_variety` | start_date=, end_date= | Shannon diversity index, staleness detection |
| `get_weather_correlation` | start_date=, end_date= | Weather vs health metrics |
| `get_lactate_threshold_estimate` | start_date=, end_date= | Aerobic threshold from cardiac efficiency |
| `get_exercise_efficiency_trend` | start_date=, end_date= | Pace-at-HR trend (fitness signal) |
| `get_hr_recovery_trend` | start_date=, end_date=, sport_type= | Post-exercise HR recovery trend |
| `get_hydration_score` | start_date=, end_date= | Note: also accessible via get_daily_metrics(view=hydration) |
| `get_meditation_correlation` | start_date=, end_date= | Meditation vs HRV/stress/recovery |

### Supplements
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_supplement` | name, dose, unit= | Log supplement or medication intake |
| `get_supplement_log` | start_date=, end_date= | Supplement history |
| `get_supplement_correlation` | supplement_name, start_date= | Supplement vs biometric outcomes |

### Board of Directors
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_board_of_directors` | member_id=, type=, feature= | View 13-member expert panel |
| `update_board_member` | member_id, updates | Add or update board member |
| `remove_board_member` | member_id | Deactivate or remove board member |

### Todoist
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_todoist_snapshot` | view= (load\|today), date=, days= | Task load snapshot or daily Todoist summary |
| `get_task_completion_trend` | start_date=, end_date= | Daily completed count + 7-day rolling avg |
| `get_project_activity` | days= | Completions by project, neglected domain detection |
| `get_decision_fatigue_signal` | days= | Task load × T0 habit compliance Pearson r |
| `list_todoist_tasks` | filter_str=, limit= | Active tasks with Todoist filter syntax |
| `get_todoist_projects` | — | All projects with IDs and names |
| `create_todoist_task` | content | Create task with optional due_string, priority |
| `update_todoist_task` | task_id | Update task |
| `close_todoist_task` | task_id | Mark task complete |
| `delete_todoist_task` | task_id | Permanently delete task |

### Platform Memory
| Tool | Key Params | Description |
|------|-----------|-------------|
| `write_platform_memory` | category, content | Store structured memory record |
| `read_platform_memory` | category, days=, limit= | Retrieve memory records |
| `list_memory_categories` | days= | List categories with record counts |
| `delete_platform_memory` | category, date | Delete a memory record |

### Decision Journal
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_decision` | decision, followed=, pillars= | Record platform-guided decision |
| `get_decisions` | days=, pillar= | Decisions with trust calibration stats |
| `update_decision_outcome` | sk, outcome_metric=, effectiveness= | Record outcome 1-3 days later |

### Adaptive Mode
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_adaptive_mode` | days= | Current brief mode (flourishing/standard/struggling) |

### Hypothesis Engine
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_hypotheses` | status=, domain=, days= | Weekly hypotheses from hypothesis-engine Lambda |
| `update_hypothesis_outcome` | sk, verdict, evidence_note= | Record confirming/refuting observation |

---

## Warmer Coverage (⚡ = nightly pre-compute)

13 warm steps run at 10:00 AM PT daily. All dispatch via the relevant tool function and cache to `CACHE#matthew` (26h TTL):

| Step | Cache Key | Warm Call |
|------|-----------|-----------|
| 1-2 | aggregated_summary_year_* | get_longitudinal_summary(view=aggregate, period=year) |
| 3-4 | aggregated_summary_month_* | get_longitudinal_summary(view=aggregate, period=month) |
| 5 | personal_records_all | get_longitudinal_summary(view=records) |
| 6 | seasonal_patterns_all | get_longitudinal_summary(view=seasonal) |
| 7 | health_dashboard_today | get_health(view=dashboard) |
| 8 | habit_dashboard_today | get_habit_dashboard() |
| 9 | health_risk_profile_today | get_health(view=risk_profile) |
| 10 | health_trajectory_today | get_health(view=trajectory) |
| 11 | training_load_today | get_training(view=load) |
| 12 | training_periodization_today | get_training(view=periodization) |
| 13 | training_recommendation_today | get_training(view=recommendation) |
| 14 | character_sheet_today | get_character(view=sheet) |
| 15 | cgm_dashboard_today | get_cgm(view=dashboard) |
