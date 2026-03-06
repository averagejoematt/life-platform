# Life Platform — Features & Capabilities

**Version:** v2.72.0 | **Last updated:** 2026-03-05

> This document describes everything the Life Platform can do, organized for two audiences:
> **Part 1** is for anyone — what does this system do for you, organized by life domain.
> **Part 2** is for engineers and architects — how it works under the hood.

---

# Part 1: What It Does (Non-Technical)

The Life Platform is a personal health intelligence system that collects data from 19 sources (wearables, apps, lab work, DNA, a continuous glucose monitor, and a daily journal), unifies it in one place, and makes it accessible through natural language conversation with Claude and automated daily email coaching.

You can also view a real-time web dashboard at `https://dash.averagejoematt.com/` alongside conversational access through Claude.

You don't need to open dashboards, export CSVs, or learn a query language. You ask questions like *"Am I ready for a hard workout?"* or *"Does alcohol affect my sleep?"* and get answers grounded in your actual data.

---

## 🏥 Daily Health Intelligence

**Morning Briefing (Daily Brief v2.62)** — An 18-section email arrives at 10:00 AM every morning with:
- A letter grade for yesterday (A+ through F) based on 8 weighted components
- A one-line AI-generated TL;DR of your top insight
- A readiness score (GREEN / YELLOW / RED) for today's training
- Sleep architecture breakdown (deep sleep %, REM %, efficiency)
- Training report with workout details and AI commentary
- Nutrition scorecard with macro progress bars
- Habit Intelligence: tier-weighted scoring (T0 non-negotiable 3x, T1 high priority 1x, T2 aspirational 0.5x), per-habit red/green chips, vice streak tracking, synergy group alerts
- Supplement adherence chips (7-day per-supplement tracking)
- Blood glucose spotlight (fasting proxy, 7-day trend, hypo alerts)
- Walking speed and gait health metrics
- Weather context with coaching nudges (temperature, daylight, pressure)
- Travel banner with Huberman jet lag protocol (when traveling)
- Blood pressure reading with AHA classification (when data available)
- Weight phase progress toward your goal
- AI coaching from a "Board of Directors" panel of expert personas
- Personalized guidance: 3-4 specific recommendations for today

The brief also writes a `data.json` file to S3, powering a real-time web dashboard.

**Anomaly Detection (v2.1)** — A separate system monitors 15 metrics across 7 data sources every morning. Uses adaptive thresholds based on rolling 30-day history with per-metric CV-based Z-score thresholds. Travel-aware: when you're on a trip, anomalies are recorded but alerts are suppressed (you don't need an email telling you your steps dropped while on a transatlantic flight). When two or more sources show unusual readings simultaneously (e.g., HRV crashed AND sleep score dropped AND resting heart rate spiked), it generates a root-cause hypothesis and sends an alert. Single-source anomalies are recorded but don't trigger alerts to avoid noise.

**Weekly Digest** — Every Sunday morning: 7-day trends, day grade distribution, Board of Advisors commentary, open coaching insights that need follow-up, and a 12-week trajectory assessment.

**Monthly Coach's Letter** — First Monday of each month: 30-day vs prior period deltas, annual goal progress bars, and an expert panel review of your trajectory.

---

## 😴 Sleep

Ask questions like: *"How is my sleep quality?"*, *"Do I have social jetlag?"*, *"Is my sleep consistent?"*

- **Clinical-grade sleep analysis** from Eight Sleep pod data: architecture percentages (REM, deep, light), sleep efficiency with CBT-I flagging, WASO (wake after sleep onset), and circadian timing
- **Social jetlag detection** — compares weekday vs weekend sleep midpoints; flags when the gap exceeds 1 hour
- **Sleep debt tracking** — rolling 7-day and 30-day deficit against your target (7.5 hours)
- **Sleep onset consistency** — rolling 7-day standard deviation; flags when variability exceeds 60 minutes (social jetlag territory)
- **Respiratory rate screening** — trends respiratory rate from Eight Sleep with clinical alert thresholds
- **Correlation analysis** — how does exercise timing, alcohol, caffeine, or glucose affect your sleep? Each has a dedicated tool that buckets your data and computes personal correlations

---

## 🏃 Fitness & Training

Ask questions like: *"Am I overtraining?"*, *"What's my Zone 2 trend?"*, *"How does my bench press compare to standards?"*

- **Readiness score** — unified 0-100 score from Whoop recovery (35%), Eight Sleep sleep quality (25%), HRV trend (20%), training stress balance (10%), and Garmin Body Battery (10%). GREEN / YELLOW / RED signal with specific training recommendation
- **Training load management** — Banister fitness-fatigue model (CTL, ATL, TSB), acute-to-chronic workload ratio with injury risk classification, training monotony detection
- **Zone 2 tracking** — weekly Zone 2 minutes against the 150 min/week longevity target, training zone distribution, polarization alerts
- **Activity search** — find any workout by name, type, distance, or elevation. Percentile ranking against your entire history
- **Strength tracking** — personal records by estimated 1RM, muscle volume per group vs MEV/MAV/MRV, bodyweight-relative strength classification (novice through elite), progression tracking with plateau detection
- **Exercise timing analysis** — does working out in the evening hurt your sleep? Buckets exercise end times into time-of-day windows and compares same-night sleep quality
- **Day type segmentation** — classifies each day as rest/light/moderate/hard/race, then compares average sleep, recovery, and nutrition across day types

---

## 🥗 Nutrition

Ask questions like: *"Am I hitting my protein goal?"*, *"What's my eating window?"*, *"Which foods spike my glucose?"*

- **Macro tracking** — daily calories, protein, fat, carbs against personalized targets with hit rate over time
- **Protein distribution score** — what percentage of your meals hit ≥30g protein (the leucine threshold for muscle protein synthesis)
- **Micronutrient sufficiency** — 5 key nutrients (fiber, potassium, magnesium, vitamin D, omega-3) scored against Board of Directors consensus targets, with per-nutrient percentage
- **25-nutrient micronutrient report** — scored against RDA and longevity-optimal targets, flags chronic deficiencies, omega-6:omega-3 ratio
- **Eating window analysis** — first bite, last bite, window duration, caloric distribution by time of day, gap between last bite and sleep onset
- **Meal-by-meal food log** — every food entry with timestamps and per-item macros
- **Nutrition-biometrics correlations** — does high protein predict better recovery? Does caffeine suppress sleep efficiency? Personal Pearson correlations between 10 nutrition metrics and 9 biometric outcomes
- **Caffeine cutoff finder** — personal caffeine half-life analysis, dose-response curves, timing buckets vs sleep quality
- **Alcohol impact analysis** — dose buckets (none / light / moderate / heavy), drinking vs sober sleep comparison, HRV and recovery impact

---

## 📊 Blood Glucose (CGM)

Ask questions like: *"What's my fasting glucose trend?"*, *"Does exercise lower my blood sugar?"*, *"How accurate is my CGM?"*

- **CGM dashboard** — daily average, time in range (70-180), time in optimal range (70-120, per Peter Attia), variability, fasting proxy, hypoglycemia flags
- **Glucose meal response** — Levels-style postprandial analysis: for each meal logged, computes spike magnitude, time to peak, AUC, return to baseline, and a letter grade (A through F). Identifies best and worst meals, per-food scores, and macro correlations
- **Glucose-sleep correlation** — buckets evening glucose levels and compares against same-night sleep quality
- **Glucose-exercise correlation** — compares exercise vs rest day glucose, intensity analysis, duration correlations
- **Fasting glucose validation** — compares CGM overnight nadir against venous lab draws with statistical analysis and bias assessment
- Data from Dexcom Stelo continuous glucose monitor via Apple Health

---

## ⚖️ Weight & Body Composition

Ask questions like: *"Am I losing fat or muscle?"*, *"When will I reach my goal weight?"*, *"What's my DEXA say?"*

- **Weight loss progress** — weekly rate of loss, BMI milestones, plateau detection, phase progress (4-phase plan from 302→185 lbs)
- **Body composition trending** — fat mass vs lean mass over time, 14-day rolling deltas to catch muscle loss during a cut
- **DEXA scan results** — FFMI, visceral fat category, bone mineral density, android/gynoid ratio, posture assessment, Withings delta since scan
- **Energy balance** — Apple Watch TDEE (real wearable measurement, not formula) vs MacroFactor intake, daily surplus/deficit, implied weekly weight change
- **Non-scale victories** — fitness improvements independent of what the scale says

---

## 🧬 Labs & Genetics

Ask questions like: *"What's my LDL trend?"*, *"What should I test next?"*, *"What does my genome say about vitamin D?"*

- **Blood work results** — 7 draws across 6 years (2019-2025), 107 unique biomarkers from Function Health and GP panels
- **Biomarker trending** — longitudinal trajectory with slope per year, 1-year projection, derived ratios (TG/HDL, non-HDL, TC/HDL)
- **Out-of-range tracking** — persistence classification (chronic, recurring, occasional) with genome-driven explanations
- **ASCVD risk score** — 10-year cardiovascular risk via Pooled Cohort Equations, computed from lab values
- **Genome insights** — 110 SNP clinical interpretations across 14 categories, cross-referenced with lab results and nutrition
- **Next lab priorities** — what to test next based on genetic risk, persistent flags, and gaps in coverage
- **Health risk profile** — unified cardiovascular, metabolic, and longevity risk assessment combining labs, genome, DEXA, and wearable HRV

---

## 🚶 Gait & Mobility

Ask questions like: *"How's my walking speed?"*, *"Am I at risk for a fall?"*, *"How much am I moving?"*

- **Gait analysis** — walking speed (strongest all-cause mortality predictor; clinical flag below 2.24 mph), step length (earliest aging marker), asymmetry (injury indicator; flags ≥5%), double support time (fall risk proxy). Composite score 0-100
- **Movement score** — NEAT analysis (non-exercise activity thermogenesis), step target tracking, sedentary day flags
- **Energy balance** — total daily energy expenditure from Apple Watch vs food intake

---

## 📓 Journal & Mental Health

Ask questions like: *"What patterns do you see in my journal?"*, *"How has my mood been trending?"*, *"What am I consistently avoiding?"*

- **5 journal templates** — Morning Check-In, Evening Reflection, Stressor Deep-Dive, Health Event, Weekly Reflection. Captured in Notion, ingested daily
- **AI enrichment** — Claude Haiku reads each entry and extracts: mood/energy/stress (normalized 1-5), emotions (granular vocabulary), themes, cognitive patterns (clinical CBT terms like catastrophizing, rumination, reframing), avoidance flags, ownership score (locus of control), social quality, flow indicators, values lived, and a notable quote
- **Mood trending** — mood, energy, and stress over time with 7-day rolling averages, trend direction, and recurring themes at peaks and valleys
- **Pattern analysis** — recurring themes, dominant emotions, cognitive pattern frequency, avoidance flags, ownership trend, values alignment, social connection quality, flow state frequency, gratitude patterns
- **Journal-wearable correlations** — does subjective mood correlate with HRV? Do high-stress journal days predict poor recovery? Finds divergences where subjective experience doesn't match objective data
- **Full-text search** — search across all entries by keyword, theme, emotion, body area, or any enriched field

---

## ✅ Habits

Ask questions like: *"What's my longest meditation streak?"*, *"Which habits correlate most with high day grades?"*, *"Am I doing enough Recovery habits?"*

- **65 habits** tracked across 9 groups (Data, Discipline, Growth, Hygiene, Nutrition, Performance, Recovery, Supplements, Wellbeing) via Habitify app
- **Habit Intelligence (v2.47.0)** — tier-weighted scoring system: Tier 0 (7 non-negotiable habits, 3x weight), Tier 1 (22 high priority, 1x weight), Tier 2 (36 aspirational, 0.5x weight). Each habit has scientific mechanism, personal context (`why_matthew`), synergy groups, and applicable days. 8 synergy groups (Sleep Stack, Morning Routine, Recovery Stack, etc.)
- **Habit registry** — browse all 65 habits with full metadata, filter by tier or category
- **Tier-weighted reports** — composite scoring, T0/T1/T2 completion breakdown, synergy group analysis
- **Vice tracking** — 5 monitored vices with streak tracking, 90-day lookback
- **Adherence rates** — per-habit and per-group completion percentages over any time window
- **Streak tracking** — current streak, longest streak, days since last completion for every habit
- **Keystone habits** — which habits correlate most with your overall P40 score
- **Habit-health correlations** — correlate any habit against any biometric outcome (e.g., cold shower → next-day HRV)
- **Habit stacks** — co-occurrence analysis showing which habits cluster together
- **Period comparison** — side-by-side adherence across two date ranges

---

## 📈 Garmin Biometrics

Ask questions like: *"What's my Body Battery trend?"*, *"How stressed have I been?"*, *"Do Whoop and Garmin agree on my HRV?"*

- **Garmin summary** — Body Battery (0-100 energy), physiological stress (calm through very stressful), HRV, RHR, respiration, training load, readiness, fitness age, VO2 max estimate
- **Device agreement** — Whoop vs Garmin cross-validation for HRV and RHR with agreement thresholds, highlighting when devices diverge

---

## 🔍 Cross-Cutting Analysis

Ask questions like: *"How does my fitness now compare to last year?"*, *"What month do I train most?"*, *"Show me my all-time records."*

- **Period comparison** — side-by-side analysis of any two date ranges across all sources
- **Seasonal patterns** — month-by-month averages across all years of data
- **Cross-source correlations** — Pearson correlation between any two metrics from any sources
- **Personal records** — all-time bests across every tracked metric
- **Coaching log** — save insights and hypotheses, track which are open/acted/resolved, get nudged when insights go stale
- **N=1 experiments** — formally track protocol changes (supplement, diet shift, sleep tweak) with a hypothesis, then auto-compare 16 health metrics before vs during the experiment. Board of Directors evaluates results
- **Health trajectory** — forward-looking intelligence: where are you headed? Weight goal date projection, biomarker slope extrapolation with threshold warnings, fitness volume trends, recovery trajectory, and metabolic trends from CGM data

---

## 💊 Supplements

Ask questions like: *"What supplements am I taking?"*, *"Is magnesium helping my sleep?"*, *"Am I consistent with creatine?"*

- **Manual supplement logging** via MCP tool — log name, dose, unit, timing (morning/with_meal/before_bed/post_workout), and category (supplement/medication/vitamin/mineral)
- **Adherence tracking** — per-supplement consistency percentage over any time window, daily log history
- **Supplement-outcome correlations** — compare days taking a supplement vs days without across recovery, sleep, HRV, glucose, and stress metrics
- **Daily Brief integration** — today's logged supplements with 7-day adherence chips per supplement

---

## 🌤️ Weather & Seasonal

Ask questions like: *"Does weather affect my sleep?"*, *"How does daylight correlate with my mood?"*, *"Does barometric pressure affect my recovery?"*

- **Seattle daily weather data** from Open-Meteo (WMO-grade, free API): temperature, humidity, precipitation, daylight hours, sunshine hours, barometric pressure, UV index, wind speed
- **Weather-health correlations** — Pearson correlations between 10 weather factors and health/journal metrics (recovery, HRV, sleep, stress, Body Battery, mood, energy)
- **Seasonal pattern detection** — identifies how Seattle's seasonal daylight changes (Huberman: master circadian lever) affect your health metrics
- **Daily Brief integration** — weather context tile with coaching nudges (e.g., low daylight = light therapy reminder)

---

## ✈️ Travel & Jet Lag

Ask questions like: *"I'm traveling to London"*, *"How did I recover from my trip?"*, *"Show my travel history"*

- **Trip logging** with destination, timezone, and purpose — auto-computes timezone offset and eastbound/westbound direction
- **Huberman jet lag protocol** — on trip start, provides personalized light exposure timing, melatonin window, meal timing, and exercise recommendations based on timezone direction and offset
- **Post-trip recovery analysis** — compares 7-day pre-trip baseline to post-return recovery curve across 8 metrics (HRV, recovery, sleep, stress, Body Battery, steps). Shows days-to-baseline per metric
- **Travel-aware anomaly detection** — anomaly detector checks travel partition before alerting; suppresses alerts during travel to avoid noise
- **Daily Brief travel banner** — when traveling, shows jet lag protocol coaching in the daily brief

---

## 🩸 Blood Pressure

Ask questions like: *"What's my blood pressure?"*, *"Does sodium affect my BP?"*, *"Am I hypertensive?"*

- **BP dashboard** — latest reading, AHA classification (normal/elevated/stage1/stage2/crisis), 30-day trend, variability analysis (SD >12 mmHg systolic = independent cardiovascular risk factor)
- **Morning vs evening patterns** — individual readings stored in S3 for time-of-day analysis
- **11-factor correlation analysis** — Pearson r for systolic/diastolic vs sodium, calories, caffeine, training, stress, sleep, weight, and more. Exercise vs rest day comparison. Sodium dose-response buckets
- **Anomaly detector integration** — BP systolic/diastolic monitored with minimum absolute change filters
- Data path: BP cuff → Apple Health → Health Auto Export webhook

---

## 😊 State of Mind

Ask questions like: *"How has my mood been?"*, *"What emotions am I feeling most?"*, *"Valence trend this month?"*

- **How We Feel integration** — quantitative mood signal via Apple HealthKit State of Mind data type. Captures momentary emotions and daily moods with valence scores (-1 to +1), emotion labels, and life area associations
- **Valence trending** — overall trend, 7-day rolling average, time-of-day patterns, best/worst days, classification distribution
- **Life area analysis** — valence breakdown by life area (work, health, relationships, etc.) and top emotion labels
- Complements the qualitative depth of Notion journal + Haiku enrichment with quantitative, HealthKit-native mood signal

---

## 🏋️ Training Periodization

Ask questions like: *"Do I need a deload?"*, *"Am I overtraining?"*, *"What should I do today?"*

- **Mesocycle detection** — analyzes weekly training patterns to identify base/build/peak/deload phases
- **Deload recommendations** — Galpin 3:1 or 4:1 ratio monitoring, progressive overload tracking
- **Training polarization** — Seiler 80/20 model compliance check, Zone 3 "no man's land" warnings
- **Readiness-based workout recommendation** — synthesizes Whoop recovery, Eight Sleep quality, Garmin Body Battery, training load (CTL/ATL/TSB), and muscle group recency into a specific workout suggestion: type, intensity, duration, HR targets, and muscle groups
- **Injury risk warnings** — ACWR alerts, consecutive training day flags, sleep debt warnings

---

## 🤝 Social Connection

Ask questions like: *"How are my social connections?"*, *"Am I socially isolated?"*, *"Does connection affect my recovery?"*

- **Social connection quality trend** — tracks enriched social quality from journal entries (alone/surface/meaningful/deep) with rolling averages and PERMA wellbeing model context
- **Social isolation risk detection** — flags periods of 3+ consecutive days without meaningful social connection, correlates isolation episodes with health metric declines
- **Health correlations** — social quality correlated with recovery, HRV, sleep, stress (Seligman: relationships are the #1 predictor of sustained wellbeing)

---

## 🧘 Meditation & Breathwork

Ask questions like: *"Does meditation help my HRV?"*, *"How consistent is my practice?"*, *"Meditation dose-response?"*

- **Mindful minutes tracking** from Apple Health — meditation vs non-meditation day comparisons across HRV, stress, sleep, recovery, Body Battery
- **Dose-response analysis** — do longer sessions produce bigger effects?
- **Next-day effects** — does today's meditation improve tomorrow's recovery?
- **Streak tracking** and consistency analysis

---

## ❤️ Heart Rate Recovery

Ask questions like: *"How's my HR recovery trend?"*, *"Am I getting fitter?"*, *"Post-exercise HR drop?"*

- **Post-peak HR recovery extraction** from Strava activity streams — strongest exercise-derived mortality predictor (Cole et al., NEJM)
- **Clinical classification** — >25 excellent, 18-25 good, 12-18 average, <12 abnormal
- **Sport-type breakdown** and cooldown vs no-cooldown comparison
- **Longitudinal fitness trajectory** — trends over time with best/worst sessions

---

## 🎮 Character Sheet — Gamified Life Score (v2.58.0)

- **Persistent Character Level** (1-100) computed daily from 7 weighted pillars: Sleep (20%), Movement (18%), Nutrition (18%), Mind (15%), Metabolic Health (12%), Consistency (10%), Relationships (7%)
- **Each pillar** has 4-6 weighted components mapped to real data (e.g., Sleep pillar = duration score + efficiency score + deep sleep % + REM % + consistency + sleep debt)
- **EMA smoothing** — 21-day exponentially-weighted rolling average prevents day-to-day noise from dominating scores
- **Anti-flip-flop leveling** — Level up requires 5 consecutive days above threshold, level down requires 7 days below. Tier transitions require 7 up / 10 down. Target: ~2-4 level events per month
- **5 named tiers:** Foundation 🔨 (1-20) → Momentum 🔥 (21-40) → Discipline ⚔️ (41-60) → Mastery 🏆 (61-80) → Elite 👑 (81-100)
- **XP system** — earn +3/+2/+1/0/-1 XP daily per pillar based on raw score bands
- **Cross-pillar effects** — Sleep Drag (sleep <35 debuffs movement/mind), Training Boost (exercise >60 buffs mind), Synergy Bonus (3+ pillars at Discipline+), and more
- **3 MCP tools:** `get_character_sheet` (overview + sparklines), `get_pillar_detail` (component breakdown), `get_level_history` (timeline of events)
- **Config:** All weights, thresholds, and effects stored in `config/character_sheet.json` (S3), editable without redeploy
- **Baseline:** Feb 22, 2026 at Level 1 (302lb). Nutrition composition sub-score maps linearly from 302lb (0%) to 185lb goal (100%)

---

## 🎨 Pixel Art Avatar System (v2.65.0)

- **48 PNG sprites** generated via Python/Pillow: 15 base characters (5 tiers × 3 body frames), 21 pillar badges, 6 effects, 1 crown, 5 email composites
- **Tier progression** reflected visually: Foundation (black hoodie, slouched) → Momentum (grey tee, straightening) → Discipline (blue performance, tall) → Mastery (charcoal henley, smile) → Elite (emerald shirt, crown)
- **Body frame** morphs based on weight progress toward goal (302→260 / 259→215 / 214→185 lbs)
- Hosted on CloudFront CDN, rendered on dashboard and buddy page with `image-rendering: pixelated` upscaling

---

## 💻 Web Dashboard

- **Daily Dashboard** at `https://dash.averagejoematt.com/` — mobile-first, dark mode, 6 tiles with sparklines, radar chart (7 pillar scores), pixel art avatar, auto-refresh every 30 minutes. Data written by Daily Brief Lambda + refreshed at 2 PM and 6 PM by Dashboard Refresh Lambda
- **Clinical Summary** at `https://dash.averagejoematt.com/clinical.html` — white-background, print-optimized, 9 sections designed for doctor visits. Vitals, DEXA, Labs (full biomarker table + persistent flags), Supplements, Sleep, Activity, Glucose, Genome. Updated weekly by Sunday Digest Lambda
- **Dashboard Refresh Lambda** (v2.66.0) — lightweight intraday refresh at 2 PM and 6 PM PT. Re-queries weight, glucose, zone2, TSB, source count. Preserves AI-computed fields. No AI calls, ~$0.01/month
- CloudFront CDN with HTTPS certificate, ~$0.01/month

---

## ✉️ Insight Email Pipeline

- **Reply-to-save** — reply to any Daily Brief, Weekly Digest, or Monthly Digest email with an insight, and it's automatically saved to the coaching log
- **AI extraction** — Lambda parses email reply text, strips quoted originals and signatures, auto-tags the insight
- **Sender whitelist** — only authorized email addresses can save insights (security)
- Endpoint: `insight@aws.mattsusername.com` → SES → S3 → Lambda → DynamoDB

---

## 🤝 Buddy Accountability Page (v2.53.0)

- **URL:** `https://buddy.averagejoematt.com/` — mobile-first, dark mode, designed for accountability partner Tom (Singapore, async timezone)
- **Beacon system:** Green/Yellow/Red based on data silence (not metrics). Conservative — green is default
- **4 signals:** Food Logging, Exercise, Routine, Weight — each with status dot + plain English explanation
- **Activity highlights** (last 4 workouts), **food snapshot** (weekly calorie/protein avg), **journey progress** (days elapsed, lbs lost, % to goal)
- **Tom’s prompt** with action guidance based on beacon state (green = be a mate, yellow = casual nudge, red = reach out)
- Data generated daily by Daily Brief Lambda (7-day lookback), separate Lambda@Edge auth with its own password
- Pixel art avatar rendered from character sheet tier + body frame

---

## 🍽️ The Weekly Plate (v2.63.0)

- **Friday evening food magazine email** — Sonnet-powered culinary celebration of the week’s eating
- **Greatest Hits** — highlights best meals from actual MacroFactor log data (with anti-hallucination guardrails)
- **Try This** — creative recipe suggestions based on what you’re already eating
- **Met Market grocery list** — curated shopping list for local grocery store
- **Macro scorecard** — weekly nutrition performance summary
- 26th Lambda, ~63s execution, ~$0.04/week

---

## 💊 Supplement Bridge (v2.66.1)

- **Automatic supplement tracking** — Habitify daily habit data auto-bridges to structured supplement entries in DynamoDB
- **21 supplements mapped** across 3 timing batches: morning fasted (4), afternoon with food (12), evening/sleep stack (5)
- Fires automatically after every Habitify Lambda run (try/except wrapped, non-fatal)
- Enables `get_supplement_log` and `get_supplement_correlation` MCP tools with real adherence data

---

## 📱 Data Sources (19 Total)

| Source | What It Tracks | How It Gets In |
|--------|---------------|----------------|
| Whoop | Recovery, HRV, strain, sleep | Automatic API sync (daily) |
| Eight Sleep | Sleep score, efficiency, stages, RHR, HRV | Automatic API sync (daily) |
| Garmin | Body Battery, stress, training load, readiness | Automatic API sync (daily) |
| Strava | Running, cycling, hiking, walking | Automatic API sync (daily) |
| Withings | Weight, body composition | Automatic API sync (daily) |
| MacroFactor | Calories, macros, micronutrients, meal timing | Phone export → Dropbox → auto-ingest |
| Habitify | 65 P40 habits, mood | Automatic API sync (daily) |
| Notion | Daily journal entries (5 templates) | Automatic API sync + AI enrichment (daily) |
| Apple Health | Steps, gait, energy, water, caffeine | Webhook push hourly |
| Dexcom Stelo | Continuous glucose (5-min readings) | Via Apple Health webhook |
| Todoist | Tasks completed, productivity | Automatic API sync (daily) |
| Function Health | Blood work (107 biomarkers, 2 draws) | Manual seed |
| GP Panels | Blood work (5 annual physicals) | Manual seed |
| DEXA | Body composition scan | Manual seed |
| Genome | 110 SNP interpretations | Manual seed |
| MacroFactor Workouts | Strength training (sets/reps/weight) | Phone export → auto-ingest |
| Weather (Open-Meteo) | Temperature, daylight, pressure, humidity | Automatic Lambda sync + on-demand |
| Supplements | Supplement/medication doses, timing, adherence | MCP tool logging |
| State of Mind (How We Feel) | Mood valence, emotions, life areas | Webhook via Apple Health |

---

## 📧 Automated Emails

| Email | When | What |
|-------|------|------|
| Daily Brief v2.62 | Every day, 10:00 AM | 18-section morning intelligence with AI coaching, character sheet, dashboard + buddy JSON |
| Anomaly Alert v2.1 | Daily (only if triggered) | Multi-source anomaly detection, travel-aware suppression |
| Freshness Alert | Daily (only if triggered) | Data source staleness warnings |
| Weekly Digest v4.3 | Sunday, 8:00 AM | 7-day summary with day grade trends, Board commentary + clinical JSON |
| Monthly Coach's Letter | 1st Monday, 8:00 AM | 30-day review, annual goal progress, expert panel |
| Nutrition Review v1.1 | Saturday, 9:00 AM | Sonnet-powered 3-expert panel weekly nutrition analysis |
| Wednesday Chronicle v1.1 | Wednesday, 7:00 AM | Sonnet-powered narrative journalism by Elena Voss + blog post |
| The Weekly Plate v1.0 | Friday, 6:00 PM | Sonnet-powered food magazine email with recipes and grocery lists |

---

# Part 2: How It Works (Technical)

For engineers and architects interested in the system design, infrastructure choices, and implementation patterns.

---

## Architecture Overview

Three-layer serverless architecture on AWS, single-region (us-west-2), single-account, ~$5/month total cost.

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER — 12 scheduled Lambdas + 1 webhook + 2 file  │
│  EventBridge cron → Lambda → DynamoDB + S3                  │
│  API Gateway webhook → Lambda → DynamoDB + S3               │
│  S3 object trigger → Lambda → DynamoDB                      │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  STORE LAYER — Single DynamoDB table + S3 raw archive       │
│  PK: USER#matthew#SOURCE#<source>  SK: DATE#YYYY-MM-DD      │
│  On-demand billing, PITR, deletion protection                │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  SERVE LAYER — MCP Lambda (105 tools, 1024 MB)             │
│  Lambda Function URL → Claude Desktop via mcp_bridge.py     │
│  + 4 email Lambdas (SES) + anomaly detector + freshness     │
│  + insight-email-parser (S3 trigger)                        │
│  + Web Dashboard (CloudFront → S3 static)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### Single-Table DynamoDB
All 16 data sources, the user profile, cached tool results, anomaly records, day grades, insights, and journal entries live in one DynamoDB table. No GSI — every access pattern is served by PK + SK range queries. This keeps costs at pennies per month and eliminates cross-table consistency concerns.

### Source-of-Truth Domain Architecture
When multiple devices measure the same thing (Whoop, Garmin, Apple Watch, and Eight Sleep all measure HRV), one source is designated authoritative per domain. The SOT mapping lives in the user profile and can be changed without code deploys. The webhook Lambda uses a three-tier filtering system to prevent double-counting at ingestion time.

### Stateless MCP Server
The MCP server is a Lambda function backed by a 23-module Python package (`mcp/`). The entry point `mcp_server.py` imports `mcp.handler` which routes requests to 20 domain-specific tool modules. Shared configuration lives in `mcp/config.py`; DynamoDB helpers, date parsing, and cache logic in `mcp/utils.py`. Each invocation authenticates, routes to the tool function, queries DynamoDB, computes, and returns JSON. No server to maintain, no connection pooling, no state between requests. Cold start is ~700-800ms; warm invocations <200ms for simple tools.

### Remote MCP Access (v2.44.0)
The MCP server is also accessible via a remote Function URL with Streamable HTTP transport (MCP spec 2025-06-18), enabling conversational queries through claude.ai and Claude mobile in addition to Claude Desktop.

### Cache Warmer Pattern
The same MCP Lambda doubles as a nightly cache warmer. An EventBridge rule triggers it at 9 AM with a special payload. It pre-computes 12 expensive tool results and writes them to a `CACHE#matthew` DynamoDB partition with a 26-hour TTL. Tools check cache on default queries and bypass it on custom date ranges. Total warmer runtime: 7 seconds.

### Haiku AI Calls (Not Sonnet/Opus)
The daily brief, weekly digest, monthly digest, journal enrichment, and anomaly detector all call Claude Haiku for AI commentary. Haiku's speed and cost make it practical to embed 4+ AI calls per daily brief without blowing the budget. The Wednesday Chronicle, Nutrition Review, and Weekly Plate use Sonnet for higher-quality narrative and analysis (~$0.04/week each). Total AI cost: ~$1-2/month.

### Lambda Function URL (Not API Gateway)
The MCP server uses a Lambda Function URL (free) instead of API Gateway REST API (~$3.50/month). Authentication is handled in-Lambda via an `x-api-key` header check. This saves $42/year for a personal project.

### Dropbox Pipeline for MacroFactor
MacroFactor doesn't have an API. The solution: export CSV from phone → save to Dropbox folder → `dropbox-poll` Lambda checks every 30 minutes → copies to S3 → triggers ingestion Lambda. Content-hash dedup prevents reprocessing. This eliminated the laptop-dependency bottleneck.

---

## Infrastructure Summary

| Component | Service | Count / Detail |
|-----------|---------|---------------|
| Lambdas | AWS Lambda (Python 3.12) | 27 total (13 ingestion, 1 webhook, 2 enrichment, 6 email/digest, 1 anomaly-detector, 1 freshness-checker, 1 character-sheet-compute, 1 dashboard-refresh, 1 MCP, 1 inbound-email, 1 key-rotator) |
| Database | DynamoDB | 1 table, single-table design, on-demand billing, PITR enabled |
| Object Storage | S3 | 1 bucket (~2.3 GB), raw archives + file triggers + static website |
| Scheduling | EventBridge | 25 rules (13 ingestion, 12 operational) |
| Webhook | API Gateway HTTP API | 1 endpoint (Health Auto Export — CGM, BP, State of Mind) |
| MCP Endpoint | Lambda Function URL | HTTPS, AuthType NONE + in-Lambda API key |
| Email (outbound) | SES | ~35 emails/month, DKIM verified domain |
| Email (inbound) | SES Receipt Rules | `insight@aws.mattsusername.com` → S3 → Lambda |
| Web Properties | CloudFront + S3 | 3 sites: `dash.averagejoematt.com` (dashboard + clinical), `blog.averagejoematt.com` (Chronicle), `buddy.averagejoematt.com` (accountability) |
| Secrets | Secrets Manager | 12 secrets (OAuth tokens, API keys) |
| Monitoring | CloudWatch | 22 alarms, 21 log groups (30-day retention) |
| Alerting | SNS | 1 topic → email subscription |
| Audit | CloudTrail | Management event logging |
| Cost Guard | AWS Budgets | $20 cap with 25/50/100% alerts |
| IAM Roles | IAM | 20 roles (least-privilege, per-Lambda) |
| DLQ | SQS | 1 queue, 20 of 27 Lambdas connected |

---

## Data Ingestion Patterns

**Three ingestion methods, chosen per-source based on API availability:**

| Pattern | Sources | Trigger | Frequency |
|---------|---------|---------|-----------|
| **Scheduled API poll** | Whoop, Garmin, Withings, Strava, Eight Sleep, Todoist, Habitify, Notion | EventBridge cron → Lambda | Daily (staggered 6:00-8:00 AM PT) |
| **File trigger** | MacroFactor, Apple Health (backfill) | S3 object created → Lambda | On file upload (MacroFactor also has Dropbox poll every 30 min) |
| **Webhook push** | Health Auto Export (CGM, gait, energy, caffeine, water) | API Gateway → Lambda | Hourly (iOS background push) |

All ingestion Lambdas follow the same pattern: authenticate → fetch data → normalize to schema → `put_item` / `update_item` to DynamoDB → archive raw response to S3. OAuth tokens self-heal on each run (refresh token → new access token → write back to Secrets Manager).

---

## MCP Tool Categories (105 Tools)

| Category | Tools | Description |
|----------|-------|-------------|
| Core Data Access | 16 | Sources, latest, daily summary, date range, field stats, search, compare, aggregate, correlations, seasonal patterns, dashboards, readiness |
| Weight & Body Comp | 4 | Weight loss progress, body composition trend, energy expenditure, non-scale victories |
| Strength Training | 6 | Exercise history, PRs, muscle volume, progression, frequency, standards |
| Sleep | 1 | Clinical sleep analysis (architecture, efficiency, debt, social jetlag, respiratory rate) |
| Nutrition | 7 | Summary, macro targets, food log, micronutrient report, meal timing, nutrition-biometrics correlation, caffeine-sleep correlation |
| Correlation & Analysis | 3 | Exercise-sleep, Zone 2, alcohol-sleep |
| Habits | 11 | Adherence, streaks, keystone habits, health correlations, group trends, period comparison, stacks, dashboard, habit registry, tier report, vice streaks |
| Garmin | 2 | Summary, device agreement |
| Labs & Genome | 8 | Lab results, trends, out-of-range history, biomarker search, genome insights, body composition snapshot, health risk profile, next lab priorities |
| Blood Glucose (CGM) | 5 | Dashboard, glucose-sleep correlation, meal response, fasting glucose validation, glucose-exercise correlation |
| Gait & Movement | 3 | Gait analysis, energy balance, movement score |
| Journal | 5 | Entries, search, mood trend, insights, correlations |
| Coaching Log | 3 | Save insight, get insights, update outcome |
| Day Classification | 1 | Day type analysis (rest/light/moderate/hard/race segmentation) |
| N=1 Experiments | 4 | Create, list, get results, end experiments — auto-compare 16 metrics before vs during |
| Health Trajectory | 1 | Forward-looking projections across weight, biomarkers, fitness, recovery, metabolic domains |
| Travel & Jet Lag | 3 | Log trips, travel history, post-trip recovery analysis with jet lag protocol |
| Blood Pressure | 2 | BP dashboard with AHA classification, 11-factor lifestyle correlation |
| Supplements | 3 | Log supplements, adherence tracking, supplement-outcome correlation |
| Weather & Seasonal | 1 | Weather-health correlations (10 weather factors vs health/journal metrics) |
| Training Periodization | 2 | Mesocycle detection + deload needs, readiness-based workout recommendation |
| Social Connection | 2 | Social quality trend (PERMA model), isolation risk detection |
| Meditation | 1 | Mindful minutes vs HRV/stress/sleep/recovery correlation |
| HR Recovery | 1 | Post-exercise HR recovery trend (mortality predictor) |
| Sleep Environment | 1 | Eight Sleep temperature optimization |
| State of Mind | 1 | How We Feel valence trend with emotion labels and life areas |

---

## Email Intelligence Pipeline

The platform sends 8 automated emails covering daily, weekly, and monthly cadences. The daily brief is the most complex Lambda (~3,000 lines). It:

1. Queries 12+ DynamoDB partitions for yesterday's data across all sources (including supplements, weather, travel, blood pressure, character sheet)
2. Fetches 7 days of Apple Health data for CGM trend context
3. Computes a weighted day grade from 8 components (sleep, recovery, nutrition, movement, habits, hydration, journal, glucose)
4. Persists the grade + habit_scores to dedicated DynamoDB partitions for historical trending
5. Makes 4 Claude Haiku API calls: Board of Directors coaching, training + nutrition commentary, journal coach, TL;DR + guidance
6. Builds an HTML email with 18 sections and sends via SES
7. Writes `dashboard/data.json` + `buddy/data.json` to S3 (non-fatal, try/except wrapped)

All AI calls are wrapped in try/except with graceful fallback — the brief always sends, even if the AI provider is down.

Beyond the daily brief, the pipeline includes: Wednesday Chronicle (Sonnet-powered narrative journalism + blog post), Nutrition Review (Saturday 3-expert panel), The Weekly Plate (Friday food magazine), Weekly Digest (Sunday 7-day summary + clinical JSON), Monthly Coach's Letter, Anomaly Alerts, and Freshness Alerts.

---

## Security Model

- **Per-Lambda IAM roles** (20 roles for 27 Lambdas) — each role scoped to exactly the secrets, DynamoDB operations, and S3 paths that Lambda needs
- **No DynamoDB Scan permission** on any role — all queries use PK+SK
- **SES scoped to verified domain** — email Lambdas can only send from `mattsusername.com`
- **API key authentication** on MCP endpoint — not AWS-level auth, but sufficient for a personal project
- **OAuth token self-healing** — refresh tokens are automatically rotated on each Lambda invocation
- **Genome data: interpretations only** — no raw genome data stored (privacy by design)
- **DynamoDB deletion protection + PITR** — 35-day point-in-time recovery, accidental deletion prevented

---

## Cost Engineering (<$25/month for a 19-Source Health Platform)

| Decision | What It Saved | Alternative Cost |
|----------|--------------|-----------------|
| Lambda Function URL instead of API Gateway | $3.50/month | REST API pricing |
| DynamoDB on-demand instead of provisioned | ~$10-15/month | Provisioned capacity for spiky workloads |
| Haiku instead of Sonnet for AI calls | ~$2-5/month | Sonnet API costs at 35 calls/day |
| Single DynamoDB table, no GSI | ~$5/month | Additional table + GSI read capacity |
| CloudWatch 30-day retention | ~$2/month | Default infinite retention |
| Cache warmer + memory bump instead of provisioned concurrency | $10.80/month | Keeping Lambda warm 24/7 |
| Secrets Manager (12 × $0.40) | — | Largest line item at $4.80/month; could consolidate but security isolation is worth it |

---

## Board of Directors Framework

The coaching intelligence throughout the system is driven by expert personas:

| Expert | Domain | Where Used |
|--------|--------|------------|
| Andrew Huberman | Sleep, stress, neuroscience | Daily brief, journal coach, sleep tools |
| Peter Attia | Longevity, metabolic health, CGM | Health risk profile, CGM tools, ASCVD risk |
| Rhonda Patrick | Nutrient metabolism, genetics | Micronutrient report, genome cross-reference |
| Andy Galpin | Exercise science, training load | Training report, readiness, Zone 2 |
| Layne Norton | Nutrition, protein optimization | Protein distribution, macro targets |
| Tim Ferriss | Behavioral design, journaling | Journal enrichment, habit analysis |
| David Sinclair | Longevity biology | Health risk profile |
| Matthew Walker | Sleep science | Sleep analysis, circadian tools |
| Judith Beck | CBT cognitive patterns | Journal enrichment |

These aren't just names — each expert's evidence-based frameworks are encoded into tool logic, scoring thresholds, AI prompts, and alert criteria.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Compute | AWS Lambda (Python 3.12) |
| Database | DynamoDB (single-table, on-demand) |
| Storage | S3 (raw archive) |
| Scheduling | EventBridge |
| Email | SES (DKIM verified) |
| AI | Claude Haiku (via Anthropic API) |
| Secrets | AWS Secrets Manager |
| Monitoring | CloudWatch Alarms + SNS |
| MCP Protocol | JSON-RPC 2.0 over HTTPS |
| Local Bridge | Python (mcp_bridge.py → Claude Desktop) |
| Journal | Notion API |
| Nutrition Pipeline | Dropbox API → S3 → Lambda |
| CGM | Dexcom Stelo → Apple HealthKit → Health Auto Export webhook |

---

## Project Stats

| Metric | Value |
|--------|-------|
| MCP tools | 120 |
| Data sources | 19 (12 scheduled + 1 webhook + 3 manual + 2 MCP-managed + 1 SoM via webhook) |
| Lambdas | 28 |
| EventBridge rules | 25 |
| CloudWatch alarms | 22 |
| Secrets | 12 |
| DynamoDB partitions | ~30 (sources + profile + cache + anomalies + day_grade + insights + experiments + travel + supplements + state_of_mind + habit_scores + character_sheet + life_events + interactions + temptations + exposures + food_responses + rewards) |
| Daily Brief sections | 18 |
| Haiku AI calls per brief | 4 |
| Historical day grades | 948 (retrocomputed back to July 2023) |
| Blood draws tracked | 7 (spanning 2019-2025) |
| Genome SNPs interpreted | 110 |
| Habits tracked | 65 across 9 groups |
| Cached MCP tools | 12 (pre-computed nightly) |
| SOT domains | 21 |
| MCP modules | 25 (22 domain + config + utils + warmer) |
| Web dashboard views | 2 (daily + clinical) |
| Monthly AWS cost | ~$6.50 |
| Development period | Feb 22-28, 2026 (7 days to v2.47.2) |
