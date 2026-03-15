# Life Platform — User Guide

**Project:** Intelligent Life Platform (Project40 data backbone)  
**Last updated:** 2026-03-08 (v2.91.0)

---

## What This Is

The Life Platform is a personal health intelligence system that aggregates data from nineteen sources (twelve scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalizes everything into a single DynamoDB table, and surfaces it to Claude via 144 MCP tools. A web dashboard at `https://dash.averagejoematt.com/` provides at-a-glance daily metrics and a clinical summary for doctor visits. It also sends nine automated emails covering daily, weekly, and monthly cadences. The result: Claude can answer questions about your health, fitness, sleep, nutrition, habits, productivity, body composition, labs, genome, glucose, gait, journal, and more using your actual data — not generics.

The platform proactively reaches out on a schedule — you don't have to ask. Each Monday you get a planning email bridging your health state with your task load. Each morning brings a daily brief with day grade, AI coaching, and 18 sections. Anomalies are detected automatically.

---

## Data Sources

| Source | Type | What it tracks | Update method |
|--------|------|----------------|---------------|
| Whoop | API (auto) | HRV, recovery, strain, sleep | Daily Lambda sync (6:00 AM PT) |
| Withings | API (auto) | Weight, body composition | Daily Lambda sync (6:15 AM PT) |
| Strava | API (auto) | Running, cycling, walking, hiking | Daily Lambda sync (6:30 AM PT) |
| Eight Sleep | API (auto) | Sleep score, RHR, HRV, efficiency, staging | Daily Lambda sync (7:00 AM PT) |
| Todoist | API (auto) | Tasks completed, productivity | Daily Lambda sync (6:45 AM PT) |
| Garmin | API (auto) | Body Battery, stress, HRV, RHR, respiration, steps, HR zones, training load, sleep | Daily Lambda sync (6:00 AM PT) |
| Habitify | API (auto) | P40 habits (65 habits, 9 groups), mood (1-5 scale) | Daily Lambda sync (6:15 AM PT) |
| Notion Journal | API (auto) | Daily journal entries, mood, reflections | Daily Lambda sync (6:00 AM PT) + AI enrichment (6:30 AM) |
| Health Auto Export | Webhook | CGM (Dexcom Stelo), gait, energy, water, caffeine | Background push from iOS hourly |
| Apple Health | Webhook + flat file | Steps, active calories, gait metrics, CGM, caffeine, water | Health Auto Export webhook (hourly) + manual S3 XML export |
| MacroFactor | Flat file (automated) | Nutrition, macros, micronutrients, meal timing, workouts | Phone export → Dropbox → Lambda poll (30 min) → S3 → DynamoDB |
| Labs | Manual seed | Blood work from Function Health + GP physicals | `seed_labs.py`, `seed_physicals_dexa.py` |
| DEXA | Manual seed | Body composition scan | `seed_physicals_dexa.py` |
| Genome | Manual seed | 110 SNP interpretations | `seed_genome.py` |
| Weather (Open-Meteo) | API (auto + on-demand) | Temperature, daylight, pressure, humidity | Daily Lambda sync (5:45 AM PT) + MCP on-demand |
| Supplements | MCP tool write | Supplement/medication doses, timing, adherence | Manual logging via `log_supplement` |
| State of Mind (How We Feel) | Webhook | Mood valence, emotions, life areas | Via Apple Health HAE webhook |
| Hevy | Archived | Strength training (migrated to MacroFactor workouts) | Historical backfill only |
| Chronicling | Archived | P40 habits (through 2025-11-09) | Replaced by Habitify |

---

## Email Layer (Proactive Intelligence)

You receive automated emails without asking:

| Email | Schedule (PDT) | What it does |
|-------|----------|--------------|
| **Monday Compass v1.0** | Monday 8:00 AM | Forward-looking weekly planning email: Todoist tasks grouped by pillar, health state header, AI cross-pillar prioritization, overdue pile (commit/defer/delete), 3 Board Pro Tips, This Week's Keystone action. ~$0.05/week |
| **Anomaly Alert v2.1** | Daily 9:05 AM (only if triggered) | Detects multi-source anomalies (15 metrics / 7 sources), travel-aware suppression, Haiku generates root cause hypothesis |
| **Freshness Alert** | Daily 10:45 AM (only if triggered) | Checks all data sources for staleness, emails + SNS if any source is overdue |
| **Daily Brief v2.62** | Daily 11:00 AM | 18-section brief: readiness, day grade + TL;DR, scorecard, weight phase, training, nutrition, **habits (tier-weighted intelligence)**, supplements, CGM spotlight, gait & mobility, weather context, travel banner, blood pressure, journal coach, Board of Directors insight, AI guidance. 4 Haiku AI calls. Writes dashboard JSON |
| **Weekly Digest v4.2** | Sunday 8:30am PT | 7-day summary across all sources, day grade trends, Board of Advisors commentary (Haiku). Writes clinical.json for web dashboard |
| **Monthly Coach's Letter** | 1st Monday 8:00am PT | 30-day vs prior-30-day deltas, annual goals progress bars, expert panel review |
| **Nutrition Review** | Saturday 9:00am PT | Weekly food quality analysis: macro targets, micronutrients, meal timing, eating window, Norton/Patrick/Attia panel review (Sonnet) |
| **Wednesday Chronicle** | Wednesday 7:00am PT | "The Measured Life" by Elena Voss — synthesis journalism with a thesis, not a timeline. Published to `blog.averagejoematt.com`. Board of Directors interview format 2-3×/month |
| **The Weekly Plate** | Friday 6:00pm PT | Food magazine email: Met Market grocery lists, recipe riffs, weekend nutrition planning |

The Board of Directors uses expert personas (13 members: Peter Attia, Andrew Huberman, Rhonda Patrick, Stuart McGill, Daniel Conti, Vivek Murthy, plus fictional advisors Maya Rodriguez, Lisa Park, Sarah Chen, Marcus Webb, James Okafor, Elena Voss, and The Chair) to generate actionable coaching insights.

---

## How to Use It: Asking Claude Questions

Once the MCP server is active in your Claude session, you can ask natural language questions. Claude will call the appropriate tool(s) behind the scenes.

### Daily Check-in
> "How am I doing today?"
> "Give me a morning health briefing."
> "Should I train hard today?"

Triggers `get_health_dashboard` and/or `get_readiness_score`.

### Readiness & Recovery
> "Am I ready for a hard session?"
> "What's my readiness score?"

Triggers `get_readiness_score` — unified score (0-100) from Whoop recovery (35%), Eight Sleep (25%), HRV trend (20%), TSB form (10%), and Garmin Body Battery (10%). GREEN/YELLOW/RED signal with actionable recommendation.

### Weight & Body Composition
> "How is my weight loss going?"
> "Am I losing fat or muscle?"
> "When will I reach my goal weight?"
> "What's my current BMI?"

Triggers `get_weight_loss_progress` and/or `get_body_composition_trend`.

### Training & Fitness
> "What were my biggest training weeks this year?"
> "How fit am I right now?"
> "Am I overtraining?"
> "What's my longest run ever?"
> "How much Zone 2 am I getting?"
> "Does exercise affect my sleep?"

Triggers `get_weekly_summary`, `get_training_load`, `search_activities`, `get_zone2_breakdown`, `get_exercise_sleep_correlation`.

### Strength
> "What are my all-time strength PRs?"
> "How has my bench press progressed?"
> "Am I training chest enough?"
> "How strong am I compared to standards?"

Triggers `get_strength_prs`, `get_strength_progress`, `get_muscle_volume`, `get_strength_standards`.

### Sleep
> "How has my sleep been this month?"
> "What's my sleep efficiency?"
> "Do I have sleep debt?"
> "Do I have social jetlag?"

Triggers `get_sleep_analysis` — clinical-grade analysis including sleep architecture, efficiency, WASO, circadian timing, social jetlag, and respiratory rate screening.

### Habits & P40
> "How are my habits?"
> "What's my longest meditation streak?"
> "Which habits have the most impact?"
> "Am I doing enough Recovery habits?"
> "Show me my habit registry."
> "How are my Tier 0 habits doing?"
> "What are my vice streaks?"

Triggers `get_habit_dashboard`, `get_habit_streaks`, `get_keystone_habits`, `get_habit_adherence`, `get_habit_registry`, `get_habit_tier_report`, `get_vice_streak_history`. All 11 habit tools read from Habitify (or Chronicling for historical queries pre-Nov 2025) based on the source-of-truth setting.

### Nutrition
> "How are my macros this week?"
> "Am I hitting my protein goal?"
> "What did I eat yesterday?"
> "Am I getting enough omega-3?"
> "What's my eating window?"

Triggers `get_nutrition_summary`, `get_macro_targets`, `get_food_log`, `get_micronutrient_report`, `get_meal_timing`.

### Blood Glucose (CGM)
> "What's my fasting glucose trend?"
> "How did that meal spike my glucose?"
> "Does glucose affect my sleep?"
> "Does exercise lower my blood sugar?"
> "How accurate is my CGM fasting glucose?"
> "Validate my CGM against lab draws."

Triggers `get_cgm_dashboard`, `get_glucose_meal_response`, `get_glucose_sleep_correlation`, `get_glucose_exercise_correlation`, `get_fasting_glucose_validation`.

### Gait & Mobility
> "How's my walking speed?"
> "Am I at risk for gait asymmetry?"
> "What's my movement score?"
> "How's my energy balance?"

Triggers `get_gait_analysis`, `get_movement_score`, `get_energy_balance`.

### Journal
> "What did I journal about this week?"
> "Search my journal for entries about stress."
> "How has my mood been trending?"
> "What patterns do my journal entries reveal?"

Triggers `get_journal_entries`, `search_journal`, `get_mood_trend`, `get_journal_insights`, `get_journal_correlations`.

### Labs & Genome
> "What were my latest blood work results?"
> "Are any biomarkers out of range?"
> "What should I test next?"
> "What do my genetics say about caffeine metabolism?"

Triggers `get_lab_results`, `get_lab_trends`, `get_out_of_range_history`, `search_biomarker`, `get_genome_insights`, `get_health_risk_profile`, `get_next_lab_priorities`, `get_body_composition_snapshot`.

### Caffeine & Alcohol
> "What's my caffeine cutoff?"
> "Does caffeine affect my sleep?"
> "How does alcohol affect my sleep?"

Triggers `get_caffeine_sleep_correlation`, `get_alcohol_sleep_correlation`.

### Training Day Analysis
> "How does my sleep differ on hard training days?"
> "Do I eat more on rest days?"
> "What's my HRV on hard vs easy days?"

Triggers `get_day_type_analysis`.

### Garmin Biometrics
> "What's my Body Battery trend?"
> "How stressed have I been?"
> "Do my Whoop and Garmin agree on HRV?"

Triggers `get_garmin_summary`, `get_device_agreement`.

### Historical & Trend Questions
> "How does my fitness now compare to last year?"
> "What month do I train most?"
> "Does high training volume lower my HRV?"
> "Does my diet affect my recovery?"

Triggers `compare_periods`, `get_seasonal_patterns`, `get_cross_source_correlation`, `get_nutrition_biometrics_correlation`.

### Personal Records
> "What are my all-time bests?"
> "When was I at my fittest?"

Triggers `get_personal_records`.

### N=1 Experiments
> "Create an experiment: no caffeine after 10am"
> "What experiments am I running?"
> "How is my no-caffeine experiment going?"
> "End the caffeine experiment — it worked."

Triggers `create_experiment`, `list_experiments`, `get_experiment_results`, `end_experiment`. Auto-compares 16 health metrics (sleep, recovery, HRV, glucose, weight, mood, etc.) before vs during the experiment period.

### Health Trajectory
> "Where am I headed health-wise?"
> "When will I reach my goal weight?"
> "Are any biomarkers trending toward concerning levels?"
> "Show my health trajectory for fitness."

Triggers `get_health_trajectory` — forward-looking projections across weight, biomarkers, fitness, recovery, and metabolic domains with Board of Directors longevity assessment.

### Supplements
> "Log 500mg magnesium before bed."
> "What supplements am I taking?"
> "Is magnesium helping my sleep?"
> "Am I consistent with creatine?"

Triggers `log_supplement`, `get_supplement_log`, `get_supplement_correlation`.

### Weather & Seasonal
> "Does weather affect my sleep?"
> "How does daylight correlate with my mood?"
> "Does barometric pressure affect my recovery?"

Triggers `get_weather_correlation`.

### Travel & Jet Lag
> "I'm traveling to London."
> "Show my travel history."
> "How did I recover from my trip?"
> "End my trip."

Triggers `log_travel`, `get_travel_log`, `get_jet_lag_recovery`.

### Blood Pressure
> "What's my blood pressure?"
> "Does sodium affect my BP?"
> "Am I hypertensive?"

Triggers `get_blood_pressure_dashboard`, `get_blood_pressure_correlation`.

### State of Mind
> "How has my mood been this week?"
> "What emotions am I feeling most?"
> "Valence trend this month?"

Triggers `get_state_of_mind_trend`.

### Training Periodization
> "Do I need a deload?"
> "Am I overtraining?"
> "What should I do today?"
> "Readiness-based workout recommendation."

Triggers `get_training_periodization`, `get_training_recommendation`.

### Social Connection
> "How are my social connections?"
> "Am I socially isolated?"
> "Does connection affect my recovery?"

Triggers `get_social_connection_trend`, `get_social_isolation_risk`.

### Meditation & Breathwork
> "Does meditation help my HRV?"
> "Meditation dose-response analysis."

Triggers `get_meditation_correlation`.

### Heart Rate Recovery
> "How's my HR recovery trend?"
> "Am I getting fitter?"
> "Post-exercise HR drop."

Triggers `get_hr_recovery_trend`.

### Sleep Environment
> "What's my optimal bed temperature?"
> "Does temperature affect my sleep?"

Triggers `get_sleep_environment_analysis`.

### Coaching Log
> "Save this insight: cutting caffeine after 2pm improved my sleep this week."
> "What insights are still open?"
> "Mark the caffeine insight as resolved — it worked."

Triggers `save_insight`, `get_insights`, `update_insight_outcome`.

### Character Sheet
> "What's my Character Sheet level?"
> "How are my 7 pillars doing?"
> "Show my Character Sheet history for March."
> "Any rewards or protocol recommendations this week?"

Triggers `get_character_sheet`, `get_character_history`, `get_character_insights`. RPG-style scoring system: 7 weighted pillars (Sleep 20%, Movement 18%, Nutrition 18%, Mind 15%, Metabolic 12%, Consistency 10%, Relationships 7%). Level 1–100 with tier names. Computed daily at 9:35 AM PT.

### Social & Behavioral Tracking
> "Log that I had coffee with Jake today — good conversation."
> "Log that I resisted the urge to snack at midnight."
> "Show my temptation trend."
> "Log a cold shower this morning, 3 minutes."
> "What's my exercise variety score?"
> "Log that my parents' anniversary dinner is today."

Triggers `log_life_event`, `get_life_events`, `log_contact`, `get_contact_frequency`, `log_temptation`, `get_temptation_trend`, `log_exposure`, `get_exposure_correlation`, `get_exercise_variety_score`.

### Longevity & Advanced Health
> "What's my biological age?"
> "Show my metabolic health score."
> "Which meals spike my glucose the most? Build a food response database."
> "Any defense mechanism patterns in my recent journal?"
> "Export all my data."

Triggers `get_biological_age`, `get_metabolic_health_score`, `get_food_response_database`, `get_defense_patterns`, `export_data`.

### Board of Directors
> "Show me the Board of Directors."
> "What are Peter Attia's domains?"
> "Update Dr. Rodriguez's focus areas."

Triggers `get_board_of_directors`, `update_board_member`, `remove_board_member`.

---

## Updating Data

### Automatic (no action needed)
Whoop, Withings, Strava, Eight Sleep, Todoist, Garmin, Habitify, Notion Journal, and Health Auto Export sync automatically via scheduled Lambda functions or webhooks. All data is typically available by 8am PT.

### MacroFactor (Dropbox zero-touch)
1. In MacroFactor app: More → Data Management → Data Export → Granular Export → Food diary → All time → Export
2. Save to Dropbox `/life-platform/` folder on your phone
3. `dropbox-poll` Lambda detects it (every 30 min) → copies to S3 → triggers `macrofactor-data-ingestion`
4. Works for both nutrition ("Food Name" header) and workout ("Exercise" header) exports
5. Exports always contain the last 7 days — this is fine, backfill is idempotent (overwrites identical data)
6. Recommended: one export at end of day. More frequent is fine, nothing breaks

### Apple Health (mostly automatic via webhook)
**Primary path (automatic):** Health Auto Export app runs in background on iPhone, pushing data hourly to the webhook. No manual action needed for steps, gait, CGM, caffeine, water, and other Apple Health metrics.

**⚠️ Important:** The app must be set to hourly sync (not "since last run"). With less frequent syncs, the payload grows too large and the app silently drops metrics like Dietary Water and Dietary Caffeine. If water/caffeine data stops appearing, check the app's sync interval and do a manual forced push to backfill.

**Manual export (for deep backfills):** On iPhone: Health app → profile icon → Export All Health Data → upload `export.xml` to `s3://matthew-life-platform/imports/apple_health/`.

### Habitify
Habits and mood are tracked in the Habitify app throughout the day. The Lambda automatically fetches yesterday's data at 6:15 AM PT each morning. To manually trigger for a specific date:
```bash
aws lambda invoke --function-name habitify-data-ingestion \
  --payload '{"date": "2026-02-23"}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/test.json
```

---

## MCP Tools Reference (121 tools)

All tools are exposed to Claude automatically when the MCP server is running.

### Core data access (16 tools)
| Tool | Use case |
|------|----------|
| `get_sources` | List all sources and their available date ranges |
| `get_latest` | Most recent record(s) for any source |
| `get_daily_summary` | All sources for a single date |
| `get_date_range` | Time-series data for one source (auto-aggregates >90 days) |
| `find_days` | Find days where a metric meets a threshold |
| `get_aggregated_summary` | Monthly/yearly averages over any window |
| `get_field_stats` | All-time min/max/avg + top-5 highs and lows |
| `search_activities` | Search Strava activities by name, sport type, distance, elevation |
| `compare_periods` | Side-by-side comparison of two date ranges |
| `get_weekly_summary` | Weekly training load totals ranked by distance |
| `get_training_load` | CTL/ATL/TSB/ACWR (Banister fitness-fatigue model) |
| `get_personal_records` | All-time PRs across every metric |
| `get_cross_source_correlation` | Pearson correlation between any two metrics |
| `get_seasonal_patterns` | Month-by-month averages across all years |
| `get_health_dashboard` | Current-state morning briefing |
| `get_readiness_score` | Unified readiness (0-100, GREEN/YELLOW/RED) from Whoop + Eight Sleep + HRV + TSB + Garmin Body Battery |

### Weight & body composition (4 tools)
| Tool | Use case |
|------|----------|
| `get_weight_loss_progress` | Weekly rate of loss, BMI milestones, plateau detection |
| `get_body_composition_trend` | Fat vs lean mass over time |
| `get_energy_expenditure` | TDEE = BMR + exercise, implied calorie target |
| `get_non_scale_victories` | Fitness improvements independent of scale |

### Strength training (6 tools)
| Tool | Use case |
|------|----------|
| `get_exercise_history` | Deep dive on a single exercise |
| `get_strength_prs` | All-exercise PR leaderboard by estimated 1RM |
| `get_muscle_volume` | Weekly sets per muscle group vs MEV/MAV/MRV |
| `get_strength_progress` | Longitudinal 1RM trend + plateau detection |
| `get_workout_frequency` | Adherence, streaks, most-trained exercises |
| `get_strength_standards` | Bodyweight-relative strength classification |

### Habits & P40 (11 tools)
| Tool | Use case |
|------|----------|
| `get_habit_adherence` | Per-habit and per-group completion rates |
| `get_habit_streaks` | Current streak, longest streak, days since last completion |
| `get_keystone_habits` | Which habits correlate most with overall P40 score |
| `get_habit_health_correlations` | Correlate a habit against a biometric outcome |
| `get_group_trends` | Weekly P40 group scores over time |
| `compare_habit_periods` | Side-by-side habit adherence across two date ranges |
| `get_habit_stacks` | Co-occurrence analysis — which habits cluster together |
| `get_habit_dashboard` | Current-state P40 briefing |
| `get_habit_registry` | Browse 65-habit registry: tier, category, mechanism, synergy groups |
| `get_habit_tier_report` | Tier-weighted scoring: T0/T1/T2 breakdown, synergy groups, composite score |
| `get_vice_streak_history` | Vice-free streak tracking, 90-day lookback, 5 monitored vices |

P40 groups: Data, Discipline, Growth, Hygiene, Nutrition, Performance, Recovery, Supplements, Wellbeing.

### Nutrition (7 tools)
| Tool | Use case |
|------|----------|
| `get_nutrition_summary` | Daily macro breakdown and rolling averages |
| `get_macro_targets` | Actual vs calorie/protein targets, hit rates |
| `get_food_log` | Per-meal entries for a specific date |
| `get_micronutrient_report` | ~25 micronutrients scored against RDA and longevity targets |
| `get_meal_timing` | Eating window, circadian alignment, last-bite-to-sleep gap |
| `get_nutrition_biometrics_correlation` | Pearson correlations between nutrition metrics and health outcomes |
| `get_caffeine_sleep_correlation` | Personal caffeine cutoff finder: bucket analysis, timing/dose correlations |

### Sleep & correlation tools (4 tools)
| Tool | Use case |
|------|----------|
| `get_sleep_analysis` | Clinical sleep analysis: architecture %, efficiency, debt, social jetlag, respiratory rate |
| `get_exercise_sleep_correlation` | How exercise timing/intensity affects sleep quality |
| `get_zone2_breakdown` | Zone 2 cardio time by activity type, weekly trend, percentage of total |
| `get_alcohol_sleep_correlation` | Alcohol's impact on sleep quality, HRV, recovery |

### Blood glucose / CGM (5 tools)
| Tool | Use case |
|------|----------|
| `get_cgm_dashboard` | CGM overview: daily avg, time in range, fasting proxy, variability |
| `get_glucose_meal_response` | Levels-style postprandial analysis: spike magnitude, time to peak, AUC |
| `get_glucose_sleep_correlation` | Overnight glucose patterns vs sleep quality |
| `get_glucose_exercise_correlation` | How exercise affects glucose levels |
| `get_fasting_glucose_validation` | Validate CGM fasting glucose accuracy against venous lab draws |

### Gait & mobility (3 tools)
| Tool | Use case |
|------|----------|
| `get_gait_analysis` | Walking speed (mph, clinical threshold), step length, asymmetry, double support |
| `get_energy_balance` | TDEE vs intake, surplus/deficit tracking |
| `get_movement_score` | Composite movement quality score |

### Journal (5 tools)
| Tool | Use case |
|------|----------|
| `get_journal_entries` | Retrieve journal entries for a date range |
| `search_journal` | Full-text search across journal entries |
| `get_mood_trend` | Mood (1-5) trend over time with rolling averages |
| `get_journal_insights` | AI-extracted themes and patterns from journal entries |
| `get_journal_correlations` | Correlate journal mood/themes with biometric data |

### Day type analysis (1 tool)
| Tool | Use case |
|------|----------|
| `get_day_type_analysis` | Segment sleep, recovery, nutrition metrics by rest/light/moderate/hard training day |

### Garmin (2 tools)
| Tool | Use case |
|------|----------|
| `get_garmin_summary` | Body Battery, stress, HRV, RHR, respiration over date range |
| `get_device_agreement` | Whoop vs Garmin HRV/RHR cross-validation with agreement thresholds |

### Labs & genome (8 tools)
| Tool | Use case |
|------|----------|
| `get_lab_results` | Blood work results by date or biomarker |
| `get_lab_trends` | Longitudinal biomarker trends across multiple blood draws |
| `get_out_of_range_history` | All out-of-range biomarkers across all draws |
| `search_biomarker` | Search for a specific biomarker across all results |
| `get_genome_insights` | Genome SNP interpretations by category or risk level |
| `get_body_composition_snapshot` | DEXA scan results |
| `get_health_risk_profile` | Combined labs + genome risk assessment |
| `get_next_lab_priorities` | What to test next based on gaps and trends |

### N=1 Experiments (4 tools)
| Tool | Use case |
|------|----------|
| `create_experiment` | Start tracking a protocol change with hypothesis, tags, and start date |
| `list_experiments` | View all active/completed/abandoned experiments |
| `get_experiment_results` | Auto-compare 16 health metrics before vs during experiment period |
| `end_experiment` | Close an experiment with outcome notes and status |

### Health Trajectory (1 tool)
| Tool | Use case |
|------|----------|
| `get_health_trajectory` | Forward-looking projections across weight, biomarkers, fitness, recovery, and metabolic domains with Board of Directors assessment |

### Travel & Jet Lag (3 tools)
| Tool | Use case |
|------|----------|
| `log_travel` | Start or end a trip with destination, timezone, purpose. Huberman jet lag protocol on start |
| `get_travel_log` | List all trips with status filter (active/completed) |
| `get_jet_lag_recovery` | Post-trip recovery analysis: 8 metrics before vs after, days-to-baseline |

### Blood Pressure (2 tools)
| Tool | Use case |
|------|----------|
| `get_blood_pressure_dashboard` | BP status, AHA classification, trend, variability, morning vs evening |
| `get_blood_pressure_correlation` | BP vs 11 lifestyle factors: sodium, caffeine, training, sleep, weight, etc. |

### Supplements (3 tools)
| Tool | Use case |
|------|----------|
| `log_supplement` | Log a supplement or medication with dose, timing, category |
| `get_supplement_log` | Retrieve supplement history with adherence patterns |
| `get_supplement_correlation` | Compare days taking a supplement vs without across health outcomes |

### Weather & Seasonal (1 tool)
| Tool | Use case |
|------|----------|
| `get_weather_correlation` | Correlate 10 weather factors with health/journal metrics |

### Training Periodization (2 tools)
| Tool | Use case |
|------|----------|
| `get_training_periodization` | Mesocycle detection, deload needs, progressive overload, polarization check |
| `get_training_recommendation` | Readiness-based workout suggestion: type, intensity, duration, HR targets |

### Social Connection (2 tools)
| Tool | Use case |
|------|----------|
| `get_social_connection_trend` | Social quality over time (PERMA model), correlation with health metrics |
| `get_social_isolation_risk` | Flag periods of 3+ days without meaningful connection |

### Meditation (1 tool)
| Tool | Use case |
|------|----------|
| `get_meditation_correlation` | Mindful minutes vs HRV, stress, sleep, recovery. Dose-response analysis |

### HR Recovery (1 tool)
| Tool | Use case |
|------|----------|
| `get_hr_recovery_trend` | Post-exercise HR recovery extraction, clinical classification, fitness trajectory |

### Sleep Environment (1 tool)
| Tool | Use case |
|------|----------|
| `get_sleep_environment_analysis` | Eight Sleep temperature vs sleep outcomes. Optimal thermal profile |

### State of Mind (1 tool)
| Tool | Use case |
|------|----------|
| `get_state_of_mind_trend` | How We Feel valence trend, emotion labels, life areas, time-of-day patterns |

### Coaching log (3 tools)
| Tool | Use case |
|------|----------|
| `save_insight` | Save a new insight or hypothesis to the coaching log |
| `get_insights` | List open/acted/resolved insights, flags stale (open ≥7 days) |
| `update_insight_outcome` | Close the loop — record what happened when you acted on an insight |

### Character Sheet (3 tools)
| Tool | Use case |
|------|----------|
| `get_character_sheet` | Current Character Sheet: level, pillar scores, XP, tier, buffs/debuffs, rewards, protocol recs |
| `get_character_history` | Character Sheet records over a date range — level progression, pillar trends |
| `get_character_insights` | Pattern analysis across pillars: weakest pillar, synergies, momentum |

### Social & Behavioral (9 tools)
| Tool | Use case |
|------|----------|
| `log_life_event` | Log a life event (birthday, milestone, conflict, loss) with date and context |
| `get_life_events` | Retrieve life events — Chronicle uses these for narrative context and anomaly explanation |
| `log_contact` | Log a meaningful interaction with a person (call, in-person, text, depth rating) |
| `get_contact_frequency` | Social dashboard: interactions/week, connection diversity, isolation risk |
| `log_temptation` | Log a resist/succumb moment — the only metric that directly measures willpower |
| `get_temptation_trend` | Resist vs succumb ratio over time, patterns by time of day and category |
| `log_exposure` | Log cold/heat exposure (cold shower, sauna, plunge) with duration and type |
| `get_exposure_correlation` | Correlate cold/heat exposure with HRV, State of Mind, sleep quality |
| `get_exercise_variety_score` | Movement pattern diversity index. Flags staleness, suggests novel movement |

### Longevity & Advanced Health (5 tools)
| Tool | Use case |
|------|----------|
| `get_biological_age` | PhenoAge / Levine biological age from blood panels + DEXA + HRV + CGM. Delta from chronological age |
| `get_metabolic_health_score` | Composite metabolic syndrome score from CGM + weight + DEXA + BP + labs. Single trajectory number |
| `get_food_response_database` | Personal food response ranking: which meals spike YOU. Postprandial AUC per meal-type |
| `get_defense_patterns` | Psychological defense mechanism detection from journal enrichment (Haiku pass) |
| `export_data` | Full DynamoDB data dump — all sources → JSON/CSV in S3. Your data, your ownership |

### Board of Directors (3 tools)
| Tool | Use case |
|------|----------|
| `get_board_of_directors` | View all 13 board members with domains, voice, focus areas (filter by name or domain) |
| `update_board_member` | Add or edit a board member’s config (name, domains, voice, principles, features) |
| `remove_board_member` | Soft-delete (archive) or hard-delete a board member |

### Adaptive Mode (1 tool)
| Tool | Use case |
|------|----------|
| `get_adaptive_mode` | Current Daily Brief mode (standard/focused/recovery/momentum) + reasoning and tone config |

---

## Infrastructure Overview

| Component | AWS Service | Purpose |
|-----------|-------------|---------|
| Raw data storage | S3 (`matthew-life-platform`) | Immutable backups, partitioned by source/date |
| Normalized data | DynamoDB (`life-platform`) | Fast queried, single-table design |
| Data ingestion | Lambda (13 ingestion + 1 webhook) | Fetch APIs, parse exports, write to DynamoDB |
| Enrichment | Lambda (2 functions) | Activity enrichment + journal enrichment (Haiku) |
| MCP server | Lambda (`life-platform-mcp`, 1024 MB) | Tool handler for Claude (121 tools, 26-module package, 12 cached) via Lambda Function URL + remote MCP |
| Email delivery | Lambda (7 functions) + SES | Daily brief, weekly/monthly digest, anomaly alerts, nutrition review, Chronicle, Weekly Plate |
| Inbound email | Lambda (`insight-email-parser`) + SES receipt rules | Reply-to-save coaching insights |
| Freshness checker | Lambda (`life-platform-freshness-checker`) | Data staleness monitoring + alerting |
| Web properties | CloudFront + S3 static | `dash.averagejoematt.com` (daily + clinical), `blog.averagejoematt.com` (Chronicle), `buddy.averagejoematt.com` (Tom) |
| Compute Lambdas | Lambda (3 functions) | character-sheet-compute, adaptive-mode-compute, dashboard-refresh (pre-compute before email) |
| Audit trail | CloudTrail (`life-platform-trail`) | Management event logging |
| Secrets | Secrets Manager (6 secrets, consolidated 2026-03-05) | OAuth tokens separate; static keys merged into `life-platform/api-keys` |
| Monitoring | CloudWatch (35 alarms) + SNS | Error alarms on all 29 Lambdas → SNS → email |
| Cost guard | AWS Budget | $20/mo cap, alerts at $5/$10/$20 |

All infrastructure runs in `us-west-2` (account 205930651321). Budget target: under $25/month. Current spend: ~$3/month.

---

## Troubleshooting

**Claude says it has no data for a source**
→ Check `get_sources` to see the available date range. If the source is missing or stale, the Lambda sync may have failed. Check CloudWatch logs for the relevant Lambda function.

**Habit tools returning empty data**
→ Verify `source_of_truth.habits` in DynamoDB profile is set to `habitify`. Check that the Habitify Lambda ran: `aws logs tail /aws/lambda/habitify-data-ingestion --since 24h --region us-west-2`. Note: there is a data gap from 2025-11-10 to 2026-02-22 (no habit data).

**Apple Health data not updating**
→ Check `health-auto-export-webhook` logs (NOT `apple-health-ingestion`). The webhook is the primary data path. Manual XML export via S3 is a fallback for backfills only.

**MacroFactor data not updating**
→ Export from MacroFactor app to Dropbox `/life-platform/` folder. Check `dropbox-poll` Lambda logs to see if the file was detected. Fallback: manually upload CSV to `s3://matthew-life-platform/uploads/macrofactor/`.

**MCP tools not appearing in Claude**
→ Confirm `mcp_bridge.py` is running and configured with the correct Lambda Function URL and API key.

**Data seems wrong or stale**
→ Run `get_latest` to see the most recent record date per source. If a source is more than 2 days behind, check the corresponding Lambda's CloudWatch logs. The freshness checker runs daily at 9:45 AM PT and will email you if any source is overdue.

**Garmin auth failure**
→ Garmin uses OAuth tokens stored in Secrets Manager. If tokens expire, re-run `setup_garmin_auth.py` locally to re-authenticate.

---

## Local Project Files

Located at `~/Documents/Claude/life-platform/`

| File | Purpose |
|------|---------|
| `mcp_server.py` | MCP tool handler (deployed to Lambda, 121 tools across 26 modules) |
| `mcp_bridge.py` | Local MCP bridge configuration |
| `*_lambda.py` | Per-source ingest Lambda functions |
| `daily_brief_lambda.py` | Daily readiness email (18 sections, 4 AI calls) + dashboard JSON |
| `weekly_digest_v2_lambda.py` | Sunday weekly digest (v4.2) |
| `monthly_digest_lambda.py` | Monthly coach's letter |
| `anomaly_detector_lambda.py` | Multi-source anomaly detection (15 metrics), travel-aware |
| `wednesday_chronicle_lambda.py` | Wednesday Chronicle email + blog post (Elena Voss, Sonnet) |
| `weekly_plate_lambda.py` | Friday food magazine email |
| `nutrition_review_lambda.py` | Saturday nutrition review email (Sonnet) |
| `character_sheet_compute_lambda.py` | Daily character sheet scoring (runs 9:35 AM before Daily Brief) |
| `adaptive_mode_compute_lambda.py` | Daily adaptive mode scoring (sets Daily Brief tone) |
| `dashboard_refresh_lambda.py` | Mid-day + evening dashboard refresh (no AI, lightweight) |
| `enrichment_lambda.py` | Activity enrichment (CTL/ATL/TSB computation) |
| `journal_enrichment_lambda.py` | Journal AI enrichment (Haiku) |
| `backfill_*.py` | One-time or manual data backfill scripts |
| `deploy*.sh` | Deployment scripts for each Lambda |
| `seed_*.py` | Manual data seeding (profile, labs, DEXA, genome) |
| `setup_*.py/.sh` | Auth setup and configuration scripts |
| `handovers/` | Session handover notes for continuity |
| `ARCHITECTURE.md` | System architecture (ground truth) |
| `SCHEMA.md` | DynamoDB schema and field reference |
| `RUNBOOK.md` | Operational procedures |
| `PROJECT_PLAN.md` | Roadmap and backlog |
| `CHANGELOG.md` | Version history |
| `USER_GUIDE.md` | This file |
