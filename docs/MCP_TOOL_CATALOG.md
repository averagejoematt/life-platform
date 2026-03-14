# Life Platform — MCP Tool Catalog

**Version:** v3.7.12 | **Last updated:** 2026-03-14 | **Total tools:** 116

> Complete reference for all MCP tools exposed to Claude Desktop.
> For usage examples and natural language queries, see USER_GUIDE.md.

---

## Quick Reference

| # | Category | Tools | Cached |
|---|----------|-------|--------|
| 1 | Core Data Access | 16 | 4 |
| 2 | Weight & Body Composition | 4 | 1 |
| 3 | Strength Training | 6 | 0 |
| 4 | Sleep | 1 | 0 |
| 5 | Nutrition | 7 | 0 |
| 6 | Correlation & Sleep Impact | 3 | 0 |
| 7 | Habits | 11 | 1 |
| 8 | Garmin Biometrics | 2 | 0 |
| 9 | Labs & Genome | 8 | 2 |
| 10 | Blood Glucose (CGM) | 5 | 0 |
| 11 | Gait & Movement | 3 | 2 |
| 12 | Journal | 5 | 0 |
| 13 | Coaching Log | 3 | 0 |
| 14 | Day Classification | 1 | 1 |
| 15 | N=1 Experiments | 4 | 0 |
| 16 | Health Trajectory | 1 | 0 |
| Travel & Jet Lag | 3 | 0 |
| Blood Pressure | 2 | 0 |
| Supplements | 3 | 0 |
| Weather & Seasonal | 1 | 0 |
| Training Periodization | 2 | 0 |
| Social Connection | 2 | 0 |
| Meditation | 1 | 0 |
| State of Mind | 1 | 0 |
| Board of Directors | 3 | 0 |
| Character Sheet | 3 | 0 |
| Social & Behavioral | 11 | 0 |
| Longevity & Metabolic Intelligence | 4 | 0 |
| Character Sheet Phase 4 | 3 | 0 |
| 25 | Todoist | 11 | 0 |
| 26 | Platform Memory | 4 | 0 |
| 27 | Decision Journal | 3 | 0 |
| 28 | Adaptive Mode | 1 | 0 |
| 29 | Hypothesis Engine | 2 | 0 |
| | **Total** | **144** | **12** |

> **Note:** 120 tools as of v2.72.0 (verified against TOOLS dict in `mcp/registry.py`).

---

## Legend

- **Required params** shown in **bold**
- **Optional params** shown in regular text
- ⚡ = Pre-cached nightly (returns <100ms on default queries)
- 📦 = Reads from S3 (not just DynamoDB)

---

## 1. Core Data Access (16 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_sources` | — | — | List all data sources and their date ranges |
| `get_latest` | — | sources | Most recent record(s) for one or more sources |
| `get_daily_summary` | **date** | — | All sources for a single date |
| `get_date_range` | **source, start_date, end_date** | — | Time-series for one source (auto-aggregates >90 days) |
| `find_days` | **source, start_date, end_date** | filters[] | Find days where metrics meet threshold conditions |
| `get_aggregated_summary` ⚡ | — | source, start_date, end_date, period | Monthly/yearly averages (cached: yearly 5yr + monthly 2yr) |
| `get_field_stats` | **source, field** | start_date, end_date | Min/max/avg, top-5 highs and lows, trend direction |
| `search_activities` | — | start_date, end_date, name_contains, sport_type, min_distance_miles, min_elevation_gain_feet, sort_by, limit | Search Strava activities by name/type/distance/elevation with percentile ranking |
| `compare_periods` | **period_a_start, period_a_end, period_b_start, period_b_end** | period_a_label, period_b_label, source | Side-by-side comparison of two date ranges |
| `get_weekly_summary` | — | start_date, end_date, sort_by, limit, sort_ascending | Weekly training totals ranked by distance |
| `get_training_load` | — | start_date, end_date | CTL/ATL/TSB/ACWR (Banister model) with injury risk classification |
| `get_personal_records` ⚡ | — | end_date | All-time PRs across every metric |
| `get_cross_source_correlation` | **source_a, field_a, source_b, field_b** | lag_days, start_date, end_date | Pearson correlation between any two metrics |
| `get_seasonal_patterns` ⚡ | — | source, start_date, end_date | Month-by-month averages across all years |
| `get_health_dashboard` ⚡ | — | — | Current-state morning briefing |
| `get_readiness_score` ⚡ | — | date | Unified 0-100 score (Whoop 35% + Eight Sleep 25% + HRV 20% + TSB 10% + Body Battery 10%) |

---

## 2. Weight & Body Composition (4 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_weight_loss_progress` | — | start_date, end_date | Weekly rate, BMI milestones, plateau detection, phase progress |
| `get_body_composition_trend` | — | start_date, end_date | Fat vs lean mass, 14-day rolling deltas |
| `get_energy_expenditure` | — | target_deficit_kcal, end_date | TDEE = BMR + exercise, implied calorie target |
| `get_non_scale_victories` | — | end_date | Fitness improvements independent of scale |

---

## 3. Strength Training (6 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_exercise_history` | **exercise_name** | start_date, end_date, include_warmups | Deep dive on a single exercise over time |
| `get_strength_prs` | — | start_date, end_date, muscle_group_filter, min_sessions | All-exercise PR leaderboard by estimated 1RM |
| `get_muscle_volume` | — | start_date, end_date, period | Weekly sets per muscle group vs MEV/MAV/MRV |
| `get_strength_progress` | **exercise_name** | start_date, end_date, plateau_threshold_days | Longitudinal 1RM trend + plateau detection |
| `get_workout_frequency` | — | start_date, end_date | Adherence, streaks, top 15 most-trained exercises |
| `get_strength_standards` | — | end_date, bodyweight_source, bodyweight_lbs | Bodyweight-relative classification (novice → elite) |

---

## 4. Sleep (1 tool)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_sleep_analysis` | — | start_date, end_date, days, target_sleep_hours | Clinical analysis: architecture %, efficiency, WASO, circadian timing, social jetlag, debt, respiratory rate |

---

## 5. Nutrition (7 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_nutrition_summary` | — | start_date, end_date | Daily macros, rolling averages, fiber/1000kcal, protein distribution |
| `get_macro_targets` | — | start_date, end_date, days, calorie_target, protein_target | Actual vs targets with hit rate |
| `get_food_log` | — | date | Per-meal entries with timestamps and per-item macros |
| `get_micronutrient_report` | — | start_date, end_date | ~25 micronutrients vs RDA and longevity targets |
| `get_meal_timing` | — | start_date, end_date | Eating window, circadian alignment, last-bite-to-sleep gap |
| `get_nutrition_biometrics_correlation` | — | start_date, end_date, lag_days | 10 nutrition metrics × 9 biometric outcomes with day lag |
| `get_caffeine_sleep_correlation` | — | start_date, end_date | Personal caffeine cutoff finder: dose/timing buckets vs sleep |

---

## 6. Correlation & Sleep Impact (3 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_exercise_sleep_correlation` | — | start_date, end_date, min_duration_minutes, exclude_sport_types | Exercise timing/intensity vs same-night sleep quality |
| `get_zone2_breakdown` | — | start_date, end_date, weekly_target_minutes, min_duration_minutes | 5-zone HR distribution, weekly vs 150 min target |
| `get_alcohol_sleep_correlation` | — | start_date, end_date | Dose buckets, drinking vs sober, HRV/recovery impact |

---

## 7. Habits (11 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_habit_adherence` | — | start_date, end_date, group | Per-habit and per-group completion rates |
| `get_habit_streaks` | — | start_date, end_date, habit_name | Current streak, longest streak, days since last |
| `get_keystone_habits` | — | start_date, end_date, top_n | Habits most correlated with overall P40 score |
| `get_habit_health_correlations` | **health_source, health_field** | habit_name, group_name, start_date, end_date, lag_days | Correlate any habit against any biometric |
| `get_group_trends` | — | start_date, end_date, groups | Weekly P40 group scores over time |
| `compare_habit_periods` | **period_a_start, period_a_end, period_b_start, period_b_end** | period_a_label, period_b_label | Side-by-side habit adherence |
| `get_habit_stacks` | — | start_date, end_date, top_n, min_pct | Co-occurrence analysis — which habits cluster |
| `get_habit_dashboard` ⚡ | — | end_date | Current-state P40 briefing |
| `get_habit_registry` | — | tier, category | Browse the 65-habit registry with tier (0/1/2), category, scientific mechanism, personal context, synergy groups, and scoring weights. Filter by tier or category |
| `get_habit_tier_report` | — | start_date, end_date | Tier-weighted scoring report: T0 (non-negotiable, 3x weight) completion, T1 (high priority, 1x) adherence, T2 (aspirational, 0.5x) summary. Synergy group completion. Composite score |
| `get_vice_streak_history` | — | start_date, end_date | Vice-free streak tracking for 5 monitored vices. Current streak, longest streak, last occurrence, 90-day lookback |

---

## 8. Garmin Biometrics (2 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_garmin_summary` | — | start_date, end_date | Body Battery, stress, HRV, RHR, respiration, training load |
| `get_device_agreement` | — | start_date, end_date | Whoop vs Garmin HRV/RHR cross-validation |

---

## 9. Labs & Genome (8 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_lab_results` | — | draw_date, category | Blood work results by date or category |
| `get_lab_trends` | — | biomarker, biomarkers, include_derived_ratios | Longitudinal biomarker trajectory with derived ratios |
| `get_out_of_range_history` | — | — | All out-of-range biomarkers with persistence classification |
| `search_biomarker` | **query** | — | Free-text biomarker search across all draws |
| `get_genome_insights` | — | category, risk_level, gene, cross_reference | 110 SNP interpretations with optional labs/nutrition cross-ref |
| `get_body_composition_snapshot` ⚡ | — | date | DEXA scan: FFMI, visceral fat, BMD, posture |
| `get_health_risk_profile` ⚡ | — | domain | Multi-source risk synthesis: cardiovascular, metabolic, longevity |
| `get_next_lab_priorities` | — | — | Recommended tests based on genetic risk and gaps |

---

## 10. Blood Glucose / CGM (5 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_cgm_dashboard` | — | start_date, end_date | Avg, time in range, variability, fasting proxy, clinical flags |
| `get_glucose_sleep_correlation` | — | start_date, end_date | Glucose buckets vs same-night sleep quality |
| `get_glucose_meal_response` 📦 | — | start_date, end_date, meal_gap_minutes | Levels-style postprandial analysis with letter grades |
| `get_fasting_glucose_validation` 📦 | — | nadir_start_hour, nadir_end_hour, deep_nadir_start_hour, deep_nadir_end_hour, min_overnight_readings | CGM overnight nadir vs venous lab draws |
| `get_glucose_exercise_correlation` | — | start_date, end_date | Exercise vs rest day glucose, intensity analysis |

---

## 11. Gait & Movement (3 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_gait_analysis` | — | start_date, end_date | Walking speed, step length, asymmetry, double support. Composite 0-100 |
| `get_energy_balance` ⚡ | — | start_date, end_date, target_deficit_kcal | Apple Watch TDEE vs MacroFactor intake, surplus/deficit |
| `get_movement_score` ⚡ | — | start_date, end_date, step_target | NEAT, step tracking, sedentary flags. Composite 0-100 |

---

## 12. Journal (5 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_journal_entries` | — | start_date, end_date, template, include_enriched | Retrieve entries with AI-enriched fields |
| `search_journal` | **query** | start_date, end_date | Full-text search across raw text + all enriched fields |
| `get_mood_trend` | — | start_date, end_date, metric | Mood/energy/stress over time, 7-day rolling avg, themes at peaks/valleys |
| `get_journal_insights` | — | start_date, end_date | Cross-entry patterns: themes, emotions, cognitive patterns, avoidance, ownership |
| `get_journal_correlations` | — | start_date, end_date, signal | Journal mood/stress vs wearable data, divergence detection |

---

## 13. Coaching Log (3 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `save_insight` | **text** | tags, source | Save a new insight or hypothesis |
| `get_insights` | — | status_filter, limit | List open/acted/resolved insights, flags stale (≥7 days) |
| `update_insight_outcome` | **insight_id** | outcome_notes, status | Record what happened when you acted on an insight |

---

## 14. Day Classification (1 tool)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_day_type_analysis` ⚡ | — | start_date, end_date, days, metrics | Classify days as rest/light/moderate/hard/race, compare sleep/recovery/nutrition by type |

---

## 15. N=1 Experiments (4 tools)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `create_experiment` | **name**, **hypothesis** | tags, start_date | Start tracking a protocol change with hypothesis and optional tags |
| `list_experiments` | — | status_filter | View all active/completed/abandoned experiments |
| `get_experiment_results` | **experiment_id** | — | Auto-compare 16 health metrics (sleep, HRV, recovery, glucose, weight, mood, etc.) before vs during experiment period. Board of Directors evaluates results against hypothesis. Warns if <14 days of data. |
| `end_experiment` | **experiment_id** | outcome_notes, status | Close experiment as completed/abandoned with outcome notes |

**Schema:** `PK: USER#matthew#SOURCE#experiments` / `SK: EXP#<slug>_<date>`

---

## 16. Health Trajectory (1 tool)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_health_trajectory` | — | domain | Forward-looking projections across 5 domains: weight (rate of loss, phase milestones, goal date), biomarkers (lab trend slopes, 6-mo projections, threshold warnings), fitness (Zone 2 trend, training consistency), recovery (HRV/RHR/sleep efficiency trends), metabolic (glucose trend, time-in-range). Board of Directors longevity assessment. |

**Domain filter:** `all` (default), `weight`, `biomarkers`, `fitness`, `recovery`, `metabolic`

**Data sources:** Withings (weight), Labs (biomarkers), Strava (fitness), Whoop + Eight Sleep (recovery), Apple Health CGM (metabolic)

---

## 17. Travel & Jet Lag (3 tools) — v2.40.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `log_travel` | action | destination_city, destination_country, destination_timezone, start_date, end_date, purpose, notes, trip_id | Start or end a trip. action='start' creates a new trip with timezone offset computation (eastbound/westbound). action='end' closes active trip. Huberman jet lag protocol returned on start. |
| `get_travel_log` | — | status | List all trips with status filter (active/completed). Shows currently_traveling flag, active trip details, trip durations. |
| `get_jet_lag_recovery` | — | trip_id, recovery_window_days | Post-trip recovery analysis. Compares 7-day pre-trip baseline to post-return recovery curve across 8 metrics (HRV, recovery, sleep, stress, Body Battery, steps). Days-to-baseline per metric. Board coaching (Huberman/Attia/Walker). |

**DynamoDB partition:** `USER#matthew#SOURCE#travel` with SK `TRIP#<slug>_<start_date>`

**Integration:** Anomaly detector checks travel partition before alerting — suppresses alerts during travel. Daily brief shows travel banner with jet lag protocol.

---

## 18. Blood Pressure (2 tools) — v2.40.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_blood_pressure_dashboard` | — | start_date, end_date | BP status dashboard: latest reading, AHA classification (normal/elevated/stage1/stage2/crisis), period averages, variability (SD), trend direction, recent 7-day readings, morning vs evening patterns. |
| `get_blood_pressure_correlation` | — | start_date, end_date | Correlate BP with 11 lifestyle factors: sodium, calories, caffeine, training, stress, sleep efficiency/score, weight, etc. Pearson r for systolic + diastolic. Exercise vs rest day comparison. Sodium dose-response buckets. |

**Data path:** BP cuff → Apple Health → Health Auto Export webhook → DynamoDB (daily avg) + S3 (individual readings)

**AHA categories:** Normal (<120/<80), Elevated (120-129/<80), Stage 1 (130-139/80-89), Stage 2 (≥140/≥90), Crisis (≥180/≥120)

---

## 19. State of Mind (1 tool) — v2.41.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_state_of_mind_trend` | — | start_date, end_date | Valence trend from How We Feel / Apple Health State of Mind. Tracks momentary emotions + daily moods with valence (-1 to +1), emotion labels, life area associations. Overall trend, 7-day rolling avg, time-of-day patterns, best/worst days, top labels, valence by life area, classification distribution. Returns setup instructions when no data found. |

**Data path:** How We Feel app → Apple HealthKit State of Mind → Health Auto Export (separate Data Type automation) → Webhook Lambda v1.5.0 → S3 (`raw/state_of_mind/`) + DynamoDB (`state_of_mind` source)

**DynamoDB fields:** `som_avg_valence`, `som_min_valence`, `som_max_valence`, `som_check_in_count`, `som_mood_count`, `som_emotion_count`, `som_top_labels`, `som_top_associations`

---

## 20. Board of Directors Management (3 tools) — v2.56.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_board_of_directors` | — | member_id, type, feature, active_only | View expert panel. Filter by member ID (`sarah_chen`, `elena_voss`, etc.), type (`fictional_advisor`/`real_expert`/`narrator`/`meta_role`), feature (`weekly_digest`/`daily_brief`/`nutrition_review`/`chronicle`), or active status. Returns personas, voice profiles, domains, and per-feature config. |
| `update_board_member` | member_id, updates | — | Add or update a board member. Supports partial updates via deep-merge. New members require name, title, type in updates dict. |
| `remove_board_member` | member_id | hard_delete | Deactivate (default, soft-delete) or permanently remove a board member. |

**Data path:** S3 `config/board_of_directors.json` — 12 members (6 fictional advisors + 5 real experts + 1 narrator). Read-heavy, rarely written, consumed as whole unit.

**Module:** `mcp/tools_board.py`

---

## 21. Character Sheet (3 tools) — v2.58.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_character_sheet` | — | date | Current character level, all 7 pillar scores with tier/XP/sparklines, active cross-pillar effects, and recent level events. Defaults to today (falls back to yesterday if not yet computed). 14-day sparkline per pillar. |
| `get_pillar_detail` | pillar | days, date | Deep dive into a single pillar: component breakdown with individual scores, daily raw_scores over time, level history, XP curve. Valid pillars: sleep, movement, nutrition, metabolic, mind, relationships, consistency. |
| `get_level_history` | — | days, pillar, date | Timeline of all level and tier change events. Shows level ups/downs, tier transitions, milestones. Filter by pillar or view all. Default 90 days. |

**Data path:** DynamoDB `USER#matthew#SOURCE#character_sheet` / `DATE#YYYY-MM-DD` — computed daily by backfill (Phase 1) then Daily Brief Lambda (Phase 2). Config: `s3://matthew-life-platform/config/character_sheet.json`.

**Module:** `mcp/tools_character.py`

---

## Cache Details

12 tools are pre-computed nightly at 9:00 AM PT by the MCP Lambda warmer. Results are stored in the `CACHE#matthew` DynamoDB partition with a 26-hour TTL.

| Tool | Cache Key Pattern | Bypass |
|------|------------------|--------|
| `get_aggregated_summary` (yearly) | `aggregated_summary_year_*` | Non-default date range |
| `get_aggregated_summary` (monthly) | `aggregated_summary_month_*` | Non-default date range |
| `get_personal_records` | `personal_records_all` | Custom end_date |
| `get_seasonal_patterns` | `seasonal_patterns_all` | Custom source/date |
| `get_health_dashboard` | `health_dashboard_today` | N/A |
| `get_habit_dashboard` | `habit_dashboard_today` | Custom end_date |
| `get_readiness_score` | `readiness_score_YYYY-MM-DD` | Custom date |
| `get_health_risk_profile` | `health_risk_profile_all` | Custom domain |
| `get_body_composition_snapshot` | `body_comp_snapshot_latest` | Custom date |
| `get_energy_balance` | `energy_balance_YYYY-MM-DD` | Custom date range |
| `get_day_type_analysis` | `day_type_analysis_YYYY-MM-DD` | Custom date range |
| `get_movement_score` | `movement_score_YYYY-MM-DD` | Custom date range |

---

## Data Source Dependencies

Tools that require specific data sources to function:

| Required Source | Tools |
|----------------|-------|
| Whoop | readiness_score, sleep correlations, anomaly metrics |
| Eight Sleep | sleep_analysis, readiness_score, glucose/alcohol/exercise-sleep correlations |
| Strava | search_activities, training_load, zone2_breakdown, exercise correlations, weekly_summary |
| MacroFactor | nutrition_summary, macro_targets, food_log, meal_timing, micronutrient_report, caffeine/alcohol correlations, glucose_meal_response |
| Apple Health (webhook) | gait_analysis, energy_balance, movement_score, cgm_dashboard, glucose tools |
| Garmin | garmin_summary, device_agreement, readiness_score (Body Battery component) |
| Habitify | All 11 habit tools |
| DynamoDB habit_scores partition | get_habit_tier_report (historical trending) |
| Notion | All 5 journal tools |
| Labs (manual seed) | lab_results, lab_trends, out_of_range_history, search_biomarker, next_lab_priorities |
| DEXA (manual seed) | body_composition_snapshot |
| Genome (manual seed) | genome_insights, health_risk_profile (genome component) |
| Hevy / MacroFactor Workouts | All 6 strength tools |
| S3 CGM readings | glucose_meal_response, fasting_glucose_validation |
| DynamoDB experiments partition | create_experiment, list_experiments, get_experiment_results, end_experiment |
| DynamoDB travel partition | log_travel, get_travel_log, get_jet_lag_recovery |
| Apple Health BP (via webhook) | get_blood_pressure_dashboard, get_blood_pressure_correlation |
| Multi-source (Withings, Labs, Strava, Whoop, Eight Sleep, Apple Health CGM) | get_health_trajectory |
| State of Mind (via webhook) | get_state_of_mind_trend |
| Weather (Open-Meteo via Lambda) | get_weather_correlation |
| DynamoDB life_events partition | log_life_event, get_life_events |
| DynamoDB interactions partition | log_interaction, get_social_dashboard |
| DynamoDB temptations partition | log_temptation, get_temptation_trend |
| DynamoDB exposures partition | log_exposure, get_exposure_log, get_exposure_correlation |
| Labs (7 draws, 9 biomarkers) | get_biological_age |
| CGM + Withings + Labs + BP | get_metabolic_health_score |
| MacroFactor food_log + CGM | get_food_response_database |
| Notion journal (defense-enriched) | get_defense_patterns |

---

## 22. Social & Behavioral (11 tools) — v2.70.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `log_life_event` | **title** | type, date, description, people, emotional_weight, recurring | Log structured life events (birthday, milestone, conflict, loss, etc.) |
| `get_life_events` | — | start_date, end_date, type, person | Retrieve life events with filters |
| `log_interaction` | **person** | type, depth, date, duration_min, notes, initiated_by | Log social interactions with depth rating |
| `get_social_dashboard` | — | start_date, end_date | Contact frequency, depth distribution, Murthy threshold |
| `log_temptation` | **category**, **resisted** | date, trigger, intensity, time_of_day, notes | Log resist/succumb moments |
| `get_temptation_trend` | — | start_date, end_date | Resist rate, category breakdown, trigger patterns |
| `log_exposure` | **type** | date, duration_min, temperature_f, time_of_day, notes | Log cold/heat exposure sessions |
| `get_exposure_log` | — | start_date, end_date | Exposure history and frequency stats |
| `get_exposure_correlation` | — | start_date, end_date | Exposure vs HRV, sleep, recovery, mood |
| `get_exercise_variety` | — | start_date, end_date, window_weeks | Shannon diversity index, staleness detection |
| `get_state_of_mind_trend` | — | start_date, end_date | How We Feel valence trend, emotion labels, life areas |

---

## 23. Longevity & Metabolic Intelligence (4 tools) — v2.72.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_biological_age` | — | draw_date | Levine PhenoAge from 9 blood biomarkers. Trajectory across all draws, genome context, Board assessment. |
| `get_metabolic_health_score` | — | start_date, end_date | Composite 0-100: CGM (30%) + labs (35%) + weight (20%) + BP (15%). MetSyn criteria check. Grade A-F. |
| `get_food_response_database` | — | start_date, end_date, min_observations, sort_by | Personal food leaderboard by glycemic impact. Macro correlations. |
| `get_defense_patterns` | — | start_date, end_date | Defense mechanism patterns from journal enrichment. Frequency, mood/stress correlation, Conti assessment. |

**Module:** `mcp/tools_longevity.py`

---

## 25. Todoist (11 tools) — v2.85.0

### Read Tools

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_task_completion_trend` | — | start_date, end_date, days | Daily completed task count + 7-day rolling average. Productivity trend signal. |
| `get_task_load_summary` | — | date | Active count, overdue count, due-today snapshot, priority breakdown (P1-P4), cognitive load signal. |
| `get_project_activity` | — | start_date, end_date, days | Completions by project with attention gap detection — which projects are being neglected. |
| `get_decision_fatigue_signal` | — | start_date, end_date, days | Correlates task load × T0 habit compliance. Pearson r between cognitive load and non-negotiable habit completion. |
| `get_todoist_day` | — | date | Full Todoist snapshot for a specific date (all fields). |

### Write Tools

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `list_todoist_tasks` | — | project_id, filter, limit | List active tasks. Supports Todoist filter syntax. |
| `get_todoist_projects` | — | — | List all Todoist projects with IDs and names. |
| `create_todoist_task` | **content** | project_id, due_string, priority, description, labels | Create a new task. Use `every! X days` syntax for completion-based recurrence. |
| `update_todoist_task` | **task_id** | content, due_string, priority, description, labels | Update an existing task. |
| `close_todoist_task` | **task_id** | — | Mark a task as complete. |
| `delete_todoist_task` | **task_id** | — | Permanently delete a task. |

**Note:** Use `every!` (not `every`) for recurring tasks — prevents pile-up when tasks slip.

---

## 26. Platform Memory (4 tools) — v2.86.0 (IC-1)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `write_platform_memory` | **category**, **content** | date, overwrite | Store a structured memory record. Categories: `failure_pattern`, `what_worked`, `coaching_calibration`, `personal_curves`, `journey_milestone`, `weekly_plate`, `insight`, `experiment_result`. |
| `read_platform_memory` | **category** | days, limit | Retrieve recent memory records for a category. Defaults: 30 days, 10 records. |
| `list_memory_categories` | — | days | List all categories with record counts and date ranges. |
| `delete_platform_memory` | **category**, **date** | — | Delete a specific memory record. |

**DDB partition:** `USER#matthew#SOURCE#platform_memory` / `MEMORY#<category>#<date>`
**Module:** `mcp/tools_memory.py`

---

## 27. Decision Journal (3 tools) — v2.88.0 (IC-19)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `log_decision` | **decision** | source, followed, override_reason, pillars, date | Record a platform-guided decision and whether you followed it. `followed` = true/false/null. |
| `get_decisions` | — | days, pillar, outcome_only | Retrieve decisions with trust calibration stats — follow vs override effectiveness comparison. |
| `update_decision_outcome` | **sk** | outcome_metric, outcome_delta, outcome_notes, effectiveness | Record what happened 1-3 days after a decision. `effectiveness` 1-5 scale. |

**DDB partition:** `USER#matthew#SOURCE#decisions` / `DECISION#<ISO-timestamp>`
**Module:** `mcp/tools_decisions.py`

---

## 28. Adaptive Mode (1 tool) — v2.73.0 (IC-50)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_adaptive_mode` | — | days | Current and historical brief mode (flourishing / standard / struggling). Engagement score, contributing factors, mode distribution, current streak. Modes are pre-computed by `adaptive-mode-compute` Lambda. |

**Modes:** Flourishing (score ≥70) / Standard (40-69) / Struggling (<40)
**DDB partition:** `USER#matthew#SOURCE#adaptive_mode`
**Module:** `mcp/tools_adaptive.py`

---

## 29. Hypothesis Engine (2 tools) — v2.89.0 (IC-18)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_hypotheses` | — | status, domain, days, include_archived | List cross-domain hypotheses generated weekly by `hypothesis-engine` Lambda. Status lifecycle: pending → confirming → confirmed (or refuted). Filter by status or domain. |
| `update_hypothesis_outcome` | **sk**, **verdict** | evidence_note, effectiveness | Record a confirming or refuting observation. Verdicts: `confirming` / `confirmed` / `refuted` / `insufficient` / `archived`. Auto-promotes to `confirmed` after 3 confirming checks. |

**Generated:** Weekly by `hypothesis-engine` Lambda (Sunday 11 AM PT)
**DDB partition:** `USER#matthew#SOURCE#hypotheses` / `HYPOTHESIS#<timestamp>`
**Module:** `mcp/tools_hypotheses.py`

---

## 24. Character Sheet Phase 4 (3 tools) — v2.71.0

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `set_reward` | **title**, **condition_type** | pillar, tier, level, description, reward_id | Create reward milestones tied to Character Sheet progress |
| `get_rewards` | — | status | View reward milestones (active/triggered/claimed) |
| `update_character_config` | **action** | pillar, weight, component, target_field, value, field | View or update Character Sheet configuration |
