# Life Platform — Platform Guide

**Version:** v3.7.32 | **Last updated:** 2026-03-15

> Combined guide replacing FEATURES.md and USER_GUIDE.md.
> For system architecture and infrastructure, see ARCHITECTURE.md and INFRASTRUCTURE.md.
> For full MCP tool catalog, see MCP_TOOL_CATALOG.md.
> For DynamoDB field reference, see SCHEMA.md.

---

## What This Is

The Life Platform is a personal health intelligence system that aggregates data from 20 sources (wearables, apps, lab work, DNA, a continuous glucose monitor, and a daily journal), unifies it in a single DynamoDB table, and makes it queryable through natural language conversation with Claude and automated daily email coaching.

You ask questions like *"Am I ready for a hard workout?"* or *"Does alcohol affect my sleep?"* and get answers grounded in your actual data — not generics. The platform also reaches out proactively on a schedule: a morning brief every day, a planning email every Monday, and weekly/monthly digests.

Web dashboard: `https://dash.averagejoematt.com/`

---

## Data Sources (20)

| Source | What It Tracks | Update Method |
|--------|---------------|---------------|
| Whoop | Recovery score, HRV, strain, sleep staging | Daily Lambda (6:00 AM PT) |
| Eight Sleep | Sleep score, efficiency, bed environment, RHR | Daily Lambda (7:00 AM PT) |
| Garmin | Body Battery, stress, HR zones, training load, VO2 max | Daily Lambda (6:00 AM PT) |
| Strava | Running, cycling, hiking, walking + GPS data | Daily Lambda (6:30 AM PT) |
| Withings | Weight, body fat %, lean mass | Daily Lambda (6:15 AM PT) |
| MacroFactor | Calories, macros, micronutrients, meal timing | Phone export → Dropbox → Lambda (30 min poll) |
| Habitify | 65 P40 habits across 9 groups, mood | Daily Lambda (6:15 AM PT) |
| Notion Journal | Daily journal entries (5 templates) + AI enrichment | Daily Lambda (6:00 AM PT) |
| Apple Health | Steps, gait, active calories, caffeine, water | HAE webhook (hourly iOS push) |
| Dexcom Stelo (CGM) | Continuous glucose (5-min readings) | Via Apple Health webhook |
| Todoist | Tasks completed, overdue, project breakdown | Daily Lambda (6:45 AM PT) |
| Function Health + GP | Blood work (107 biomarkers, 7 draws 2019–2025) | Manual seed |
| DEXA | Body composition scan (visceral fat, FFMI, BMD) | Manual seed |
| Genome | 110 SNP clinical interpretations | Manual seed |
| MacroFactor Workouts | Strength training (sets/reps/weight from MF) | Phone export → Dropbox pipeline |
| Weather (Open-Meteo) | Temperature, daylight, pressure, humidity | Daily Lambda (5:45 AM PT) |
| Supplements | Supplement/medication doses, timing, adherence | Manual via `log_supplement` MCP tool |
| State of Mind (How We Feel) | Mood valence, emotions, life area associations | Via Apple Health webhook |
| Google Calendar | Calendar events, meeting load, focus blocks | Daily Lambda (6:30 AM PT) |

---

## Automated Emails

| Email | Schedule (PDT) | What |
|-------|----------------|------|
| **Monday Compass** | Mon 8:00 AM | Weekly planning: tasks by pillar, health state, Board Pro Tips, Keystone action |
| **Anomaly Alert** | Daily 9:05 AM (triggered only) | Multi-source anomaly detection, travel-aware suppression |
| **Daily Brief** | Daily 11:00 AM | 18-section brief with day grade, AI coaching, readiness, habits, CGM, gait, weather |
| **Evening Nudge** | Daily 8:00 PM (only if incomplete) | Completeness reminder for supplements, journal, How We Feel |
| **Freshness Alert** | Daily 10:45 AM (triggered only) | Data source staleness warnings |
| **Wednesday Chronicle** | Wed 8:00 AM | "The Measured Life" by Elena Voss — narrative journalism + blog post |
| **The Weekly Plate** | Fri 7:00 PM | Food magazine email with recipes and Met Market grocery list |
| **Weekly Digest** | Sun 9:00 AM | 7-day summary, day grade trends, Board commentary, clinical JSON |
| **Nutrition Review** | Sat 10:00 AM | 3-expert panel weekly nutrition analysis (Sonnet) |
| **Monthly Coach's Letter** | 1st Mon 9:00 AM | 30-day vs prior-30 deltas, annual goals, expert panel |

---

## Feature Guide by Domain

### Daily Intelligence

**Daily Brief (v2.82, 18 sections)** — arrives 11:00 AM daily:
- Letter grade for yesterday (A+ through F) from 8 weighted components
- AI-generated TL;DR one-liner
- Readiness signal (GREEN / YELLOW / RED) for today's training
- Sleep architecture (deep %, REM %, efficiency, WASO)
- Training report with workout details and AI commentary
- Nutrition scorecard with macro progress
- Habit Intelligence: tier-weighted scoring (T0 non-negotiable 3×, T1 high-priority 1×, T2 aspirational 0.5×), per-habit chips, vice streak tracking
- Supplement adherence chips (7-day per-supplement)
- Blood glucose spotlight (fasting proxy, 7-day trend, hypo alerts)
- Walking speed and gait health
- Weather context with coaching nudges
- Travel banner with Huberman jet lag protocol (when traveling)
- Blood pressure with AHA classification (when available)
- Weight phase progress
- Board of Directors AI coaching panel
- 3–4 specific personalized guidance recommendations

**Anomaly Detection (v2.1)** — 9:05 AM daily:
Monitors 15 metrics across 7 sources with CV-based adaptive thresholds and 30-day rolling baseline. Travel-aware (suppresses alerts while traveling). Alerts only when 2+ sources show unusual readings simultaneously.

### Sleep

Tools: `get_sleep_analysis` | Questions: *"How is my sleep quality?"*, *"Do I have social jetlag?"*, *"How much sleep debt do I have?"*

- Clinical-grade sleep analysis: architecture (REM/deep/light %), efficiency, WASO, circadian timing
- Social jetlag detection — weekday vs weekend midpoint comparison, flags >1 hour gap
- Sleep debt tracking — rolling 7-day and 30-day deficit
- Respiratory rate screening with clinical alert thresholds
- Correlation analysis: exercise timing, alcohol, caffeine vs sleep quality

### Fitness & Training

Tools: `get_training`, `get_readiness_score`, `get_zone2_breakdown`, `search_activities`, `get_weekly_summary` | Questions: *"Am I overtraining?"*, *"What's my Zone 2 trend?"*, *"What should I do today?"*

- **Readiness score** — unified 0-100 from Whoop recovery (35%), Eight Sleep (25%), HRV trend (20%), TSB (10%), Garmin Body Battery (10%)
- **Training load** — Banister CTL/ATL/TSB, ACWR injury risk, monotony detection
- **Zone 2 tracking** — weekly minutes vs 150 min/week target, polarization alerts
- **Periodization** — mesocycle detection (base/build/peak/deload), 80/20 compliance
- **Activity search** — find any workout by name, type, distance, elevation with all-time percentile rank
- **Day type analysis** — classifies rest/light/moderate/hard/race days, compares sleep/recovery/nutrition across types

### Strength

Tools: `get_strength`, `get_centenarian_benchmarks`, `get_exercise_history`, `get_muscle_volume` | Questions: *"What are my PRs?"*, *"Am I on track for my 80s?"*, *"Am I training chest enough?"*

- PRs by estimated 1RM, muscle volume vs MEV/MAV/MRV landmarks
- Bodyweight-relative strength classification (Novice through Elite)
- Progression tracking with plateau detection
- **Centenarian decathlon benchmarks** — Peter Attia's longevity strength targets: deadlift 2.0×BW, squat 1.75×, bench 1.5×, OHP 1.0×

### Nutrition

Tools: `get_nutrition`, `get_food_log` | Questions: *"Am I hitting my protein goal?"*, *"Which foods spike my glucose?"*, *"What's my eating window?"*

- Daily macro breakdown and rolling averages
- Protein distribution score (% of meals ≥30g protein — MPS threshold)
- Micronutrient sufficiency across 25+ nutrients vs RDA and longevity targets
- Eating window analysis: first/last bite, circadian alignment, last-bite-to-sleep gap
- Meal-by-meal food log with timestamps and per-item macros
- Caffeine cutoff finder: personal half-life analysis, dose-response vs sleep quality

### Blood Glucose (CGM)

Tools: `get_cgm`, `get_glucose_meal_response` | Questions: *"What's my fasting glucose?"*, *"How accurate is my CGM?"*, *"Which meals spike me most?"*

- Daily average, time in range (70–180), time in optimal (70–120, Attia), variability, fasting proxy
- Levels-style postprandial analysis: spike magnitude, time to peak, AUC, letter grade per meal
- Fasting glucose validation against venous lab draws

### Weight & Body Composition

Tools: `get_weight_loss_progress`, `get_body_composition_trend` | Questions: *"Am I losing fat or muscle?"*, *"When will I reach goal weight?"*

- Weekly rate of loss, BMI milestones, plateau detection, phase progress
- Fat mass vs lean mass over time — 14-day rolling deltas to catch muscle loss
- DEXA results: FFMI, visceral fat, BMD, android/gynoid ratio
- Energy balance: Apple Watch TDEE vs MacroFactor intake, daily deficit/surplus

### Labs & Genetics

Tools: `get_labs`, `get_genome_insights`, `get_health` (risk_profile) | Questions: *"What's my LDL trend?"*, *"What should I test next?"*

- 7 blood draws, 107 biomarkers (2019–2025), trend slopes, ASCVD risk score
- Out-of-range persistence classification (chronic / recurring / occasional)
- 110 SNP interpretations across 14 categories, cross-referenced with labs and nutrition
- Next lab priorities based on genetic risk and persistent flags

### Gait & Mobility

Tools: `get_gait_analysis`, `get_daily_metrics` | Questions: *"How's my walking speed?"*, *"Am I at fall risk?"*

- Walking speed (strongest all-cause mortality predictor; flag <2.24 mph)
- Step length, asymmetry (flag ≥5%), double support time (fall risk proxy)
- NEAT analysis, step target tracking, sedentary day flags

### Journal & Mental Health

Tools: `get_journal_entries`, `search_journal`, `get_mood`, `get_journal_insights` | Questions: *"What patterns do you see in my journal?"*, *"How has my mood been?"*

- 5 journal templates (morning, evening, stressor, health event, weekly) captured in Notion
- AI enrichment via Claude Haiku: mood/energy/stress scores, emotions, CBT cognitive patterns, ownership, social quality, avoidance flags, values lived
- Full-text search across all entries by keyword, theme, or enriched field

### Habits (P40)

Tools: `get_habits`, `get_habit_registry` | Questions: *"What's my longest streak?"*, *"Which habits drive my day grade?"*, *"How are my Tier 0 habits?"*

- 65 habits, 9 groups: Tier 0 (non-negotiable, 3× weight), Tier 1 (high priority), Tier 2 (aspirational)
- Keystone habits — Pearson correlation of each habit vs overall P40 score
- Vice tracking — 5 monitored vices with streak history
- Habit stacks — co-occurrence analysis, natural morning routines

### Behavioral & Longevity

- **N=1 experiments** — formally track protocol changes with a hypothesis, auto-compare 16 metrics before vs during
- **Temptation logging** — resist/succumb moments, the only metric that directly measures willpower
- **Cold/heat exposure** — log sessions, correlate with HRV and State of Mind
- **Social connection** — meaningful vs surface interactions, isolation risk, PERMA wellbeing model
- **Character Sheet** — RPG-style 7-pillar scoring (Level 1–100): Sleep 20%, Movement 18%, Nutrition 18%, Mind 15%, Metabolic 12%, Consistency 10%, Relationships 7%
- **Decision journal** — log platform-guided decisions, track follow vs override, build trust calibration

---

## Natural Language Query Guide

The fastest way to use the platform. Claude calls the appropriate tool automatically.

### Readiness & Recovery
- *"Am I ready for a hard session today?"* → `get_readiness_score`
- *"How was my recovery this week?"* → `get_health` (dashboard)
- *"Do my Whoop and Garmin agree?"* → `get_readiness_score` (device_agreement)

### Weight & Body
- *"How is my weight loss going?"* → `get_weight_loss_progress`
- *"Am I losing fat or muscle?"* → `get_body_composition_trend`
- *"When will I reach goal weight?"* → `get_weight_loss_progress`
- *"What does my DEXA say?"* → `get_health` (risk_profile)

### Training & Fitness
- *"What were my biggest training weeks?"* → `get_weekly_summary`
- *"How fit am I right now?"* → `get_training` (load)
- *"Am I overtraining?"* → `get_training` (load) with ACWR
- *"What's my longest run ever?"* → `search_activities`
- *"How much Zone 2 am I getting?"* → `get_zone2_breakdown`
- *"Do I need a deload?"* → `get_training` (periodization)
- *"What should I do today?"* → `get_training` (recommendation)

### Strength
- *"What are my all-time PRs?"* → `get_strength` (prs)
- *"Am I on track for my 80s?"* → `get_centenarian_benchmarks`
- *"Am I training chest enough?"* → `get_muscle_volume`
- *"How has my bench progressed?"* → `get_exercise_history`

### Sleep
- *"How has my sleep been?"* → `get_sleep_analysis`
- *"Do I have sleep debt?"* → `get_sleep_analysis`
- *"Does exercise affect my sleep?"* → `get_exercise_sleep_correlation`
- *"Does alcohol hurt my sleep?"* → `get_alcohol_sleep_correlation`

### Nutrition
- *"Am I hitting my protein goal?"* → `get_nutrition` (macros)
- *"What did I eat yesterday?"* → `get_food_log`
- *"Am I getting enough omega-3?"* → `get_nutrition` (micronutrients)
- *"What's my eating window?"* → `get_nutrition` (meal_timing)

### Blood Glucose
- *"What's my fasting glucose trend?"* → `get_cgm` (fasting)
- *"Which meals spike my glucose?"* → `get_glucose_meal_response`
- *"Does exercise lower my blood sugar?"* → `get_glucose_exercise_correlation`

### Habits
- *"How are my habits?"* → `get_habits` (dashboard)
- *"What's my longest meditation streak?"* → `get_habits` (streaks)
- *"Which habits drive my day grade?"* → `get_habits` (keystones)
- *"How are my Tier 0 habits?"* → `get_habits` (tiers)

### Labs & Genome
- *"What were my latest blood results?"* → `get_labs` (results)
- *"What's trending in my biomarkers?"* → `get_labs` (trends)
- *"What should I test next?"* → `get_next_lab_priorities`
- *"What do my genetics say about caffeine?"* → `get_genome_insights`

### Journal & Mood
- *"What patterns do you see in my journal?"* → `get_journal_insights`
- *"Search my journal for stress entries"* → `search_journal`
- *"How has my mood been trending?"* → `get_mood`

### Historical & Cross-Source
- *"How does my fitness now compare to last year?"* → `compare_periods`
- *"What month do I train most?"* → `get_longitudinal_summary` (seasonal)
- *"Does high protein predict better recovery?"* → `get_cross_source_correlation`
- *"What are my all-time bests?"* → `get_longitudinal_summary` (records)
- *"Show my health trajectory"* → `get_health` (trajectory)

### Supplements & Experiments
- *"Log 500mg magnesium before bed"* → `log_supplement`
- *"Is magnesium helping my sleep?"* → `get_supplement_correlation`
- *"Start a no-caffeine-after-10am experiment"* → `create_experiment`
- *"How is my caffeine experiment going?"* → `get_experiment_results`

### Travel & Weather
- *"I'm flying to London"* → `log_travel`
- *"How did I recover from my trip?"* → `get_jet_lag_recovery`
- *"Does barometric pressure affect my recovery?"* → `get_weather_correlation`

### Calendar & Productivity
- *"What's on my calendar today?"* → `get_calendar_events`
- *"Do I have a heavy week?"* → `get_schedule_load`
- *"Which tasks did I complete yesterday?"* → `get_todoist_snapshot` (today)

---

## Updating Data

### Automatic (no action needed)
Whoop, Withings, Strava, Eight Sleep, Todoist, Garmin, Habitify, Notion, Apple Health (CGM, gait, energy), Google Calendar, and Weather all sync automatically. All data is typically available by 8 AM PT.

### MacroFactor (Dropbox zero-touch)
1. MacroFactor app → More → Data Management → Data Export → Granular Export → Food diary → All time → Export
2. Save to Dropbox `/life-platform/` folder
3. `dropbox-poll` Lambda detects it within 30 minutes → copies to S3 → triggers ingestion
4. Same pipeline handles workout exports (detected by "Exercise" header vs "Food Name")

### Apple Health (mostly automatic)
Health Auto Export app runs in background hourly. **Must be set to hourly sync** — "since last run" causes the payload to grow too large and silently drops metrics (water, caffeine disappear first). For deep backfills: Health app → Export All Health Data → upload to `s3://matthew-life-platform/imports/apple_health/`.

### Supplements
Log via MCP: `log_supplement name="Magnesium Glycinate" dose=400 unit="mg" timing="before_bed"`.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Claude says no data for a source | Lambda sync failed or date range is outside available data | `get_sources` to check ranges; check CloudWatch logs for the Lambda |
| Habit tools returning empty | Habitify Lambda not run or wrong SOT | `aws logs tail /aws/lambda/habitify-data-ingestion --since 24h` |
| Apple Health not updating | HAE app sync interval too long | Check app is on hourly sync; force manual push |
| MacroFactor stale | CSV not exported to Dropbox | Export from MF app to Dropbox `/life-platform/` folder |
| Withings data gap | OAuth token expired | `python3 setup/fix_withings_oauth.py` |
| Daily Brief missing sections | Compute Lambda failed upstream | Check `daily-metrics-compute` CloudWatch logs |
| MCP tool timeout | Query scans too much data | Narrow date range; use summary tools for multi-year windows |
| Data freshness alert firing | Source hasn't updated >48h | Check source Lambda logs; may need manual backfill |
