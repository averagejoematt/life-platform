# Life Platform — MCP Tool Catalog

**Version:** v4.4.0 | **Last updated:** 2026-03-30 | **Total tools:** 118

> SIMP-1 Phase 1 complete (v3.7.17–19): 116 → 86 tools via 13 view-dispatchers. ADR-030 (v3.7.46): `get_calendar_events` + `get_schedule_load` retired (Google Calendar integration blocked by IT policy).
> Many previously standalone tools are now `view=` parameters of a parent dispatcher.
> For architecture and schema details, see ARCHITECTURE.md and SCHEMA.md.

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
| get_habit_adherence, get_habit_streaks, get_keystone_habits, get_habit_stacks, get_habit_dashboard, get_habit_tier_report | **get_habits** | dashboard, adherence, streaks, tiers, stacks, keystones |

---

## Quick Reference — All 112 Tools

### Core Data Access
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_sources` | — | List all data sources and date ranges |
| `get_daily_snapshot` | view= (summary\|latest), date=, sources=[] | Daily data: all sources for a date (summary) or most recent per source (latest) |
| `get_date_range` | source, start_date, end_date | Time-series for one source |
| `find_days` | source, start_date, end_date, filters[] | Find days where metrics meet thresholds |
| `get_longitudinal_summary` | view= (aggregate\|seasonal\|records), source=, period= | Long-horizon data: aggregates, seasonal patterns, all-time PRs |
| `get_field_stats` | source, field, start_date=, end_date= | Min/max/avg, top-5 highs/lows, trend direction |
| `search_activities` | name_contains=, sport_type=, min_distance_miles=, min_elevation_gain_feet=, sort_by=, limit= | Search Strava activities with percentile ranking |
| `compare_periods` | period_a_start, period_a_end, period_b_start, period_b_end, period_a_label=, period_b_label=, source= | Side-by-side comparison of two date ranges |
| `get_weekly_summary` | start_date=, end_date=, sort_by=, limit=, sort_ascending= | Weekly training totals ranked by distance |
| `get_cross_source_correlation` | source_a, field_a, source_b, field_b, lag_days=, start_date=, end_date= | Pearson correlation between any two metrics |

### Health Intelligence (Dispatchers)
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_health` | view= (dashboard\|risk_profile\|trajectory), domain= | Unified health: morning briefing / CV+metabolic risk / forward projections. risk_profile and trajectory warmed nightly. |
| `get_readiness_score` | date= | Unified 0-100 readiness from Whoop recovery (35%), sleep (25%), HRV trend (20%), TSB (10%), Body Battery (10%). GREEN/YELLOW/RED signal. |
| `get_autonomic_balance` | start_date=, end_date=, days= | BS-MP1: 4-quadrant ANS model (Flow/Stress/Recovery/Burnout). Balance score 0-100, 7d trend, state transitions |
| `get_daily_metrics` | view= (movement\|energy\|hydration), start_date=, end_date=, step_target= | Daily activity: NEAT/steps / calorie balance / water intake |
| `get_labs` | view= (results\|trends\|out_of_range), biomarker=, category=, start_date=, end_date= | Lab intelligence: draws / trajectory / chronic flags |
| `get_training` | view= (load\|periodization\|recommendation), start_date=, end_date=, date=, weeks= | Training intelligence: CTL/ATL/TSB / mesocycle analysis / today's workout. All warmed nightly. |
| `get_acwr_status` | date=, days_back= | BS-09: Acute:Chronic Workload Ratio from Whoop strain. Safe zone 0.8–1.3. Gabbett thresholds. |
| `get_cgm` | view= (dashboard\|fasting), start_date=, end_date=, days= | CGM: time-in-range + variability / fasting glucose validation. Dashboard warmed nightly. |
| `get_mood` | view= (trend\|state_of_mind), start_date=, end_date=, days= | Mood intelligence: journal-derived scores / Apple Health HWF valence |
| `get_nutrition` | view= (summary\|macros\|meal_timing\|micronutrients), start_date=, end_date=, days=, calorie_target=, protein_target= | Nutrition intelligence: macro breakdown / adherence / eating window / RDA scoring |
| `get_food_log` | date= | Individual food entries logged on a specific date with per-item macros and daily totals |
| `get_deficit_sustainability` | start_date=, end_date=, days= | BS-12: 5-channel deficit early warning (HRV, sleep, recovery, habits, training). 3+ degradations → flag |
| `get_metabolic_adaptation` | start_date=, end_date=, weeks= | IC-29: TDEE divergence tracker. Expected vs actual weight loss, adaptation ratio, diet break recs |

### Weight & Body Composition
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_weight_loss_progress` | start_date=, end_date= | Weekly rate, BMI milestones, plateau detection, goal date |
| `get_body_composition_trend` | start_date=, end_date= | Fat vs lean mass, 14-day rolling deltas |

### Strength Training
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_strength` | view= (progress\|prs\|standards), start_date=, end_date=, exercise=, muscle_group= | Strength intelligence: volume trends / PR leaderboard / bodyweight-relative levels |
| `get_centenarian_benchmarks` | end_date=, bodyweight_lbs=, bodyweight_source= | Peter Attia's centenarian decathlon targets. 1RM vs BW ratios for deadlift/squat/bench/OHP. Readiness score + priority lift. |
| `get_exercise_history` | exercise_name, start_date=, end_date=, include_warmups= | Deep dive on a single exercise |
| `get_muscle_volume` | start_date=, end_date=, period= | Weekly sets per muscle group vs MEV/MAV/MRV |
| `get_workout_frequency` | start_date=, end_date= | Adherence, streaks, top exercises |

### Character Sheet
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_character` | view= (sheet\|pillar\|history), pillar=, days=, pillar_filter= | Character Sheet: level + pillar scores / pillar deep-dive / level-up timeline. Reads pre-computed DDB partition. Warmed nightly. |
| `set_reward` | title, condition_type, pillar=, tier=, level=, description=, reward_id= | Create reward milestone tied to Character Sheet progress |
| `get_rewards` | status= | View reward milestones |
| `update_character_config` | action, pillar=, weight=, component=, target_field=, value=, field= | View or update Character Sheet configuration |

### Sleep
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_sleep_analysis` | start_date=, end_date=, days=, target_sleep_hours= | Clinical analysis: architecture %, WASO, circadian timing, debt |
| `get_sleep_environment_analysis` | start_date=, end_date=, days= | BS-SL1: Eight Sleep temp × Whoop staging. Temperature band analysis, optimal band detection, Pearson correlations |

### Habits
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_habits` | view= (dashboard\|adherence\|streaks\|tiers\|stacks\|keystones), start_date=, end_date=, group=, habit_name=, top_n=, min_pct= | Unified P40 habit intelligence. Dashboard briefing / per-habit completion rates / streak tracking / tier-weighted scoring / co-occurrence / behavioral levers |
| `compare_habit_periods` | period_a_start, period_a_end, period_b_start, period_b_end, period_a_label=, period_b_label= | Side-by-side habit adherence |
| `get_habit_registry` | tier=, category=, vice_only=, synergy_group= | Browse 65-habit registry with tiers, weights, synergy groups |
| `get_vice_streak_history` | start_date=, end_date=, vice_name= | Vice streak trends over time, relapse dates, trajectory |
| `get_vice_streaks` | days_back=, end_date=, vice_name= | BS-BH1: Vice Streak Amplifier — compounding value calculation, streak risk, milestones, portfolio value |
| `get_essential_seven` | date=, days_back= | BS-01: Tier 0 non-negotiable habits only. Per-habit streak, today's status, completion rate |

### Sick Days
| Tool | Key Params | Description |
|------|-----------|-------------|
| `manage_sick_days` | action= (list\|log\|clear), date=, dates=[], reason=, start_date=, end_date= | Manage sick/rest day flags (suppresses streak breaks and anomaly noise) |

### Garmin Biometrics
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_garmin_summary` | start_date=, end_date= | Body Battery, stress, HRV, RHR, training load |
| `get_device_agreement` | start_date=, end_date= | Whoop vs Garmin HRV/RHR cross-validation |

### Labs & Genome
| Tool | Key Params | Description |
|------|-----------|-------------|
| `search_biomarker` | query | Free-text biomarker search across all draws |
| `get_genome_insights` | category=, risk_level=, gene=, cross_reference= | 110 SNP interpretations |

### Blood Glucose / CGM
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_glucose_meal_response` | start_date=, end_date=, meal_gap_minutes= | Postprandial analysis with letter grades |

### Correlation & Fitness
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_zone2_breakdown` | start_date=, end_date=, weekly_target_minutes=, min_duration_minutes= | 5-zone HR distribution vs 150 min target |
| `get_lactate_threshold_estimate` | start_date=, end_date=, zone2_hr_low=, zone2_hr_high=, min_duration_min=, sport_type= | Aerobic threshold from cardiac efficiency |
| `get_exercise_efficiency_trend` | start_date=, end_date=, sport_type=, min_hr=, min_duration_min= | Pace-at-HR trend (fitness signal) |
| `get_hr_recovery_trend` | start_date=, end_date=, sport_type=, cooldown_only= | Post-exercise HR recovery trend |

### Journal & Mood
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_journal_entries` | start_date=, end_date=, template=, include_enriched= | Retrieve entries with AI-enriched fields |
| `search_journal` | query, start_date=, end_date= | Full-text search across all journal fields |
| `get_journal_insights` | start_date=, end_date= | Cross-entry patterns: themes, emotions, avoidance |
| `get_journal_sentiment_trajectory` | start_date=, end_date=, days= | BS-MP2: Mood/energy/stress regression, divergence detection, inflection points |

### Coaching Log / Insights
| Tool | Key Params | Description |
|------|-----------|-------------|
| `save_insight` | text, tags=[], source= | Save new insight or hypothesis |
| `get_insights` | status_filter=, limit= | List open/acted/resolved insights |
| `update_insight_outcome` | insight_id, outcome_notes=, status= | Record outcome when acting on insight |

### Travel & Jet Lag
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_travel` | action= (start\|end), destination_city=, destination_country=, destination_timezone=, start_date=, end_date=, purpose=, trip_id=, notes= | Start or end a trip with timezone offset and Huberman jet lag protocol |
| `get_travel_log` | status= | All trips with status |
| `get_jet_lag_recovery` | trip_id=, recovery_window_days= | Post-trip recovery analysis |

### Blood Pressure
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_blood_pressure_dashboard` | start_date=, end_date= | AHA classification, trends, morning vs evening |

### N=1 Experiments
| Tool | Key Params | Description |
|------|-----------|-------------|
| `create_experiment` | name, hypothesis, start_date=, tags=[], notes=, library_id=, duration_tier=, experiment_type=, planned_duration_days= | Start tracking a protocol change |
| `list_experiments` | status= | View all experiments |
| `get_experiment_results` | experiment_id | Auto-compare 16 metrics before vs during |
| `end_experiment` | experiment_id, outcome=, status=, end_date=, grade=, compliance_pct=, reflection= | Close experiment |

### Challenges
| Tool | Key Params | Description |
|------|-----------|-------------|
| `create_challenge` | name, catalog_id=, description=, source=, domain=, difficulty=, duration_days=, protocol=, success_criteria=, metric_targets=, status=, verification_method=, tags=[] | Create a gamified challenge (candidate or active) |
| `activate_challenge` | challenge_id | Transition challenge from candidate to active |
| `checkin_challenge` | challenge_id, completed, note=, rating=, date= | Record daily check-in for active challenge |
| `list_challenges` | status=, source=, domain=, limit= | List challenges with progress stats |
| `complete_challenge` | challenge_id, status=, outcome=, reflection= | End challenge, compute success rate, award XP |

### Protocols
| Tool | Key Params | Description |
|------|-----------|-------------|
| `create_protocol` | name, slug=, domain=, category=, pillar=, status=, start_date=, description=, why=, key_metrics=[], tracked_by=[], related_habits=[], related_supplements=[], experiment_tags=[], adherence_target=, signal_status=, signal_note= | Create a health protocol (strategy layer) |
| `update_protocol` | protocol_id, name=, description=, why=, status=, domain=, category=, pillar=, key_finding=, signal_status=, signal_note=, key_metrics=[], tracked_by=[], related_habits=[], related_supplements=[], adherence_target= | Update fields on an existing protocol |
| `list_protocols` | status=, domain= | List all protocols |
| `retire_protocol` | protocol_id, reason= | Retire a protocol |

### Social & Behavioral
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_life_event` | title, type=, date=, description=, people=[], emotional_weight=, recurring= | Log structured life events |
| `get_life_events` | start_date=, end_date=, type=, person= | Retrieve life events with filters |
| `log_interaction` | person, type=, depth=, date=, duration_min=, notes=, initiated_by= | Log social interactions |
| `get_social_dashboard` | start_date=, end_date= | Contact frequency, depth, Murthy threshold |
| `get_social_connection_trend` | start_date=, end_date= | Social connection quality trend |
| `log_temptation` | category, resisted, date=, trigger=, intensity=, time_of_day=, notes= | Log resist/succumb moments |
| `get_temptation_trend` | start_date=, end_date= | Resist rate, trigger patterns |

### Discoveries
| Tool | Key Params | Description |
|------|-----------|-------------|
| `annotate_discovery` | date, event_type, title, annotation, action_taken=, outcome= | Add behavioral response annotation to a Discoveries timeline event |
| `get_discovery_annotations` | — | List all discovery annotations |

### Food Delivery
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_food_delivery` | view= (dashboard\|history\|binge\|streaks\|annual), months= | Food delivery behavioral intelligence: streak, monthly timeline, binge detection, clean periods, year-by-year |

### Body Measurements
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_measurements` | latest_only=, start_date=, end_date= | Body tape measurements: raw dimensions + derived metrics (waist-to-height, bilateral symmetry) |
| `get_measurement_trends` | include_projection= | Cross-session analysis: deltas from baseline, rate of change, recomposition score, W/H ratio projection |

### Supplements
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_supplement` | name, dose=, unit=, timing=, category=, notes=, date= | Log supplement or medication intake |
| `get_supplement_log` | start_date=, end_date=, name= | Supplement history and adherence |

### Board of Directors
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_board_of_directors` | member_id=, type=, feature=, active_only= | View 14-member expert panel |

### Todoist
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_todoist_snapshot` | view= (load\|today), date=, days= | Task load snapshot or daily Todoist summary |
| `get_task_completion_trend` | days= | Daily completed count + 7-day rolling avg |
| `get_project_activity` | days= | Completions by project, neglected domain detection |
| `get_decision_fatigue_signal` | days= | Task load × T0 habit compliance Pearson r |
| `list_todoist_tasks` | filter_str=, limit= | Active tasks with Todoist filter syntax |
| `get_todoist_projects` | — | All projects with IDs and names |
| `create_todoist_task` | content, project_id=, due_string=, due_date=, priority=, description= | Create task with optional due_string, priority |
| `update_todoist_task` | task_id, due_string=, due_date=, content=, description=, priority=, project_id= | Update task. Use `every!` for recurring due_string. |
| `close_todoist_task` | task_id | Mark task complete |
| `delete_todoist_task` | task_id | Permanently delete task |

### Platform Memory
| Tool | Key Params | Description |
|------|-----------|-------------|
| `write_platform_memory` | category, content, date=, overwrite= | Store structured memory record |
| `read_platform_memory` | category, days=, limit= | Retrieve memory records |
| `list_memory_categories` | days= | List categories with record counts |
| `delete_platform_memory` | category, date | Delete a memory record |
| `capture_baseline` | date=, label=, force= | Capture full-state Day 1 baseline snapshot across 8 domains (weight, BP, HRV, character, habits, vices, glucose, nutrition). Safe: won't overwrite without force=true. |

### Decision Journal
| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_decision` | decision, followed=, override_reason=, source=, pillars=[], date= | Record platform-guided decision |
| `get_decisions` | days=, pillar=, outcome_only= | Decisions with trust calibration stats |
| `update_decision_outcome` | sk, outcome_metric=, outcome_delta=, outcome_notes=, effectiveness= | Record outcome 1-3 days later |

### Adaptive Mode
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_adaptive_mode` | days= | Current brief mode (flourishing/standard/struggling) and engagement score history |

### Hypothesis Engine
| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_hypotheses` | status=, domain=, days=, include_archived= | Weekly hypotheses from hypothesis-engine Lambda |
| `update_hypothesis_outcome` | sk, verdict, evidence_note=, effectiveness= | Record confirming/refuting observation |

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
| 8 | habit_dashboard_today | get_habits(view=dashboard) |
| 9 | health_risk_profile_today | get_health(view=risk_profile) |
| 10 | health_trajectory_today | get_health(view=trajectory) |
| 11 | training_load_today | get_training(view=load) |
| 12 | training_periodization_today | get_training(view=periodization) |
| 13 | training_recommendation_today | get_training(view=recommendation) |
| 14 | character_sheet_today | get_character(view=sheet) |
| 15 | cgm_dashboard_today | get_cgm(view=dashboard) |
