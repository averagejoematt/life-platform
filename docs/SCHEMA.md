# Life Platform — Schema & Data Dictionary

**Table:** `life-platform` (us-west-2)
**Design:** Single-table with composite keys (no GSIs — ADR-005)
**Last updated:** 2026-06-28 (v8.6.0 — 136 MCP tools, 20 data sources, 81 Lambdas, 12 cached tools)

> Consolidated from SCHEMA.md + DATA_DICTIONARY.md (v3.7.32). For metric descriptions and feature guide, see PLATFORM_GUIDE.md.

---

## Source-of-Truth (SOT) Domains

Each health domain has exactly one authoritative source. When multiple devices measure the same thing, only the SOT source is used for scoring, grading, and coaching. The SOT mapping lives in the user profile and can be changed without code deploys.

| Domain | SOT Source | Why This Source |
|--------|-----------|-------------------|
| **Cardio** | Strava | GPS accuracy, activity classification |
| **Strength** | Hevy / MacroFactor Workouts | Set-level granularity (weight × reps × RIR) |
| **Physiology** (HRV, RHR, recovery) | Whoop | Clinical-grade sensor, worn 24/7 |
| **Nutrition** | MacroFactor | User-logged meals with per-food granularity |
| **Sleep Duration & Staging** | Whoop | Captures all sleep regardless of location (v2.55.0) |
| **Sleep Environment** | Eight Sleep | Pod sensor (pressure + temperature), unique to bed |
| **Body** (weight, body fat) | Withings | Smart scale, daily weigh-in |
| **Steps** | Apple Health | iPhone always-on, most accurate daily step count |
| **Tasks** | Todoist | Primary task manager |
| **Habits** | Habitify | Active tracking app |
| **Stress** | Garmin | Epix Gen 2 all-day HRV-derived stress score |
| **Body Battery** | Garmin | Proprietary Garmin metric |
| **Gait** | Apple Health | Apple Watch accelerometer via HAE webhook |
| **Energy Expenditure** | Apple Health | Apple Watch active + basal calories (real measurement) |
| **CGM** | Apple Health | Dexcom Stelo → HealthKit → webhook |
| **Caffeine** | Apple Health | Caffeine tracking app → HealthKit → webhook |
| **Water** | Apple Health | Water tracking app → HealthKit → webhook |
| **Journal** | Notion | Structured journal templates with AI enrichment |
| **Supplements** | Supplements (MCP) | Manual logging via `log_supplement` MCP tool |
| **Weather** | Weather (Open-Meteo) | Automated Lambda sync + on-demand MCP fetch |
| **State of Mind** | State of Mind (How We Feel) | Via Apple HealthKit → HAE webhook |

---

## Metric Overlap Map

Where multiple sources measure the same thing:

| Metric | SOT | Also Available From | Resolution |
|--------|-----|-------------------|------------|
| **HRV** | Whoop | Garmin (`hrv_last_night`), Eight Sleep (`hrv`), Apple Health (`hrv_sdnn_apple`) | Whoop for coaching; `get_device_agreement` cross-validates |
| **Resting Heart Rate** | Whoop | Garmin, Eight Sleep, Apple Health | Same cross-validation pattern |
| **Sleep Duration** | Whoop | Eight Sleep, Garmin | Whoop captures couch/travel sleep |
| **Sleep Staging** | Whoop | Eight Sleep | Whoop hours → pct via `normalize_whoop_sleep()` |
| **Steps** | Apple Health | Garmin (watch) | Apple preferred (phone always-on). **DI-1.4 step precedence:** the Garmin watch is the better counter only when its source-state is `live`; a rate-limited/stale Garmin emits sparse partial readings (the "phantom 298" — Garmin 6/15=298 steps used as the daily figure while the Apple ~3,415 avg was truer), so consumers fall back to Apple Health unless Garmin is live. A step count never, on its own, drives a sedentary/under-training verdict (Hevy-join, DI-1.2). `get_daily_metrics(view="movement")` carries `step_data_complete`/`step_coverage_pct`/`step_incomplete_dates` — the apple_health envelope can read "fresh" while the step field itself is missing for a day. |
| **Active Calories** | Apple Health | Garmin | Apple for TDEE; Garmin retained for training metrics |
| **Body Composition** | Withings (daily) | DEXA (semi-annual) | Withings for trending; DEXA for absolute accuracy |

### Three-Tier Source Filtering (HAE Webhook)

| Tier | Behavior | Metrics |
|------|----------|---------|
| **Tier 1** (Apple-exclusive) | All readings ingested | Steps, active/basal calories, gait, flights, water, caffeine, body mass (`weight_lbs` fallback, v1.4.2 — Withings API has sync delays) |
| **Tier 2** (Cross-device) | Filtered to Apple Watch only, `_apple` suffix | HR, RHR, HRV, respiratory rate, SpO2 |
| **Tier 3** (Skip) | Blocked at ingestion | Nutrition (MacroFactor SOT), sleep analysis (Eight Sleep SOT), body fat % (`body_fat_percentage` — Withings SOT) |

---

## Known Data Gaps

| Gap | Period | Impact |
|-----|--------|--------|
| Habit tracking | 2025-11-10 → 2026-02-22 | No habit data. No fix possible. |
| Garmin | 2026-01-19 → 2026-02-23 | App sync issue. Backfilled from Feb 23 forward. |
| MacroFactor | Before 2026-02-22 | Mock data only; real import pending. |
| CGM | 2025-01-25 → 2026-02-24 | Dexcom gap. CGM data: Sep 2024–Jan 2025 + Feb 2026 onward. |
| Journal | Before 2026-02-24 | Notion system created Feb 24. No prior subjective data. |
| State of Mind | Before 2026-02-27 | How We Feel integration added v2.41.0. |
| Supplements | Before 2026-02-26 | Manual MCP logging started v2.36.0. |

---

## Key Structure

| Attribute | Description |
|-----------|-------------|
| `pk` | Partition key — identifies the entity type and owner |
| `sk` | Sort key — enables range queries and versioning |

### Partition Key Patterns

| Entity | pk format | Example |
|--------|-----------|---------|
| Health source data | `USER#matthew#SOURCE#<source>` | `USER#matthew#SOURCE#whoop` |
| User profile | `USER#matthew` | `USER#matthew` |

### Sort Key Patterns

| Entity | sk format | Example |
|--------|-----------|---------|
| Daily record | `DATE#YYYY-MM-DD` | `DATE#2026-02-22` |
| Whoop workout | `DATE#YYYY-MM-DD#WORKOUT#<id>` | `DATE#2026-03-29#WORKOUT#12345` |
| Hevy workout | `DATE#YYYY-MM-DD#WORKOUT#<id>` | `DATE#2026-05-25#WORKOUT#a1b2c3d4-…` |
| Hevy delete tombstone | `DELETE#WORKOUT#<id>` | `DELETE#WORKOUT#a1b2c3d4-…` |
| Lab provider metadata | `PROVIDER#<provider>#<period>` | `PROVIDER#function_health#2025-spring` |
| User profile | `PROFILE#v1` | `PROFILE#v1` |

---

## Sources

Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `macrofactor_workouts`, `macrofactor_export`, `garmin`, `habitify`, `notion`, `labs`, `dexa`, `genome`, `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `chronicle`, `measurements`, `food_delivery`, `weight_episodes`, `training_reference`, `macrofactor_meals`

Note: `chronicling` is a historical/archived source — not actively ingesting. `hevy` became the **primary** strength-training source on 2026-05-25 (see ADR-060) — actively ingesting via hourly `hevy-backfill` poll of the Hevy events API; older Hevy records exist as legacy daily aggregates that the MCP `_expand_legacy_aggregate` bridge surfaces as virtual per-workout views. `macrofactor_export` is the explicit source label for workouts arriving via the manual MacroFactor Dropbox CSV export path (Tier 2 — see ADR-061). `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `weight_episodes`, `training_reference`, and `macrofactor_meals` are derived/computed partitions, not raw ingested data (the last is a recomputable projection over the raw `macrofactor` food log — see below).

Ingestion methods: API polling (scheduled Lambda), S3 file triggers (manual export), **webhook** (Health Auto Export push — also handles BP and State of Mind), **MCP tool write** (supplements), **on-demand fetch + scheduled Lambda** (weather)

---

## Field Reference by Source

> **Framework-stamped fields (all SIMP-2 framework sources):** `ingestion_framework.py` stamps `pk`, `sk`, `source`, `schema_version`, `ingested_at`, and `phase` (ADR-058: `pilot`/`experiment`) on every item it writes. These fields are not repeated in the per-source tables below.

### whoop

Daily records (`sk = DATE#YYYY-MM-DD`) + workout sub-items (`sk = DATE#YYYY-MM-DD#WORKOUT#<id>`).

**Daily fields:**
| Field | Type | Description |
|-------|------|-------------|
| `recovery_score` | number | 0–100 daily recovery |
| `hrv` | number | Heart rate variability (ms) |
| `resting_heart_rate` | number | RHR (bpm) |
| `strain` | number | 0–21 daily strain |
| `sleep_duration_hours` | number | Total sleep (hours) |
| `sleep_quality_score` | number | 0–100 sleep quality |
| `sleep_performance_percentage` | number | 0–100 sleep performance |
| `sleep_efficiency_percentage` | number | Sleep efficiency % |
| `sleep_consistency_percentage` | number | Circadian consistency % |
| `rem_sleep_hours` | number | REM sleep (hours) |
| `slow_wave_sleep_hours` | number | Deep/SWS sleep (hours) |
| `light_sleep_hours` | number | Light sleep (hours) |
| `time_awake_hours` | number | Time awake (hours) |
| `disturbance_count` | number | Sleep disturbances |
| `respiratory_rate` | number | Breaths/min |
| `spo2_percentage` | number | Blood oxygen % |
| `skin_temp_celsius` | number | Skin temperature °C |
| `kilojoule` | number | Daily energy (kJ) |
| `average_heart_rate` | number | Daily avg HR (bpm) |
| `max_heart_rate` | number | Daily max HR (bpm) |
| `sleep_start` | string | ISO timestamp |
| `sleep_end` | string | ISO timestamp |
| `sleep_onset_minutes` | number | Minutes from midnight to sleep onset |
| `sleep_onset_consistency_7d` | number | 7-day onset consistency (std dev) |
| `nap_count` | number | Number of nap sessions (only present when ≥1 nap) |
| `nap_duration_hours` | number | Total nap sleep (hours, in-bed minus awake) |

**Workout sub-items** (`sk = DATE#YYYY-MM-DD#WORKOUT#<id>`):
| Field | Type | Description |
|-------|------|-------------|
| `workout_id` | string | Whoop workout ID (v2 API UUID) |
| `sport_id` | number | Whoop sport type ID |
| `sport_name` | string | Human-readable sport name |
| `start_time` | string | ISO timestamp |
| `end_time` | string | ISO timestamp |
| `strain` | number | Workout strain |
| `average_heart_rate` | number | Avg HR during workout |
| `max_heart_rate` | number | Max HR during workout |
| `kilojoule` | number | Energy (kJ) |
| `distance_meter` | number | Distance (meters) |
| `zone_0_minutes` through `zone_5_minutes` | number | Time in each HR zone (minutes) |

### withings
| Field | Type | Description |
|-------|------|-------------|
| `weight_kg` | number | Body weight (kg, source of truth) |
| `weight_lbs` | number | Body weight (lbs, derived) |
| `fat_mass_lbs` | number | Fat mass (lbs) |
| `fat_free_mass_lbs` | number | Fat-free/lean mass (lbs) |
| `fat_ratio_pct` | number | Body fat percentage |
| `muscle_mass_lbs` | number | Muscle mass (lbs) |
| `bone_mass_lbs` | number | Bone mass (lbs) |
| `hydration_kg` | number | Body water mass (kg) |
| `heart_pulse` | number | Heart rate at weigh-in (bpm) |
| `measurement_timestamp` | number | Unix epoch of measurement |
| `measurement_time_utc` | string | ISO timestamp of measurement |
| `captured_at` | string | ISO timestamp of ingestion |
| `lean_mass_delta_14d` | number | 14-day lean mass change (lbs) |
| `fat_mass_delta_14d` | number | 14-day fat mass change (lbs) |

Note: every mass metric is written in kg with a derived lbs twin — `fat_mass_kg`, `fat_free_mass_kg`, `muscle_mass_kg`, `bone_mass_kg` accompany the `*_lbs` fields above. Additional conditional fields are written whenever the device reports them (all in `MEAS_TYPES` in `withings_lambda.py`): `height_m`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `temperature_c`, `body_temperature_c`, `skin_temperature_c`, `spo2_pct`, `pulse_wave_velocity_mps`, `vo2_max`, ECG intervals (`qrs_interval_ms`, `pr_interval_ms`, `qt_interval_ms`), and `vascular_age`.

### strava
Day-level aggregates (rolled up from individual activities):

| Field | Type | Description |
|-------|------|-------------|
| `total_distance_miles` | number | Sum of all activity distances |
| `total_elevation_gain_feet` | number | Sum of elevation gain |
| `total_moving_time_seconds` | number | Sum of moving time |
| `activity_count` | number | Number of activities |
| `sport_types` | list | Sorted distinct sport types for the day |
| `total_zone2_seconds` | number | Sum of per-activity Zone 2 seconds |
| `total_kilojoules` | number | Energy output — **legacy-only** (pre-migration records; not written by current code, but still read by hypothesis engine and nutrition tools) |

Field aliases supported in queries:
- `distance_miles` → `total_distance_miles`
- `elevation_gain_feet` / `elevation_gain` → `total_elevation_gain_feet`

Individual activity records (inside `activities` list) include:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Original Strava activity name (never overwritten) |
| `enriched_name` | string | Auto-generated label with location, stats, recovery context, percentile rank |
| `enriched_at` | string | ISO timestamp of last enrichment |
| `sport_type` | string | Activity type (Run, Hike, WeightTraining, etc.) |
| `distance_miles` | number | Distance |
| `total_elevation_gain_feet` | number | Elevation gain |
| `moving_time_seconds` | number | Moving time |
| `average_heartrate` | number | Avg HR (bpm) |
| `max_heartrate` | number | Max HR (bpm) |
| `kilojoules` | number | Energy output |
| `pr_count` | number | Strava PRs set |
| `location_city` | string | City near activity start (new activities only) |
| `location_state` | string | State near activity start (new activities only) |
| `location_country` | string | Country (new activities only) |
| `start_date_local` | string | Local start time |
| `strava_id` | string | Strava activity ID |

Note: `location_*` fields are only populated on activities ingested after 2026-02-22. Historical records have null location.

Note: `enriched_name` is written nightly by the `activity-enrichment` Lambda. Original `name` is always preserved and never overwritten.

Note: `search_activities` searches both `name` and `enriched_name` — keyword searches will match renamed activities (e.g. "Machu Picchu", "Mailbox Peak") via the enriched label.

### todoist
| Field | Type | Description |
|-------|------|-------------|
| `completed_count` | number | Tasks completed that day |
| `active_count` | number | Active tasks at time of sync |
| `overdue_count` | number | Overdue tasks |
| `due_today_count` | number | Tasks due today |
| `priority_breakdown` | object | Count by priority level (p1-p4) |
| `completed_tasks` | list | List of completed task objects |
| `completions_by_project` | object | Completion count per project |
| `tasks_due_today` | list | List of today's due tasks |

### apple_health

Data ingested via two paths:
- **S3 XML import** — manual Apple Health export (full history, all fields below)
- **Health Auto Export webhook** — automated push from iOS app every 4 hours (CGM + selected metrics)

Both paths merge into the same `apple_health` DynamoDB records via `update_item` (no overwrites).

**Standard fields (XML export):**

| Field | Type | Description |
|-------|------|-------------|
| `steps` | number | Step count |
| `active_calories` | number | Active calories burned (daily sum) |
| `basal_calories` | number | Basal/resting calories (daily sum) |
| `vo2max` | number | Estimated VO2 max |
| `heart_rate` | number | Average heart rate (daily avg) |

Note: the XML import path (`apple_health_lambda.py` `QUANTITY_RECORDS`) writes many more fields than the rows above: `hrv_sdnn`, `weight_lbs`, `bmi`, `body_fat_pct`, `lean_mass_lbs`, `waist_inches`, `spo2_pct`, `respiratory_rate`, `resting_heart_rate`, `walking_heart_rate_avg`, `bp_systolic`/`bp_diastolic`, `blood_glucose_mgdl`, `walking_steadiness_pct`, `distance_cycling_miles`, ~36 `nutrition_*` fields, plus workout aggregates (`workouts`, `workout_count`, `workout_total_minutes`, `workout_types`), sleep aggregates, and CGM daily aggregates. **Caveat:** the XML path writes UNSUFFIXED HR/HRV/SpO2/respiratory fields with no Apple-device tier filtering — the Tier-2 `_apple` suffix system exists only in the HAE webhook Lambda.

**Activity / energy fields (webhook — Tier 1, all readings):**

| Field | Type | Description |
|-------|------|-------------|
| `active_calories` | number | Active calories burned (Apple Watch, daily sum) |
| `basal_calories` | number | Basal metabolic calories (Apple Watch, daily sum) |
| `total_calories_burned` | number | Derived: active + basal (Apple Watch TDEE) |
| `steps` | number | Step count (daily sum) |
| `flights_climbed` | number | Floors climbed (daily sum) |
| `distance_walk_run_miles` | number | Walking + running distance (daily sum, miles) |
| `distance_cycling_miles` | number | Cycling distance (daily sum, miles) — 2026-06-20 capture-everything expansion |
| `distance_swimming_miles` | number | Swimming distance (daily sum, miles) — 2026-06-20 |
| `distance_snow_miles` | number | Downhill snow-sports distance (daily sum, miles) — 2026-06-20 |
| `vo2max` | number | Estimated VO₂ max (daily avg) — Apple/Watch is the only source; 2026-06-20 |
| `walking_heart_rate_avg` | number | Walking heart-rate average (daily avg) — 2026-06-20 |
| `walking_steadiness_pct` | number | Apple Walking Steadiness (daily avg, %) — fall-risk proxy; 2026-06-20 |
| `physical_effort` | number | Physical Effort / estimated MET intensity (daily avg) — 2026-06-20 |
| `cycling_ftp_watts` | number | Cycling Functional Threshold Power (daily avg, watts) — fitness benchmark; 2026-06-20 |
| `weight_lbs` | number | Body mass from HAE (Tier 1 fallback since v1.4.2 — Withings remains SOT but its API has sync delays) |

> **2026-06-20 capture-everything note:** the additive distances (`distance_cycling_miles`/`distance_swimming_miles`/`distance_snow_miles`) join `_ACTIVITY_MAX_FIELDS` — max-across-sources dedup (same as `steps`) to avoid iPhone + Watch + Strava double-counting. Per-sample *workout dynamics* (cycling/running power, cadence, ground contact, stride, vertical oscillation) are deliberately NOT promoted to daily fields — a daily average is noise; they are preserved in the raw S3 payload archive (`raw/{user}/health_auto_export/`) and the Workouts feed, surfaced per-workout if ever needed.

**Gait / mobility fields (webhook — Tier 1, Apple Watch exclusive):**

| Field | Type | Description |
|-------|------|-------------|
| `walking_speed_mph` | number | Average walking speed (mph) — strongest single mortality predictor |
| `walking_step_length_in` | number | Average step length (inches) — earliest aging gait marker |
| `walking_asymmetry_pct` | number | Left/right gait asymmetry (%) — injury/compensation indicator |
| `walking_double_support_pct` | number | Double support time (%) — balance/fall risk proxy |

Note: Gait metrics are Apple Watch exclusive. Walking speed <1.0 m/s (2.24 mph) is a clinical flag. Sustained asymmetry >3-4% indicates compensation for pain/injury. These fields are available from v1.1.0 of the webhook Lambda.

**Caffeine (webhook — Tier 1, SOT for caffeine):**

| Field | Type | Description |
|-------|------|-------------|
| `caffeine_mg` | number | Daily caffeine intake (mg, summed from water/caffeine tracking app) |
| `_rd_caffeine_mg` | map | Reading-level dedup map {timestamp: quantity} — incremental sync deduplication |

Note: Caffeine SOT moved from MacroFactor to Apple Health as of v2.28.0. Logged via dedicated water/caffeine app → Apple Health → webhook. MacroFactor `total_caffeine_mg` retained as secondary reference but is no longer authoritative.

**Audio exposure (webhook — Tier 1):**

| Field | Type | Description |
|-------|------|-------------|
| `headphone_audio_exposure_db` | number | Average headphone audio level (dBASPL) — hearing health |

**Cross-device reference fields (webhook — Tier 2, Apple Watch readings only):**

| Field | Type | Description |
|-------|------|-------------|
| `heart_rate_apple` | number | Average HR from Apple Watch only (bpm) |
| `resting_heart_rate_apple` | number | RHR from Apple Watch only (bpm) |
| `hrv_sdnn_apple` | number | HRV SDNN from Apple Watch only (ms) |
| `respiratory_rate_apple` | number | Respiratory rate from Apple Watch only (breaths/min) |
| `spo2_pct_apple` | number | SpO2 from Apple Watch only (%) |

Note: Tier 2 fields are suffixed with `_apple` to avoid colliding with SOT fields from Whoop/Eight Sleep/Garmin. Readings from non-Apple devices (Eight Sleep, Whoop, MacroFactor) are filtered out at ingestion time. Use for cross-device validation via `get_device_agreement`.

**CGM / Blood Glucose fields (webhook):**

| Field | Type | Description |
|-------|------|-------------|
| `blood_glucose_avg` | number | Daily average glucose (mg/dL) |
| `blood_glucose_min` | number | Daily minimum glucose |
| `blood_glucose_max` | number | Daily maximum glucose |
| `blood_glucose_std_dev` | number | Glucose variability (std deviation) |
| `blood_glucose_readings_count` | number | Number of readings that day |
| `blood_glucose_time_in_range_pct` | number | % of readings 70–180 mg/dL |
| `blood_glucose_time_below_70_pct` | number | % of readings <70 (hypoglycemia) |
| `blood_glucose_time_above_140_pct` | number | % of readings >140 (elevated) |
| `blood_glucose_time_in_optimal_pct` | number | % of readings 70–120 mg/dL (Attia optimal, stricter than 70-180) |
| `cgm_source` | string | `dexcom_stelo` (≥20 readings/day) or `manual` (<20) |
| `webhook_ingested_at` | string | ISO timestamp of last webhook write |

Note: Individual 5-minute CGM readings are stored in S3 at `raw/matthew/cgm_readings/YYYY/MM/DD.json` for detailed analysis. DynamoDB holds daily aggregates only.

Note: `cgm_source` auto-detects based on reading frequency. ≥20 readings/day indicates continuous monitor (Dexcom Stelo); fewer indicates manual finger-stick entries.

**Blood pressure fields (webhook v1.4.0):**

| Field | Type | Description |
|-------|------|-------------|
| `blood_pressure_systolic` | number | Daily average systolic (mmHg) |
| `blood_pressure_diastolic` | number | Daily average diastolic (mmHg) |
| `bp_systolic` | number | Duplicate of `blood_pressure_systolic` (written alongside it) |
| `bp_diastolic` | number | Duplicate of `blood_pressure_diastolic` (written alongside it) |
| `blood_pressure_pulse` | number | Daily average pulse from BP cuff (bpm) |
| `blood_pressure_readings_count` | number | Number of BP readings that day |

Note: Individual BP readings stored in S3 at `raw/matthew/blood_pressure/YYYY/MM/DD.json` for morning vs evening analysis. DynamoDB holds daily averages only. Data path: BP cuff → Apple Health → Health Auto Export webhook → DynamoDB + S3.

**Breathwork / mindfulness fields (webhook — via Breathwrk app → HealthKit → HAE):**

| Field | Type | Description |
|-------|------|-------------|
| `mindful_minutes` | number | Breathwork/meditation minutes from Breathwrk via HAE |

**Water intake fields (webhook — via water tracking app → HealthKit → HAE):**

| Field | Type | Description |
|-------|------|-------------|
| `water_intake_ml` | number | Daily water intake in milliliters (deduped from reading-level data) |
| `water_intake_oz` | number | Derived: water_intake_ml / 29.5735 (oz not tracked independently) |
| `_rd_water_intake_ml` | map | Reading-level dedup map {timestamp: quantity} — used for incremental sync deduplication |

**Recovery / flexibility fields (webhook — from HAE workouts payloads, e.g. Pliability/Breathwrk → HealthKit → HAE; not Apple Watch-specific):**

| Field | Type | Description |
|-------|------|-------------|
| `recovery_workout_minutes` | number | Total recovery-workout minutes (all categories) |
| `recovery_workout_sessions` | number | Total recovery-workout session count |
| `recovery_workout_types` | string | Comma-joined sorted set of categories present |
| `flexibility_minutes` | number | Stretching/flexibility minutes |
| `flexibility_sessions` | number | Stretching/flexibility session count |
| `breathwork_minutes` | number | Breathwork minutes |
| `breathwork_sessions` | number | Breathwork session count |
| `yoga_minutes` | number | Yoga minutes |
| `yoga_sessions` | number | Yoga session count |
| `pilates_minutes` | number | Pilates minutes |
| `pilates_sessions` | number | Pilates session count |
| `cooldown_minutes` | number | Cooldown minutes |
| `tai_chi_minutes` | number | Tai chi minutes |

### eightsleep
| Field | Type | Description |
|-------|------|-------------|
| `sleep_score` | number | Eight Sleep sleep score |
| `hrv_avg` | number | Average HRV (ms) |
| `hr_avg` | number | Average heart rate (bpm) |
| `respiratory_rate` | number | Breaths per minute |
| `toss_turn_count` | number | Movement count |
| `sleep_duration_hours` | number | Time actually asleep (hours) |
| `time_in_bed_hours` | number | Total time in bed (hours, derived) |
| `sleep_efficiency_pct` | number | Sleep efficiency % (derived) |
| `waso_hours` | number | Wake after sleep onset (hours, derived) |
| `rem_hours` | number | REM sleep (hours) |
| `deep_hours` | number | Deep sleep (hours) |
| `light_hours` | number | Light sleep (hours) |
| `awake_hours` | number | Awake time (hours) |
| `rem_pct` | number | REM % of total sleep (derived) |
| `deep_pct` | number | Deep % of total sleep (derived) |
| `light_pct` | number | Light % of total sleep (derived) |
| `time_to_sleep_min` | number | Sleep onset latency (minutes) |
| `sleep_start` | string | ISO timestamp of sleep onset (UTC) |
| `sleep_end` | string | ISO timestamp of wake (UTC) |
| `bed_temp_c` | number | Pod temperature (°C) |
| `bed_temp_f` | number | Pod temperature (°F) |
| `bed_temp_min_c` | number | Minimum pod temperature overnight (°C) |
| `bed_temp_max_c` | number | Maximum pod temperature overnight (°C) |
| `room_temp_c` | number | Room temperature (°C) |
| `room_temp_f` | number | Room temperature (°F) |
| `temp_level_avg` | number | Temp level setting avg (-10 to +10) |
| `temp_level_min` | number | Temp level min |
| `temp_level_max` | number | Temp level max |
| `bed_side` | string | Left or right side of bed |
| `sleep_onset_hour` | number | Hour of sleep onset (derived) |
| `wake_hour` | number | Hour of wake (derived) |
| `sleep_midpoint_hour` | number | Midpoint hour (derived) |

### hevy (strength training)
Hevy data is stored at the workout and set level, not day-level aggregates. Access via strength-specific MCP tools (`get_exercise_history`, `get_strength_prs`, etc.) rather than `get_date_range`.

**Per-workout items** (`sk = DATE#YYYY-MM-DD#WORKOUT#<id>`, from `lambdas/hevy_common.py::normalize_workout`):

| Field | Type | Description |
|-------|------|-------------|
| `source_workout_id` | string | Hevy workout ID |
| `workout_uid` | string | Stable cross-source dedupe key (`hevy:<workout_id>`) |
| `date` | string | YYYY-MM-DD |
| `title` | string | Workout title |
| `description` | string | Workout description (truncated to 1000 chars) |
| `start_time` | string | ISO timestamp |
| `end_time` | string | ISO timestamp |
| `duration_sec` | number | Workout duration (seconds) |
| `total_volume_kg` | number | Sum of weight × reps across all sets (kg) |
| `exercises` | list | Per-exercise objects with sets (reps × weight) |
| `exercise_count` | number | Number of exercises |
| `set_count` | number | Total sets across exercises |
| `original_unit` | string | Unit hint from the raw payload |
| `raw_ref` | string | `s3://` path of the archived raw payload |
| `schema_version` | number | Item schema version |
| `ingested_at` | string | ISO timestamp |
| `phase` | string | ADR-058 phase tag (`pilot`/`experiment`) |

**Delete tombstones** (`sk = DELETE#WORKOUT#<id>`, written by `hevy_backfill_lambda.py` on Hevy deleted-events): `tombstone: true`, `tombstoned_at`, `tombstoned_reason: "hevy_event_delete"`. Reconciled by the next audit pass (the date isn't known at delete time).

### macrofactor
| Field | Type | Description |
|-------|------|-------------|
| `total_calories_kcal` | number | Total calories consumed |
| `total_protein_g` | number | Protein (grams) |
| `total_carbs_g` | number | Carbohydrates (grams) |
| `total_fat_g` | number | Fat (grams) |
| `total_fiber_g` | number | Fiber (grams) |
| `total_sodium_mg` | number | Sodium (mg) |
| `total_caffeine_mg` | number | Caffeine (mg) |
| `total_omega3_total_g` | number | Omega-3 fatty acids total (grams) |
| `total_potassium_mg` | number | Potassium (mg) |
| `total_magnesium_mg` | number | Magnesium (mg) |
| `total_vitamin_d_mcg` | number | Vitamin D (mcg) |
| `food_log` | list | Nested list of individual food entries with per-item macros and timestamps (HH:MM format) |
| `entries_count` | number | Number of food-log entries that day |
| `protein_distribution_score` | number | % of meals (≥400 kcal) hitting ≥30g protein (Norton/Galpin MPS threshold) |
| `meals_above_30g_protein` | number | Count of meals meeting ≥30g protein target |
| `total_meals` | number | Distinct meals detected (eating occasions ≥400 kcal) |
| `total_snacks` | number | Eating occasions excluded as snacks (<400 kcal) |
| `micronutrient_sufficiency` | object | Per-nutrient map: {nutrient_key: {actual, target, pct}} — 5 nutrients tracked |
| `micronutrient_avg_pct` | number | Average sufficiency across tracked nutrients (each capped at 100%) |

Note: `food_log` is a nested list within each day record. Access via `get_food_log` tool rather than `get_date_range`.

Note: the `total_*` nutrient rows above are a representative subset — the diary parser maps ~55 nutrient columns (`NUTRIENT_COLUMNS` in `macrofactor_lambda.py`), each written as a `total_*` field when present.

**Daily-summary CSV format (current MacroFactor default export, `_format: "daily_summary"`):** one row per day with daily totals and no per-meal food log. Detected by `detect_csv_type` (Expenditure + Date + Calories columns). Writes the same `DATE#` partition with `schema_version: 2`, `_format: "daily_summary"`, empty `food_log`, `entries_count: 0`, plus:

| Field | Type | Description |
|-------|------|-------------|
| `weight_lbs_macrofactor` | number | Scale weight from MacroFactor (lbs) |
| `trend_weight_lbs` | number | MacroFactor trend weight (lbs) |
| `expenditure_kcal` | number | MacroFactor estimated TDEE |
| `target_calories_kcal` | number | Calorie target |
| `target_protein_g` | number | Protein target |

Note: `macrofactor_export` is a **read-side alias only** — no Lambda writes `source=macrofactor_export`; the MCP read layer maps `macrofactor_workouts` → `macrofactor_export` (`mcp/tools_hevy.py`).

### food_delivery (behavioral signal)

Quarterly CSV import with multiple item types per session. Source: `USER#matthew#SOURCE#food_delivery`.

**Transaction items** (`sk = DATE#YYYY-MM-DD#TXN#NNN`):
| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD order date |
| `merchant` | string | Restaurant/service name |
| `platform` | string | Delivery platform (DoorDash, UberEats, etc.) |
| `amount` | number | Order amount ($) |
| `orders_that_day` | number | Total orders that calendar day |
| `is_binge_day` | boolean | True if 3+ orders in one day |
| `day_of_week` | string | Day name (e.g. "Friday") |
| `month` | string | YYYY-MM |
| `year` | number | YYYY |
| `import_date` | string | YYYY-MM-DD of the CSV import |

**Monthly aggregates** (`sk = MONTH#YYYY-MM`):
| Field | Type | Description |
|-------|------|-------------|
| `month` | string | YYYY-MM |
| `year` | number | YYYY |
| `order_count` | number | Total orders that month |
| `total_spend` | number | Total spend ($) |
| `avg_order_size` | number | Average order amount ($) |
| `delivery_index` | number | 0-10 normalized index (10 = worst month) |
| `binge_days` | number | Days with 3+ orders |
| `delivery_days` | number | Distinct days with ≥1 order |
| `orders_per_week` | number | Orders normalized per week |
| `platform_breakdown` | map | Spend per platform |
| `computed_at` | string | ISO timestamp |

**Annual summaries** (`sk = YEAR#YYYY`): per-year rollup with `order_count`, `total_spend`, `avg_order_size`, `binge_days`, `delivery_days`, `orders_per_week`, `computed_at`.

**Streak record** (`sk = STREAK#current`):
| Field | Type | Description |
|-------|------|-------------|
| `streak_days` | number | Current delivery-free streak |
| `streak_start` | string | YYYY-MM-DD streak began (day after last order) |
| `last_order_date` | string | Date of most recent order |
| `last_order_amount` | number | Total $ of the last order day |
| `last_order_merchant` | string | Merchant of the last order |
| `longest_ever_streak` | number | All-time longest clean streak |
| `longest_ever_start` | string | YYYY-MM-DD longest streak began |
| `longest_ever_end` | string | YYYY-MM-DD longest streak ended |
| `updated_at` | string | ISO timestamp |

**Freshness marker** (`sk = DATE#<import_date>`): written on every import with `import_date` and `records_imported` so the freshness checker sees the partition as fresh.

### measurements (body tape measurements)

Periodic (every 4-8 weeks) body tape measurements. Source: `USER#matthew#SOURCE#measurements`.

| Field | Type | Description |
|-------|------|-------------|
| `session_number` | number | Sequential session count |
| `measured_by` | string | Person taking measurements (hardcoded `"brittany"` in the ingestion Lambda) |
| `unit` | string | Always "in" (inches) |
| `source_file` | string | `s3://` path of the source CSV |
| `notes` | string | Optional free-text notes from the CSV |
| `neck_in` | number | Neck circumference |
| `chest_in` | number | Chest circumference |
| `waist_narrowest_in` | number | Waist at narrowest point (Attia priority) |
| `waist_navel_in` | number | Waist at navel (Attia priority — visceral fat proxy) |
| `hips_in` | number | Hip circumference |
| `bicep_relaxed_left_in` | number | Left bicep relaxed |
| `bicep_relaxed_right_in` | number | Right bicep relaxed |
| `bicep_flexed_left_in` | number | Left bicep flexed |
| `bicep_flexed_right_in` | number | Right bicep flexed |
| `calf_left_in` | number | Left calf |
| `calf_right_in` | number | Right calf |
| `thigh_left_in` | number | Left thigh (mid-thigh) |
| `thigh_right_in` | number | Right thigh |
| `waist_height_ratio` | number | Derived: waist_navel / height (target <0.5) |
| `bilateral_symmetry_bicep_in` | number | Derived: abs(R-L) relaxed bicep |
| `bilateral_symmetry_thigh_in` | number | Derived: abs(R-L) thigh |
| `limb_avg_in` | number | Derived: avg of 4 limb measurements |
| `trunk_sum_in` | number | Derived: waist_navel + waist_narrowest |

### macrofactor_workouts (strength training from MacroFactor)

**SOT for:** strength training history (supplementary to Hevy — MacroFactor captures workouts logged within the app)

**Data source:** Granular CSV export from MacroFactor (More → Data Management → Data Export → Granular Export → Workouts). Backfilled via `backfill_macrofactor_workouts.py`.

**Coverage:** 422 items, 2021-04-12 → 2026-02-24

**Day-level summary fields:**

| Field | Type | Description |
|-------|------|-------------|
| `workouts_count` | number | Number of distinct workouts that day |
| `total_sets` | number | Total sets across all exercises |
| `total_volume_lbs` | number | Sum of (weight × reps) across all sets |
| `unique_exercises` | number | Count of distinct exercises performed |
| `ingested_at` | string | ISO timestamp of backfill |

**Nested `workouts` list — each workout:**

| Field | Type | Description |
|-------|------|-------------|
| `workout_name` | string | Name of workout (e.g. "Push", "Pull", "Legs") |
| `workout_duration_min` | number | Duration in minutes (if recorded) |
| `exercises` | list | List of exercise objects (see below) |

**Each exercise object:**

| Field | Type | Description |
|-------|------|-------------|
| `exercise_name` | string | Exercise name (e.g. "Bench Press (Barbell)") |
| `base_weight_lbs` | number | Exercise base/body weight (optional) |
| `sets` | list | List of set objects (see below) |

**Each set object:**

| Field | Type | Description |
|-------|------|-------------|
| `set_index` | number | 1-indexed set number within exercise |
| `set_type` | string | `normal`, `warmup`, `drop`, etc. |
| `weight_lbs` | number | Weight lifted (lbs) |
| `reps` | number | Repetitions |
| `rir` | number | Reps in reserve (optional) |
| `set_duration_sec` | number | Set duration in seconds (optional, for timed exercises) |
| `distance_yards` | number | Distance in yards (optional, for cardio exercises) |
| `distance_miles` | number | Distance in miles (optional) |

Note: This source stores the raw set-level granularity from MacroFactor, complementing Hevy data. Used by the Daily Brief training report for workout detection and volume tracking.

Note: Items can be large due to nested workout/exercise/set structure. Monitor against the 400KB DynamoDB item limit for days with very high training volume.

### garmin

**Status: paused (ADR-074)** — direct-API ingestion retired due to vendor anti-automation. Historical records remain queryable; fields below describe what the Lambda wrote.

**Cross-device biometrics (validate against Whoop / Eight Sleep / Apple Health):**

| Field | Type | Description |
|-------|------|-------------|
| `resting_heart_rate` | number | Daily RHR (bpm) — cross-check with Whoop |
| `hrv_last_night` | number | Overnight HRV average (ms) — cross-check with Whoop |
| `hrv_status` | string | POOR / FAIR / GOOD / EXCELLENT |
| `hrv_5min_high` | number | Best 5-min overnight HRV window (ms) |
| `avg_stress` | number | Daily avg physiological stress 0–100 (HRV-derived) |
| `max_stress` | number | Peak stress level of the day |
| `stress_qualifier` | string | CALM / BALANCED / STRESSFUL / VERY_STRESSFUL |
| `body_battery_high` | number | Peak Body Battery 0–100 |
| `body_battery_low` | number | Minimum Body Battery |
| `body_battery_end` | number | End-of-day Body Battery — readiness input |
| `avg_respiration` | number | Waking respiration (breaths/min) — cross-check with Eight Sleep |
| `sleep_respiration` | number | Sleep respiration (breaths/min) |
| `steps` | number | Step count — cross-check with Apple Health |

**Garmin-exclusive biometrics:**

| Field | Type | Description |
|-------|------|-------------|
| `spo2_avg` | number | Average blood oxygen % (Epix Gen 2+) |
| `spo2_low` | number | Lowest blood oxygen % |
| `vo2_max` | number | Garmin estimated VO2 max |
| `fitness_age` | number | Garmin fitness age estimate |
| `training_status` | string | Garmin training status label (e.g. PRODUCTIVE, MAINTAINING) |
| `training_readiness` | number | Garmin readiness 0–100 |
| `training_readiness_level` | string | Garmin readiness level label |
| `sleep_duration_seconds` | number | Garmin sleep duration (supplementary to Eight Sleep) |
| `sleep_score` | number | Garmin sleep score |
| `hr_zone_0_seconds` | number | Daily seconds in HR Zone 0 (very light) |
| `hr_zone_1_seconds` | number | Daily seconds in HR Zone 1 (light / Zone 2) |
| `hr_zone_2_seconds` | number | Daily seconds in HR Zone 2 (aerobic) |
| `hr_zone_3_seconds` | number | Daily seconds in HR Zone 3 (threshold) |
| `hr_zone_4_seconds` | number | Daily seconds in HR Zone 4 (max) |
| `zone2_minutes` | number | Convenience: Zone 1 seconds / 60 (longevity metric) |
| `intensity_minutes_moderate` | number | Moderate intensity minutes (WHO metric) |
| `intensity_minutes_vigorous` | number | Vigorous intensity minutes |
| `intensity_minutes_total` | number | mod + vig×2 (vigorous counts double per WHO) |
| `floors_climbed` | number | Floors ascended |
| `active_calories` | number | Active kcal burned |
| `bmr_calories` | number | Basal metabolic rate kcal |
| `total_calories_burned` | number | Total kcal (active + BMR) |
| `garmin_acute_load` | number | Garmin 7-day acute training load (replaces removed `training_load` — `extract_training_load` deleted) |
| `garmin_chronic_load` | number | Garmin 28-day chronic training load |
| `garmin_acwr` | number | Acute:chronic workload ratio (acute / chronic) |
| `hrv_weekly_average` | number | 7-day HRV average (ms) |
| `recovery_time_hours` | number | Garmin recommended recovery time (hours) |
| `garmin_activity_count` | number | Number of activities in `garmin_activities` |

Note: `hr_zone_{i}_seconds` covers **every** zone Garmin returns (0–5), not just 0–4 — the extractor enumerates the full `heartRateZones` array.

Note (v1.5.0 sleep expansion): also written when present — `deep_sleep_seconds`, `light_sleep_seconds`, `rem_sleep_seconds`, `awake_sleep_seconds`, `unmeasurable_sleep_seconds`, `sleep_start_local`/`sleep_end_local`, `sleep_spo2_avg`/`sleep_spo2_low`, `sleep_avg_respiration`/`sleep_lowest_respiration`, `restless_moments_count`, and sleep sub-scores `sleep_score_quality`, `sleep_score_duration`, `sleep_score_deep`, `sleep_score_rem`, `sleep_score_light`, `sleep_score_awakenings`.

**Garmin activities (Garmin-proprietary fields; Strava is SOT for GPS/distance/elevation):**

`garmin_activities` is a nested list. Each item:

| Field | Type | Description |
|-------|------|-------------|
| `garmin_activity_id` | string | Garmin activity ID |
| `activity_name` | string | Activity name |
| `activity_type` | string | Type key (running, cycling, etc.) |
| `start_time` | string | Local start time |
| `duration_secs` | number | Duration (seconds) |
| `distance_meters` | number | Distance (metres) |
| `avg_hr` | number | Average heart rate (bpm) |
| `max_hr` | number | Max heart rate (bpm) |
| `calories` | number | Calories burned |
| `avg_speed_mps` | number | Average speed (m/s) |
| `max_speed_mps` | number | Max speed (m/s) |
| `aerobic_training_effect` | number | Aerobic TE score 0–5 (Garmin proprietary) |
| `anaerobic_training_effect` | number | Anaerobic TE score 0–5 |
| `training_effect_label` | string | e.g. "Base Building", "Tempo" |
| `performance_condition` | number | Real-time fitness estimate at finish |
| `lactate_threshold_hr` | number | Estimated LT heart rate (bpm) |
| `lactate_threshold_speed_mps` | number | Estimated LT pace (m/s) |
| `activity_training_load` | number | Per-workout load contribution |
| `body_battery_change` | number | Body Battery drained by this activity |
| `normalized_power_watts` | number | Normalized power (cycling/running power meter) |
| `training_stress_score` | number | TSS (power-based) |
| `avg_cadence` | number | Average cadence (steps/min or rpm) |
| `stride_length_m` | number | Average stride length (m) |
| `ground_contact_time_ms` | number | Ground contact time (ms) |
| `vertical_oscillation_cm` | number | Vertical oscillation (cm) |
| `vertical_ratio_pct` | number | Vertical ratio % |

Note: `body_battery_end` (0–100) is used as the 5th component in `get_readiness_score` (10% weight).

Note: HRV/RHR cross-validation between Garmin and Whoop is available via `get_device_agreement` tool.

Note: Garmin auto-syncs activities to Strava. `garmin_activities` captures Garmin-proprietary analytics only; GPS/distance/elevation remains in `strava` source.

### habitify (P40 habits — active source)

**SOT for:** habits domain (replaced chronicling as of v2.7.0)

| Field | Type | Description |
|-------|------|-------------|
| `habits` | object | Map of habit name → count (Decimal: `1` = completed, `0` = not completed) |
| `habit_statuses` | object | Per-habit structured status map (TD-11): status, completed_at, etc. |
| `by_group` | object | Map of P40 group name → group stats object (see below) |
| `total_completed` | number | Total habits completed that day |
| `total_possible` | number | Total habits tracked that day |
| `pending_count` | number | Habits still pending (deadline not yet passed) — excluded from `completion_pct` denominator (TD-11 phantom-fail fix) |
| `completion_pct` | number | Pending-aware completion 0.0–1.0 |
| `completion_pct_strict` | number | Legacy strict completion (pending counts as miss), for comparison |
| `mood` | number | Habitify mood rating 1–5 (null if not logged) |
| `mood_label` | string | Terrible / Bad / Okay / Good / Excellent (null if not logged) |
| `skipped_count` | number | Habits explicitly skipped |
| `updated_at` | string | ISO timestamp of last write |

Each `by_group` entry:
```json
{
  "completed": 3,
  "possible": 5,
  "pct": 0.6,
  "habits_done": ["Cold Shower", "No alcohol", "No porn"]
}
```

Valid P40 groups: `Data`, `Discipline`, `Growth`, `Hygiene`, `Nutrition`, `Performance`, `Recovery`, `Supplements`, `Wellbeing`.

Note: `Supplements` is new as of v2.7.0 — 19 individual supplement habits broken out from former grouped items.

Access via habit-specific MCP tools (`get_habit_adherence`, `get_habit_streaks`, etc.) for most queries.

### notion (journal — subjective layer)

**SOT for:** journal domain (added v2.16.0)

Notion journal uses multiple SK patterns per day (one per template type):

| SK Pattern | Template |
|-----------|----------|
| `DATE#YYYY-MM-DD#journal#morning` | Morning Check-In |
| `DATE#YYYY-MM-DD#journal#evening` | Evening Reflection |
| `DATE#YYYY-MM-DD#journal#weekly` | Weekly Reflection |
| `DATE#YYYY-MM-DD#journal#stressor#N` | Stressor Deep-Dive (numbered) |
| `DATE#YYYY-MM-DD#journal#health#N` | Health Event (numbered) |
| `DATE#YYYY-MM-DD#journal#journal#N` | Fallback for unstructured entries without a Template property (numbered) |

**Common fields (all templates):**

| Field | Type | Description |
|-------|------|-------------|
| `template` | string | Morning / Evening / Stressor / Health Event / Weekly Reflection |
| `raw_text` | string | Concatenated text of all fields (for Haiku enrichment) |
| `notion_page_id` | string | Notion page UUID |
| `notion_last_edited` | string | Notion last_edited_time ISO |
| `created_at` | string | Notion page created_time ISO |
| `updated_at` | string | ISO timestamp of ingestion write |
| `body_text` | string | Page body content (fetched blocks), when present |

Note: since notion Lambda v1.2.0, property extraction is **dynamic** — `extract_all_properties()` reads ALL properties from each Notion page. The per-template field tables below reflect the current Notion template configuration and can drift if templates change in Notion (no code change required).

**Morning Check-In fields:**

| Field | Type | Description |
|-------|------|-------------|
| `subjective_sleep_quality` | number | 1-5 |
| `morning_energy` | number | 1-5 |
| `morning_mood` | number | 1-5 |
| `physical_state` | list | Fresh, Sore, Stiff, Pain, Fatigued, Energized |
| `body_region` | list | Lower Back, Knees, Shoulders, Neck, Hips, General |
| `todays_intention` | string | Free text |
| `notes` | string | Free text |

**Evening Reflection fields:**

| Field | Type | Description |
|-------|------|-------------|
| `day_rating` | number | 1-5 |
| `stress_level` | number | 1-5 |
| `stress_source` | list | Work, Family, Health, Financial, Social, None |
| `energy_eod` | number | 1-5 |
| `workout_rpe` | number | 1-10 |
| `hunger_cravings` | list | Controlled, Hungry all day, Sugar cravings, Late-night snacking, Low appetite |
| `win_of_the_day` | string | Free text |
| `what_drained_me` | string | Free text |
| `notable_events` | string | Free text |
| `tomorrow_focus` | string | Free text |

**Stressor Deep-Dive fields:**

| Field | Type | Description |
|-------|------|-------------|
| `stress_intensity` | number | 1-10 |
| `stress_category` | string | Work, Family, Health, Financial, Social, Existential |
| `what_happened` | string | Free text |
| `physical_response` | list | Heart racing, Tension, Shallow breathing, Stomach, Headache, None |
| `what_i_did` | string | Free text |
| `resolution` | string | Resolved, Ongoing, Escalated, Accepted |

**Health Event fields:**

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | Illness, Injury, Symptom, Medication Change, Supplement Change |
| `description` | string | Free text |
| `severity` | string | Mild, Moderate, Severe |
| `duration` | string | Hours, Days, Ongoing |
| `impact_on_training` | string | None, Modified, Skipped, Full Rest |

**Weekly Reflection fields:**

| Field | Type | Description |
|-------|------|-------------|
| `week_rating` | number | 1-5 |
| `biggest_win` | string | Free text |
| `biggest_challenge` | string | Free text |
| `what_would_i_change` | string | Free text |
| `emerging_pattern` | string | Free text |
| `next_week_priority` | string | Free text |

**Haiku-enriched fields (written by journal-enrichment Lambda):**

| Field | Type | Description |
|-------|------|-------------|
| `enriched_mood` | number | 1-5 synthesized mood score |
| `enriched_energy` | number | 1-5 synthesized energy score |
| `enriched_stress` | number | 1-5 stress score (1=calm, 5=overwhelmed) |
| `enriched_sentiment` | string | positive/neutral/negative/mixed |
| `enriched_emotions` | list | Precise emotional vocabulary |
| `enriched_themes` | list | Life themes (max 4) |
| `enriched_cognitive_patterns` | list | CBT patterns (catastrophizing, reframing, etc.) |
| `enriched_growth_signals` | list | Evidence of learning/growth |
| `enriched_avoidance_flags` | list | Things being avoided |
| `enriched_ownership` | number | 1-5 locus of control |
| `enriched_social_quality` | string | alone/surface/meaningful/deep |
| `enriched_flow` | boolean | Evidence of deep engagement |
| `enriched_values_lived` | list | Core values evidenced in actions |
| `enriched_gratitude` | list | Specific gratitude items |
| `enriched_alcohol` | boolean | Alcohol mention detected |
| `enriched_sleep_context` | string | Sleep-disruption context |
| `enriched_pain` | list | Pain mentions |
| `enriched_exercise_context` | string | Exercise context |
| `enriched_notable_quote` | string | Most revealing sentence |
| `enriched_at` | string | ISO timestamp of enrichment |

**Defense mechanism enrichment fields (v2.72.0, second Haiku pass):**

| Field | Type | Description |
|-------|------|-------------|
| `enriched_defense_patterns` | list | Detected defense mechanisms: intellectualization, avoidance, displacement, rationalization, isolation_of_affect, minimization, projection, denial, sublimation, humor_as_deflection, compartmentalization |
| `enriched_primary_defense` | string | Single most prominent defense (null if none) |
| `enriched_defense_context` | string | 1-sentence description of what's being defended against |
| `enriched_emotional_depth` | number | 1-5 emotional depth rating (1=very surface/avoidant, 5=deep processing) |
| `defense_enriched_at` | string | ISO timestamp of defense enrichment |

### labs (blood work / biomarkers)

**SOT for:** biochemical/labs domain

Labs data uses the standard PK pattern but has an additional SK pattern for provider metadata:
- Draw records: `DATE#YYYY-MM-DD` (one item per blood draw date)
- Provider metadata: `PROVIDER#<provider>#<period>` (e.g. `PROVIDER#function_health#2025-spring`)

Each draw record contains all biomarkers from that blood draw as a nested `biomarkers` dict. Item sizes are small (~7-16 KB per draw) — well within the 400KB DynamoDB limit even for 100+ biomarkers.

**Draw record fields:**

| Field | Type | Description |
|-------|------|-------------|
| `draw_date` | string | YYYY-MM-DD collection date |
| `lab_provider` | string | e.g. `function_health`, `inside_tracker`, `gp_panel` |
| `lab_network` | string | Lab network e.g. `quest_diagnostics` |
| `specimen_id` | string | Lab accession number |
| `collection_date` | string | YYYY-MM-DD |
| `report_date` | string | YYYY-MM-DD |
| `biomarkers` | object | Map of biomarker_key → biomarker object (see below) |
| `out_of_range` | list | List of biomarker keys flagged high/low |
| `out_of_range_count` | number | Count of out-of-range biomarkers |
| `total_biomarkers` | number | Total biomarkers in this draw |
| `urinalysis` | object | Optional — urinalysis results if included |
| `metadata` | object | Patient info, physician, test round |
| `clinician_summary` | object | Optional — per-category clinician notes |

**Biomarker object structure:**

| Field | Type | Description |
|-------|------|-------------|
| `value` | number/string | Raw value (string for qualitative like "NEGATIVE", "<10") |
| `value_numeric` | number | Numeric value for trending (null for qualitative) |
| `unit` | string | Unit of measure |
| `ref_text` | string | Original reference range text |
| `ref_low` | number | Lower bound (null if one-sided or none) |
| `ref_high` | number | Upper bound (null if one-sided or none) |
| `flag` | string | `normal` / `high` / `low` / `carrier` / `noncarrier` |
| `category` | string | Biomarker category (see below) |
| `fh_category` | string | Function Health classification: `In Range` / `Out of Range` / `Other` |

**Biomarker categories:** `cbc`, `cbc_differential`, `cardiovascular`, `digestive`, `electrolytes`, `genetics`, `hormones`, `immune`, `inflammation`, `iron`, `kidney`, `lipids`, `lipids_advanced`, `liver`, `metabolic`, `minerals`, `omega_fatty_acids`, `prostate`, `thyroid`, `toxicology`, `vitamins`, `blood_type`

**Biomarker keys** are snake_case normalized names: `apob`, `ldl_c`, `testosterone_total`, `vitamin_d_25oh`, `hs_crp`, etc.

**Provider metadata fields:**

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | Provider name |
| `test_period` | string | e.g. "Spring 2025" |
| `total_biomarkers_tested` | number | Total across all draws |
| `in_range_count` | number | Function Health "In Range" count |
| `out_of_range_count` | number | Function Health "Out of Range" count |
| `biological_age_delta_years` | number | Years younger/older than chronological |
| `draw_dates` | list | List of draw date strings |
| `food_recommendations` | object | Enjoy/avoid lists + focus areas |
| `supplement_recommendations` | object | Reduce/maintain/consider lists |


**ASCVD Risk Score fields (on draw records):**

| Field | Type | Description |
|-------|------|-------------|
| `ascvd_risk_10yr_pct` | number/string | 10-year ASCVD risk percentage (Pooled Cohort Equations). String "insufficient_data..." if missing TC/HDL. |
| `ascvd_risk_category` | string | `low` (<5%), `borderline` (5-7.5%), `intermediate` (7.5-20%), `high` (>20%) |
| `ascvd_inputs` | object | All inputs used: age, sex, race, TC, HDL, SBP, bp_treated, is_diabetic, is_smoker, systolic_bp_source |
| `ascvd_equation` | string | "Pooled Cohort Equations (2013 ACC/AHA)" |
| `ascvd_caveats` | list | Any caveats (e.g. age extrapolation outside 40-79 range) |

Note: SBP currently uses estimate (125 mmHg) — `ascvd_inputs.systolic_bp_source` tracks provenance. Update when BP monitor data available.

Access via labs-specific MCP tools (`get_lab_results`, `get_lab_trends`, `get_out_of_range_summary`).

### dexa (body composition scans)

**SOT for:** precision body composition (more accurate than Withings for lean mass, body fat, visceral fat)

**Key Pattern:**
- PK: `USER#matthew#SOURCE#dexa`
- SK: `DATE#YYYY-MM-DD` (one item per scan date)

| Field | Type | Description |
|-------|------|-------------|
| `scan_date` | string | YYYY-MM-DD |
| `facility` | string | e.g. "DexaFit Seattle" |
| `scan_type` | string | `dexa_body_composition` |
| `body_composition.weight_lbs` | number | Total body weight |
| `body_composition.body_fat_pct` | number | Whole-body fat % |
| `body_composition.lean_mass_lbs` | number | Lean body mass |
| `body_composition.fat_mass_lbs` | number | Total fat mass |
| `body_composition.android_gynoid_ratio` | number | A/G ratio (target ≤1.0) |
| `body_composition.visceral_fat_g` | number | Visceral adipose tissue (grams) |
| `bone_density.t_score` | number | BMD T-score |
| `bone_density.z_score` | number | BMD Z-score |
| `posture_assessment` | object | Kinetisense 3D captures (frontal, sagittal, transverse) |
| `interpretations` | object | Percentile ranks, clinical context, goals |
| `goals` | object | 6-month targets for body fat, lean mass, A/G ratio |

Manual entry source — new scans seeded via `seed_physicals_dexa.py`. Cadence: semi-annual.

### genome (SNP clinical interpretations)

**Key Pattern:**
- PK: `USER#matthew#SOURCE#genome`
- SK: `GENE#<gene_name>#SNP#<rsid>` (one item per SNP) or `SUMMARY` (aggregate record)

Stores ONLY clinical interpretations and actionable recommendations — no raw genome data (privacy by design).

**SNP record fields:**

| Field | Type | Description |
|-------|------|-------------|
| `gene` | string | Gene name (e.g. "FTO", "MTHFR", "CYP1A2") |
| `rsid` | string | dbSNP identifier (e.g. "rs9939609") |
| `genotype` | string | Observed genotype (e.g. "A;T", "C;C") |
| `summary` | string | One-line clinical interpretation |
| `category` | string | See categories below |
| `risk_level` | string | `favorable` / `neutral` / `unfavorable` / `mixed` |
| `details` | string | Extended interpretation with study context |
| `actionable_recs` | list | Specific lifestyle/diet/supplement recommendations |
| `related_biomarkers` | list | Lab biomarkers this SNP influences (e.g. `["ldl_c", "homocysteine"]`) |
| `report_date` | string | Date of source report |
| `report_type` | string | `comprehensive_snp_interpretation` |

**Categories:** `metabolism`, `longevity`, `nutrient_metabolism`, `lipids`, `immune`, `taste`, `exercise`, `sleep`, `miscellaneous`, `statin_response`, `antioxidant`, `cardiovascular`, `caffeine`, `cancer_risk`

**Summary record (SK = SUMMARY):**

| Field | Type | Description |
|-------|------|-------------|
| `total_snps` | number | Count of SNP records |
| `risk_distribution` | object | Count per risk_level |
| `category_distribution` | object | Count per category |
| `key_actionable_themes` | list | Top-10 cross-SNP actionable themes |
| `blood_type` | string | e.g. "A_Rh_D_Positive" |
| `blood_type_date` | string | Date blood type was determined |

Note: `related_biomarkers` enables cross-referencing genome data with labs data. For example, ABCG8 rs6544713 T;T (elevated LDL) can be correlated with actual LDL-C trends across GP blood draws.

### chronicling (P40 habits — historical archive)

**Status:** Archived. Last record: 2025-11-09. Data preserved at `USER#matthew#SOURCE#chronicling`.

| Field | Type | Description |
|-------|------|-------------|
| `habits` | object | Map of habit name → count (Decimal: `1` = completed, `0` = not) |
| `by_group` | object | Map of P40 group name → group stats object (same format as habitify) |
| `total_completed` | number | Total habits completed that day |
| `total_possible` | number | Total habits tracked that day |
| `completion_pct` | number | Overall completion 0.0–1.0 |

Valid P40 groups (historical): `Data`, `Discipline`, `Growth`, `Hygiene`, `Nutrition`, `Performance`, `Recovery`, `Wellbeing`.

Note: Field names documented here match the actual DynamoDB records and MCP server code (`_habit_series()`). Previous documentation incorrectly listed `total_score` and `group_scores` — those field names were never used in practice.

Access via habit-specific MCP tools when `source_of_truth.habits` is set to `chronicling`.

### supplements (supplement & medication log)

**SOT for:** supplement tracking domain (added v2.36.0)

**Data source:** Manual logging via `log_supplement` MCP tool. Multiple entries per day appended to a list.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `supplements` | list | List of supplement entry objects (see below) |
| `updated_at` | string | ISO timestamp of last write |

**Each supplement entry object:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Supplement or medication name (e.g. "Magnesium Glycinate") |
| `dose` | number | Dosage amount (e.g. 500 for 500mg) |
| `unit` | string | Unit: mg, mcg, g, IU, ml, capsule, tablet |
| `timing` | string | When taken: morning, with_meal, before_bed, post_workout, evening, afternoon |
| `category` | string | supplement, medication, vitamin, mineral |
| `notes` | string | Optional free text |
| `logged_at` | string | ISO timestamp of when the entry was logged |

Access via `log_supplement`, `get_supplement_log`, `get_supplement_correlation` MCP tools.

Note: Daily Brief reads this partition to show today's logged supplements and 7-day adherence chips per supplement.

**Habitify supplement bridge:** the habitify ingestion Lambda's post-store hook (`supplement_bridge` in `habitify_lambda.py`) side-writes checked supplement habits into this partition. The day's record carries `bridge_source: "habitify"` and each bridged entry has `source: "habitify_bridge"` with dose/unit/timing from a hardcoded `SUPPLEMENT_MAP`. The bridge **overwrites the day's record** (`put_item`) — manual `log_supplement` entries for the same day can be replaced on the next habitify sync.

### weather (Seattle daily weather)

**SOT for:** weather/environment domain (added v2.36.0)

**Data source:** Open-Meteo archive API (free, no auth, WMO-grade data). Two ingestion paths:
- **Scheduled Lambda** (`weather-data-ingestion`): EventBridge at 5:45 AM PT, fetches yesterday + today
- **MCP on-demand** (`get_weather_correlation`): fetches and caches any missing dates

**Location:** Seattle, WA (47.6062, -122.3321)

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `temp_high_f` | number | Daily high temperature (°F) |
| `temp_low_f` | number | Daily low temperature (°F) |
| `temp_avg_f` | number | Daily mean temperature (°F) |
| `humidity_pct` | number | Average relative humidity (%) |
| `precipitation_mm` | number | Total daily precipitation (mm) |
| `wind_speed_max_mph` | number | Peak wind speed (mph) |
| `pressure_hpa` | number | Average surface barometric pressure (hPa) |
| `daylight_hours` | number | Total daylight duration (hours) — Huberman: master circadian lever |
| `sunshine_hours` | number | Total sunshine duration (hours) — actual sun vs just daylight |
| `uv_index_max` | number | Peak UV index |
| `ingested_at` | string | ISO timestamp of ingestion (Lambda-written records only) |

Note: Barometric pressure <1008 hPa correlates with increased joint inflammation and headaches (Attia). Daylight hours <10h in Seattle winter months may require light therapy intervention.

Note: Daily Brief reads this partition to show weather context (temperature, daylight, precipitation, pressure) with coaching nudges.

Note: S3 raw backup at `raw/weather/YYYY/MM/DD.json` (Lambda path only).

### state_of_mind (How We Feel / Apple Health State of Mind)

**SOT for:** state_of_mind domain (added v2.41.0)

**Data source:** How We Feel app → Apple HealthKit State of Mind → Health Auto Export webhook (separate Data Type automation from health metrics). Webhook Lambda v1.5.0 detects State of Mind payloads and processes them separately.

**Storage location:** there is **no** `SOURCE#state_of_mind` DynamoDB partition — the `som_*` daily aggregates below are merged into the **apple_health** partition (`pk = USER#matthew#SOURCE#apple_health`, `sk = DATE#YYYY-MM-DD`) via the HAE webhook Lambda's merge path. `state_of_mind` in the SOT table is a domain label, not a partition.

**S3 raw:** Individual check-ins stored at `raw/matthew/state_of_mind/YYYY/MM/DD.json` with full detail (timestamp, kind, valence, labels, associations, source).

**DynamoDB daily aggregates (in the apple_health partition):**

| Field | Type | Description |
|-------|------|-------------|
| `som_avg_valence` | number | Average valence for the day (-1.0 to +1.0) |
| `som_min_valence` | number | Lowest valence check-in |
| `som_max_valence` | number | Highest valence check-in |
| `som_check_in_count` | number | Total State of Mind check-ins |
| `som_mood_count` | number | Count of dailyMood entries |
| `som_emotion_count` | number | Count of momentaryEmotion entries |
| `som_top_labels` | string | Comma-joined most frequent emotion labels (e.g. `"content, anxious"`) — a string, not a list |
| `som_top_associations` | string | Comma-joined most frequent life area associations (e.g. `"work, health"`) — a string, not a list |

**Check-in kinds:** `dailyMood` (overall day rating) and `momentaryEmotion` (in-the-moment capture).

**Valence classifications:** very_unpleasant / unpleasant / slightly_unpleasant / neutral / slightly_pleasant / pleasant / very_pleasant

Note: Idempotent ingestion — deduplicates by timestamp on re-ingestion. Requires a separate HAE automation with Data Type = "State of Mind" (same URL + auth as existing health metrics automation).

Access via `get_state_of_mind_trend` MCP tool.

---

### weight_episodes (BENCH-1 — derived cut/regain ledger)

Computed source written weekly by the `episode-detect` Lambda (ADR-089). One item per
detected ≥15 lb loss/regain episode over the full Withings history. Cross-phase reference
data — written **without** a `phase` attribute (survives a reset; passes the ADR-058 filter).

**pk:** `USER#matthew#SOURCE#weight_episodes` · **sk:** `DATE#{end_date}` (trough for loss, peak for regain)

| Field | Type | Description |
|-------|------|-------------|
| `episode_id` | string | e.g. `2024-09-05_loss` |
| `type` | string | `loss` \| `regain` |
| `start_date` / `end_date` | string | episode bounds (YYYY-MM-DD) |
| `w_start` / `w_end` / `magnitude_lb` | number | smoothed weights + |Δ| |
| `duration_wk` / `rate_lb_wk` / `peak_rate_lb_wk` | number | duration + mean/peak weekly rate |
| `covariates_during` | map | `{walks_wk, walk_hr_wk, runs_wk, lift_sessions_wk, lift_sets_wk}` |
| `covariates_reliable` | bool | false when window start < 2020-01-01 (sparse Strava) |
| `post_trough_8wk` | map | `{walks_wk, walk_hr_wk}` (loss episodes only) |
| `regain_180d_lb` / `outcome` | number / string | loss only — `held` (regain < magnitude/3) \| `reversed` |
| `confidence` | string | `low` while total episode n < 30 |

Access via `get_benchmark(view="episodes")`. PRIVATE.

### training_reference (BENCH-1 — proven by-band prescription, singleton)

Singleton computed source (ADR-089). Readers take the newest in-range record (the
`computed_metrics` read pattern). Cross-phase; no TTL; no `phase` attribute.

**pk:** `USER#matthew#SOURCE#training_reference` · **sk:** `DATE#{derived_date}`

| Field | Type | Description |
|-------|------|-------------|
| `bands` | map | by-bodyweight-band proven volumes, e.g. `{"300-309": {walks_wk, walk_hr_wk, runs_wk, lift_sessions_wk}}` |
| `proven_curve` | list | the 2024-09→2025-04 trajectory: `[{weight, days_from_start, cum_lost, walks_wk}, …]` |
| `source_window` | string | `2024-09-05..2025-04-30` |
| `derived_at` | string | ISO timestamp of the compute |
| `confidence` | string | `low` |
| `n_episodes_with_covariates` | number | episodes contributing covariates |

Access via `get_benchmark(view="pace"/"maintenance")`. PRIVATE.

### macrofactor_meals (derived meal layer — best-effort meal grouping)

Recomputable projection (ADR-090) over the raw `macrofactor` food log, written by the
deterministic `meal_grouper` (shared layer). Groups individual food entries into the
meals they were eaten as. **Raw is never mutated** — `member_refs`/`sides` are pointers
into the `macrofactor` partition; `rollup` is a cached sum, raw wins on any disagreement.
Every record is an inference: `inferred:true` + `confidence`. Conservation holds — every
raw entry lands in exactly one group, so `sum(rollups) == raw daily totals`. Written by
`deploy/backfill_meals.py` (history) and `manage_meals regroup_day` (one day). No `phase`
attribute (a recompute artifact, not phase-scoped experiment data).

**pk:** `USER#matthew#SOURCE#macrofactor_meals` · **sk:** `DATE#YYYY-MM-DD#MEAL#<NN>` (ordinal = time order, e.g. `DATE#2026-06-18#MEAL#03`)

| Field | Type | Description |
|-------|------|-------------|
| `ordinal` | number | 1-based position within the day (time-ordered) |
| `meal_name` | string | display label, e.g. `Turkey Tacos` — **cosmetic; aggregates never key on this** |
| `template_id` | string \| null | e.g. `tpl_turkey_tacos`; null for snacks/uncategorized |
| `kind` | string | `meal` \| `snack` \| `uncategorized` (uncategorized = counted in totals, excluded from meal analytics) |
| `method` | string | `template` \| `content_split+template` \| `singleton` \| `uncategorized` |
| `confidence` | number | 0–1 coverage score (fraction of the cluster the template explains, by items + calories) |
| `signature` | string | `<sorted canonical tokens>#<hash>` — stable cluster identity; the analytics key |
| `time_window` | map | `{start, end}` (HH:MM) |
| `member_refs` | list | `[{idx, food_name, time, token}]` — pointers into raw |
| `sides` | list | orphan add-ons attached to the meal (`attached:true`) |
| `rollup` | map | cached `{calories_kcal, protein_g, carbs_g, fat_g, fiber_g, sugars_g}` |
| `algo_version` | string | e.g. `meal-grouper@1.1.0` — enables safe full-history recompute |

Locked params: `GAP_MIN=15`, `CONF_MIN=0.7`. Canonical vocabulary: `config/food_vocabulary.json`.
Access via `manage_meals` (`get_day` / `most_eaten` / `regroup_day` / `list_templates`). The
LLM namer for residual `uncategorized` clusters is Phase 2 (deferred).

---

## Profile Record

**pk:** `USER#matthew`  
**sk:** `PROFILE#v1`

| Field | Description |
|-------|-------------|
| `name` | Display name |
| `date_of_birth` | YYYY-MM-DD |
| `height_inches` | For BMR calculations |
| `biological_sex` | For Mifflin-St Jeor |
| `goal_weight_lbs` | Weight loss target |
| `journey_start_date` | Reference date for progress tracking |
| `timezone` | User timezone string |
| `day_grade_weights` | object | Per-component weights for day grade (sleep_quality, recovery, etc.) |
| `mvp_habits` | list | Habit names tracked in MVP scorecard (legacy, superseded by habit_registry) |
| `habit_registry` | map | 65-habit registry with tier/category/mechanism/synergy metadata (v2.47.0) |
| `weight_loss_phases` | list | Phase objects with start_lbs, end_lbs, weekly_target_lbs |
| `demo_mode_rules` | object | Rules for demo/share sanitization (see below) |
| `source_of_truth` | object | Per-domain SOT overrides (see below) |

---

### Source-of-Truth block (inside profile)

The `source_of_truth` field overrides the default authoritative source per domain. If absent, the MCP server falls back to hardcoded defaults.

```json
{
  "cardio":              "strava",
  "strength":            "hevy",
  "physiology":          "whoop",
  "nutrition":            "macrofactor",
  "sleep":               "eightsleep",
  "body":                "withings",
  "steps":               "apple_health",
  "tasks":               "todoist",
  "habits":              "habitify",
  "stress":              "garmin",
  "body_battery":        "garmin",
  "gait":                "apple_health",
  "energy_expenditure":  "apple_health",
  "cgm":                 "apple_health",
  "caffeine":             "apple_health",
  "supplements":          "supplements",
  "weather":              "weather",
  "state_of_mind":        "state_of_mind",
  "journal":              "notion"
}
```

Change one field here (e.g. `"cardio": "garmin"`) to switch source ownership without any code changes.

---

### Demo Mode Rules (inside profile)

The `demo_mode_rules` field controls how the daily brief is sanitized when invoked with `{"demo_mode": true}`. Update in DynamoDB without redeployment.

```json
{
  "redact_patterns": ["marijuana", "thc", "cannabis", "weed", "alcohol", "bourbon"],
  "replace_values": {
    "weight_lbs": "•••",
    "calories": "•,•••",
    "protein": "•••"
  },
  "hide_sections": ["journal_pulse", "journal_coach", "weight_phase"],
  "subject_prefix": "[DEMO]"
}
```

**Available sections for `hide_sections`:** scorecard, readiness, training, nutrition, habits, cgm, weight_phase, guidance, journal_pulse, journal_coach, bod

---

## Travel Partition (v2.40.0)

**pk:** `USER#matthew#SOURCE#travel`
**sk:** `TRIP#<slug>_<start_date>` (e.g. `TRIP#london_2026-03-15`)

Written by `log_travel` MCP tool. Read by anomaly detector and daily brief for travel-aware behavior.

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL-safe city name (e.g. "london", "new_york") |
| `destination_city` | string | City name |
| `destination_country` | string | Country name |
| `destination_timezone` | string | IANA timezone (e.g. "Europe/London") |
| `home_timezone` | string | Always "America/Los_Angeles" |
| `tz_offset_hours` | number | Dest offset - home offset (e.g. +8 for London from Seattle) |
| `direction` | string | `eastbound` / `westbound` / `same_zone` |
| `start_date` | string | YYYY-MM-DD trip start |
| `end_date` | string | YYYY-MM-DD trip end (null if active) |
| `purpose` | string | `personal` / `work` / `family` / `vacation` |
| `status` | string | `active` / `completed` |
| `notes` | string | Free text |
| `created_at` | string | ISO timestamp |
| `updated_at` | string | ISO timestamp |

Integration points:
- **Anomaly detector v2.1.0:** Checks travel partition before alerting. If traveling, records anomalies but suppresses alert email with `severity: travel_suppressed`.
- **Daily Brief v2.5.0:** Shows travel banner with Huberman jet lag protocol when active trip detected.
- **Jet Lag Recovery tool:** Compares pre-trip baseline to post-return recovery curve.

---

## Anomalies Partition

**pk:** `USER#matthew#SOURCE#anomalies`
**sk:** `DATE#YYYY-MM-DD`

Written daily by `anomaly-detector` Lambda at 8:05am PT. The daily brief reads this record to decide whether to inject an anomaly section.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `anomalous_metrics` | list | List of flagged metric objects (see below) |
| `source_count` | number | Number of distinct sources with anomalies |
| `alert_sent` | boolean | Whether an alert email was sent |
| `hypothesis` | string | Haiku-generated root cause hypothesis (empty if no alert) |
| `severity` | string | `none` / `moderate` / `high` / `travel_suppressed` |
| `travel_mode` | boolean | True if date fell within an active trip (v2.1.0) |
| `travel_destination` | string | Destination city if traveling (v2.1.0) |
| `updated_at` | string | ISO timestamp of last write |

Each item in `anomalous_metrics`:
```json
{
  "source": "whoop",
  "field": "hrv",
  "label": "HRV",
  "yesterday_val": 38.5,
  "baseline_mean": 61.2,
  "baseline_sd": 8.4,
  "z_score": -2.70,
  "direction": "low",
  "pct_from_mean": -37.1
}
```

Alert logic: `severity = moderate/high` only when `source_count >= 2`. Single-source anomalies are recorded but do not trigger an alert email.

---

## Insights Partition

**pk:** `USER#matthew#SOURCE#insights`  
**sk:** `INSIGHT#<ISO-timestamp>` (e.g. `INSIGHT#2026-02-23T09:15:00`)

One item per saved insight. Written by `save_insight` MCP tool; updated by `update_insight_outcome`.

| Field | Type | Description |
|-------|------|-------------|
| `insight_id` | string | ISO timestamp (same as SK suffix) — used to reference the insight |
| `text` | string | Full insight text |
| `date_saved` | string | YYYY-MM-DD date saved |
| `source` | string | `chat` (default) or `email` |
| `status` | string | `open` / `acted` / `resolved` |
| `outcome_notes` | string | What happened when acted on (empty until updated) |
| `tags` | list | Optional string tags e.g. `["sleep", "caffeine"]` |
| `date_updated` | string | YYYY-MM-DD of last status update (added by `update_insight_outcome`) |

Stale flag: insights with `status=open` and `days_open >= 7` are flagged by `get_insights`. Weekly digest surfaces these as an "Open Insights" amber section (live since v3.5.0). The 7-day threshold was tightened from the original 14-day plan.

---

## Day Grade Partition

**pk:** `USER#matthew#SOURCE#day_grade`  
**sk:** `DATE#YYYY-MM-DD`

One item per day. Written by the Daily Brief Lambda after computing the weighted day grade, or by `retrocompute_day_grades.py` for historical backfill.

**Coverage:** 948 records (2023-07-23 → present). 947 retrocomputed + daily brief going forward.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `total_score` | number | Weighted composite 0-100 |
| `letter_grade` | string | A+ through F |
| `algorithm_version` | string | Current: "1.1" (v2.22.1 fixes: journal=None when no entries, hydration <118ml = not tracked) |
| `weights_snapshot` | object | Copy of day_grade_weights used for this computation |
| `computed_at` | string | ISO timestamp |
| `source` | string | "retrocompute" for backfilled records; absent for daily-brief-computed records |
| `component_sleep_quality` | number | 0-100 (or absent if no data) |
| `component_recovery` | number | 0-100 |
| `component_nutrition` | number | 0-100 |
| `component_movement` | number | 0-100 |
| `component_habits_mvp` | number | 0-100 |
| `component_hydration` | number | 0-100 |
| `component_journal` | number | 0-100 |
| `component_glucose` | number | 0-100 |

Retrocompute: Weight changes → instant recompute from stored components. Component formula changes → recompute from raw source data using `retrocompute_day_grades.py --write --force`.

---

## Habit Scores Partition (v2.47.0)

**pk:** `USER#matthew#SOURCE#habit_scores`  
**sk:** `DATE#YYYY-MM-DD`

One item per day. Written by the Daily Brief Lambda (v2.47.0+) after computing tier-weighted habit scores. Derived data — not raw ingested. Enables historical trending without recomputing from raw Habitify data.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `tier0_done` | number | Count of completed Tier 0 habits |
| `tier0_total` | number | Total applicable Tier 0 habits for this day |
| `tier0_pct` | number | Tier 0 completion percentage (0.0–1.0) |
| `tier1_done` | number | Count of completed Tier 1 habits |
| `tier1_total` | number | Total applicable Tier 1 habits |
| `tier1_pct` | number | Tier 1 completion percentage |
| `vices_held` | number | Count of vices successfully avoided |
| `vices_total` | number | Total tracked vices |
| `vice_streaks` | map | Per-vice streak snapshot: `{"No Alcohol": 14, "No THC": 7, ...}` |
| `synergy_groups` | map | Per-group completion %: `{"Sleep Stack": 0.8, "Morning Routine": 1.0, ...}` |
| `missed_tier0` | list | Names of missed Tier 0 habits (for pattern detection) |
| `composite_score` | number | Tier-weighted composite score (T0=3x, T1=1x, T2=0.5x) |
| `scoring_method` | string | `tier_weighted_v1` — marks transition from binary scoring |

Queried by MCP tools: `get_habit_tier_report`, `get_vice_streak_history`.

---

## Character Sheet Partition (v1.1.0)

**pk:** `USER#matthew#SOURCE#character_sheet`
**sk:** `DATE#YYYY-MM-DD`

One item per day. Computed by the backfill script initially, then by the Daily Brief Lambda (Phase 2). Contains the full character state: overall level, all 7 pillar scores, XP, tier info, cross-pillar effects, and level events. Sequential dependency — each day's computation requires the previous day's state for streak tracking and level transitions. Engine v1.1.0 adds confidence scoring, XP decay, progressive difficulty, and per-pillar EMA smoothing.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `character_level` | number | Overall weighted level (1-100), uses `math.floor()` of weighted pillar average |
| `character_tier` | string | Current tier name: Foundation / Momentum / Discipline / Mastery / Elite |
| `character_tier_emoji` | string | Tier emoji |
| `character_xp` | number | Cumulative total XP across all pillars |
| `min_confidence` | number | Lowest pillar confidence (0.0–1.0). v1.1.0+ |
| `avg_confidence` | number | Average pillar confidence (0.0–1.0). v1.1.0+ |
| `active_effects` | list | Active cross-pillar effects (e.g., Sleep Drag, Training Boost) |
| `level_events` | list | Events that occurred this day (level_up, level_down, tier_up, tier_down) |
| `engine_version` | string | Version of character_engine.py that computed this record |
| `computed_at` | string | ISO timestamp of computation |
| `pillar_sleep` | map | Sleep pillar: raw_score, level_score, level, tier, xp_total, xp_delta, streak_above, streak_below, components |
| `pillar_movement` | map | Movement pillar (same structure) |
| `pillar_nutrition` | map | Nutrition pillar (same structure) |
| `pillar_metabolic` | map | Metabolic Health pillar (same structure) |
| `pillar_mind` | map | Mind pillar (same structure) |
| `pillar_relationships` | map | Relationships pillar (same structure) |
| `pillar_consistency` | map | Consistency meta-pillar (same structure) |

**Pillar sub-fields (each `pillar_*` map):**

| Field | Type | Description |
|-------|------|-------------|
| `raw_score` | number | Today's unsmoothed score (0-100) |
| `level_score` | number | EMA-smoothed score after cross-pillar effects |
| `level` | number | Discrete level (1-100), changes subject to progressive streak rules |
| `tier` | string | Pillar tier name |
| `tier_emoji` | string | Tier emoji |
| `xp_total` | number | Cumulative XP for this pillar (decays daily by `daily_xp_decay`) |
| `xp_delta` | number | Net XP change today (earned − decay) |
| `xp_earned` | number | Raw XP earned today before decay. v1.1.0+ |
| `xp_buffer` | number | XP within current level (0 to xp_per_level). Protects against level-down. v1.1.0+ |
| `confidence` | number | Data completeness confidence (0.0–1.0). v1.1.0+ |
| `data_coverage` | number | Ratio of available to max component weight (0.0–1.0). v1.1.0+ |
| `streak_above` | number | Consecutive days target_level > current_level |
| `streak_below` | number | Consecutive days target_level < current_level |
| `components` | map | Per-component scores: `{"component_name": {"score": N, "weight": W}, "_confidence": N, "_data_coverage": N}` |

Config: `s3://matthew-life-platform/config/character_sheet.json`  
Queried by MCP tools: `get_character_sheet`, `get_pillar_detail`, `get_level_history`.

---

## Computed Metrics Partition (v2.82.0 / IC MAINT)

**pk:** `USER#matthew#SOURCE#computed_metrics`  
**sk:** `DATE#YYYY-MM-DD`

Pre-computed daily metrics written by `daily-metrics-compute` Lambda at 9:40 AM PT (before Daily Brief). The Daily Brief reads this partition first with inline fallback to raw source computation if absent.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `day_grade_total` | number | Weighted composite day grade (0-100) |
| `day_grade_letter` | string | A+ through F |
| `readiness_score` | number | 0-100 composite readiness |
| `readiness_level` | string | GREEN / YELLOW / RED |
| `hrv_7d_avg` | number | 7-day HRV rolling average (ms) |
| `hrv_trend` | string | improving / stable / declining |
| `weight_7d_avg` | number | 7-day weight rolling average (lbs) |
| `tsb` | number | Training Stress Balance (ATL-CTL) |
| `atl` | number | Acute Training Load (7-day) |
| `ctl` | number | Chronic Training Load (42-day) |
| `zone2_minutes_7d` | number | Zone 2 minutes in rolling 7 days |
| `consecutive_logging_days` | number | Streak of days with nutrition logged |
| `habit_streak_t0` | number | Consecutive days all Tier 0 habits completed |
| `computed_at` | string | ISO timestamp of computation |

---

## Weekly Correlations Partition (R8-LT9, v3.7.20)

**pk:** `USER#matthew#SOURCE#weekly_correlations`  
**sk:** `WEEK#<iso_week>` (e.g. `WEEK#2026-W11`)

Pearson correlations between 20 key metric pairs computed weekly over a 90-day rolling window. Written by `weekly-correlation-compute` Lambda every Sunday at 11:30 AM PT. MCP tools can read this for instant correlation lookups without recomputing from raw sources.

| Field | Type | Description |
|-------|------|-------------|
| `week` | string | ISO week key (e.g. `2026-W11`) |
| `start_date` | string | Window start YYYY-MM-DD |
| `end_date` | string | Window end YYYY-MM-DD |
| `lookback_days` | number | Lookback window (default: 90) |
| `n_pairs` | number | Number of correlation pairs computed |
| `correlations` | map | Per-pair results (see below) |
| `computed_at` | string | ISO timestamp |

**`correlations` sub-fields** (per pair, e.g. `correlations.hrv_vs_recovery`):

| Sub-field | Type | Description |
|-----------|------|-------------|
| `metric_a` | string | First metric name |
| `metric_b` | string | Second metric name |
| `pearson_r` | number | Pearson r (−1 to 1), null if <10 paired days |
| `r_squared` | number | r² (explained variance) |
| `n_days` | number | Paired data points used |
| `interpretation` | string | strong/moderate/weak/negligible/insufficient_data |
| `direction` | string | positive/negative/null |

**Pairs computed:** hrv↔recovery, sleep_duration↔recovery, sleep_score↔recovery, hrv↔sleep_score, rhr↔recovery, tsb↔recovery, strain↔hrv, training_load↔hrv, training_mins↔recovery, protein↔recovery, calories↔hrv, carbs↔hrv, steps↔recovery, steps↔hrv, steps↔sleep, habit_pct↔day_grade, habit_pct↔recovery, tier0_streak↔day_grade, calories↔day_grade, readiness↔day_grade.

**Durability:** Retained indefinitely. One record per ISO week.

---

## ~~Composite Scores Partition~~ (Removed v3.7.28 — ADR-025)

**Status: REMOVED.** This partition (`USER#matthew#SOURCE#composite_scores`) was consolidated into `computed_metrics` in v3.7.28 (CLEANUP-1 per ADR-025). No new data is written here. All fields previously in this partition now live in the `computed_metrics` partition. Existing historical records remain in DynamoDB but are not read by any Lambda or MCP tool.

**Migration:** `daily-metrics-compute` writes all composite fields directly to `computed_metrics`. MCP tools use `computed_metrics` for all lookups.

---

## Platform Memory Partition (IC-1, v2.86.0)

**pk:** `USER#matthew#SOURCE#platform_memory`  
**sk:** `MEMORY#<category>#<date>` (e.g. `MEMORY#failure_patterns#2026-03-09`)

Structured key-value memory store for computed intelligence. Written by insight compute Lambda and digest Lambdas. Read by all AI calls as compounding context.

**Memory categories:**

| SK prefix | Written by | Purpose |
|-----------|-----------|----------|
| `MEMORY#failure_patterns` | Weekly attribution pass | Conditions preceding low day grades |
| `MEMORY#what_worked` | IC-9 (Month 3) | Episodic library of above-baseline outcomes |
| `MEMORY#coaching_calibration` | IC-11 (Month 3) | Matthew-specific response patterns |
| `MEMORY#personal_curves` | IC-10 (Month 4) | Personal response curves (weight loss rate vs. intake, etc.) |
| `MEMORY#temporal_patterns` | IC-26 (Month 2-3) | Cyclical patterns by DOW / week-of-month |
| `MEMORY#milestone_architecture` | IC-6 (Month 1) | Weight/health milestones with biological significance |
| `MEMORY#permanent_learnings` | IC-28 (quarterly) | Stable truths confirmed by repeated observation |
| `MEMORY#intention_tracking` | IC-8 (daily-insight) | Stated intentions vs actual outcomes |

**Core fields (all memory records):**

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Memory category label |
| `date` | string | YYYY-MM-DD date written |
| `content` | object | Category-specific structured content |
| `written_by` | string | Lambda name that wrote this record |
| `written_at` | string | ISO timestamp |
| `version` | string | Schema version |

---

## Insight Ledger Partition (IC-15, v2.87.0)

**pk:** `USER#matthew#SOURCE#insights`  
**sk:** `INSIGHT#<ISO-timestamp>` (e.g. `INSIGHT#2026-03-09T10:15:00`)

Universal write-on-generate: every email/digest Lambda appends a structured insight record after generation. Accumulates the raw material for all downstream IC compounding features.

| Field | Type | Description |
|-------|------|-------------|
| `insight_id` | string | ISO timestamp (SK suffix) |
| `text` | string | Full insight text |
| `date_saved` | string | YYYY-MM-DD |
| `source` | string | `chat` / `email` / `daily_brief` / `weekly_digest` / `chronicle` / etc. |
| `digest_type` | string | Lambda that generated this insight |
| `pillars` | list | Affected pillars e.g. `["sleep", "movement"]` |
| `data_sources` | list | DDB sources referenced |
| `confidence` | string | `high` / `medium` / `low` |
| `actionable` | boolean | Whether the insight has an action item |
| `semantic_tags` | list | e.g. `["hrv", "recovery", "caffeine"]` |
| `generated_text_hash` | string | SHA256 hash for deduplication |
| `status` | string | `open` / `acted` / `resolved` |
| `outcome_notes` | string | What happened when acted on |

---

## Decisions Partition (IC-19, v2.88.0)

**pk:** `USER#matthew#SOURCE#decisions`  
**sk:** `DECISION#<ISO-timestamp>`

Tracks platform-guided decisions and their outcomes. Builds trust-calibration dataset for knowing when to follow the system vs. override it.

| Field | Type | Description |
|-------|------|-------------|
| `decision_id` | string | ISO timestamp (SK suffix) |
| `date` | string | YYYY-MM-DD |
| `decision` | string | What the platform recommended |
| `context` | string | Why it was recommended |
| `followed` | boolean | Whether Matthew followed the advice |
| `outcome_metric` | string | Metric observed as outcome |
| `outcome_delta` | number | Change in outcome metric |
| `notes` | string | Free text notes |
| `logged_at` | string | ISO timestamp |

Access via `log_decision`, `get_decision_journal`, `get_decision_effectiveness` MCP tools.

---

## Field Notes Partition (BL-04, v4.6.0)

**pk:** `USER#matthew#SOURCE#field_notes`
**sk:** `WEEK#<YYYY-WNN>` (e.g. `WEEK#2026-W14`)

Weekly AI-vs-Matthew lab notebook. AI generates three paragraphs every Sunday; Matthew responds via MCP tool. Uses `update_item` for Matthew's fields to never overwrite AI-generated content.

| Field | Type | Description |
|-------|------|-------------|
| `week` | string | ISO week identifier (e.g. `2026-W14`) |
| `week_label` | string | Display label (e.g. `Week 14 · Apr 1–7, 2026`) |
| `week_start` | string | YYYY-MM-DD (Monday) |
| `week_end` | string | YYYY-MM-DD (Sunday) |
| `week_number` | number | Week number within the year |
| `ai_present` | string | Present-signal paragraph (~150 words) |
| `ai_lookback` | string | Lookback paragraph (~120 words) |
| `ai_focus` | string | Forward-focus paragraph (~100 words) |
| `ai_generated_at` | string | ISO timestamp |
| `ai_model` | string | Model used (e.g. `claude-sonnet-4-6`) |
| `ai_tone` | string | `affirming`, `cautionary`, `mixed`, or `urgent` |
| `ai_domains` | list | Domains with notable signals |
| `ai_key_metrics` | map | Snapshot of key metrics for the week |
| `matthew_notes` | string | Matthew's prose response |
| `matthew_notes_at` | string | ISO timestamp of response |
| `matthew_agreement` | string | `agree`, `disagree`, or `mixed` |
| `matthew_disputed` | list | Specific AI claims Matthew disputes |
| `matthew_added` | string | What Matthew noticed the AI missed |
| `character_level` | number | Character level at end of week |
| `day_grade_avg` | number | Average day grade 0–100 |
| `platform_week` | number | Platform week number |

Access via `get_field_notes`, `log_field_note_response` MCP tools.

---

## Ledger Partition (BL-03, v4.6.0)

**pk:** `USER#matthew#SOURCE#ledger`

Achievement-linked charitable giving. Two record types under the same partition:

### Transaction Records

**sk:** `LEDGER#<ISO-timestamp>` (e.g. `LEDGER#2026-03-30T14:22:01.000Z`)

| Field | Type | Description |
|-------|------|-------------|
| `ledger_id` | string | ISO timestamp (SK suffix) |
| `date` | string | YYYY-MM-DD of the outcome |
| `type` | string | `bounty` or `punishment` |
| `amount_usd` | number | Dollar amount donated |
| `cause_id` | string | Cause identifier from `config/ledger.json` |
| `cause_name` | string | Denormalized cause name |
| `source_type` | string | `achievement`, `challenge`, or `experiment` |
| `source_id` | string | ID of the triggering record |
| `source_name` | string | Human-readable name |
| `source_badge_icon` | string | Emoji key |
| `outcome` | string | `earned`, `passed`, `failed`, or `abandoned` |
| `notes` | string | Optional context |
| `logged_at` | string | ISO timestamp |

### Running Totals Record

**sk:** `TOTALS#current` (single record, updated on every transaction)

| Field | Type | Description |
|-------|------|-------------|
| `total_donated_usd` | number | Grand total across all causes |
| `total_bounties_usd` | number | Total from successful outcomes |
| `total_punishments_usd` | number | Total from failed outcomes |
| `bounty_count` | number | Number of bounty transactions |
| `punishment_count` | number | Number of punishment transactions |
| `cause_count` | number | Distinct causes funded |
| `by_cause` | map | Per-cause breakdown: `{cause_id: {amount_usd, count, transactions[]}}` |
| `last_updated` | string | ISO timestamp |

Access via `log_ledger_entry` MCP tool. Config in `config/ledger.json` (S3).

---

## Journal Analysis Partition (v4.7.0)

**pk:** `USER#matthew#SOURCE#journal_analysis`
**sk:** `DATE#YYYY-MM-DD`

Cached theme/sentiment extraction from journal entries. Generated nightly by `journal-analyzer` Lambda using Claude Haiku. Auto-expires after 180 days via TTL.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Journal entry date (YYYY-MM-DD) |
| `dominant_theme` | string | Primary theme: `personal_growth`, `relationships`, `health_body`, `work_ambition`, `anxiety_stress`, `gratitude`, `reflection`, `other` |
| `themes` | list | Up to 5 theme tags |
| `sentiment_score` | string | Float -1.0 to 1.0 (stored as string for DynamoDB) |
| `sentiment_label` | string | `very_positive`, `positive`, `neutral`, `negative`, `very_negative` |
| `energy_level` | string | `high`, `medium`, `low` |
| `word_count` | number | Word count of source journal entry |
| `one_line_summary` | string | Max 12-word factual summary |
| `analyzed_at` | string | ISO timestamp |
| `model` | string | AI model used (e.g. `claude-haiku-4-5-20251001`) |
| `ttl` | number | DynamoDB TTL epoch (180 days from analysis) |

Served via `GET /api/journal_analysis` (site API). Displayed on Mind observatory page as heatmap + charts.

---

## AI Analysis Partition (v4.7.0) — DEPRECATED

**pk:** `USER#matthew#SOURCE#ai_analysis`
**sk:** `EXPERT#mind` | `EXPERT#nutrition` | `EXPERT#training` | `EXPERT#physical`

**Status: DEPRECATED (v6.0.0).** Replaced by Coach Intelligence partitions (`COACH#`, `ENSEMBLE#`, `NARRATIVE#`). The `ai-expert-analyzer` Lambda is superseded by `coach-observatory-renderer`. Legacy `/api/ai_analysis` endpoint still functional as fallback. New data is written to `COACH#{coach_id}` partitions.

Cached weekly AI expert voice analyses. Generated Monday 6am PT by `ai-expert-analyzer` Lambda using Claude Sonnet. Auto-expires after 8 days via TTL.

| Field | Type | Description |
|-------|------|-------------|
| `expert_key` | string | `mind`, `nutrition`, `training`, `physical` |
| `analysis` | string | 2-3 paragraphs of prose analysis (~200 words) |
| `generated_at` | string | ISO timestamp |
| `data_snapshot` | string | JSON snapshot of input data (truncated to 5KB) |
| `ttl` | number | DynamoDB TTL epoch (8 days from generation) |

Served via `GET /api/ai_analysis?expert=<key>` (site API). Displayed on all 4 observatory pages via `renderAIAnalysisCard()`.

---

## Hypotheses Partition (IC-18, v2.89.0)

**pk:** `USER#matthew#SOURCE#hypotheses`  
**sk:** `HYPOTHESIS#<ISO-timestamp>`

Generated weekly by `hypothesis-engine` Lambda (Sunday 11 AM PT). Cross-domain hypotheses that the other 144 tools don't explicitly monitor. Confirmed hypotheses graduate to permanent checks; refuted ones archive.

| Field | Type | Description |
|-------|------|-------------|
| `hypothesis_id` | string | ISO timestamp (SK suffix) |
| `date_generated` | string | YYYY-MM-DD |
| `hypothesis` | string | Hypothesis statement |
| `domains` | list | Pillars involved e.g. `["sleep", "nutrition"]` |
| `numeric_criteria` | object | Measurable confirmation criteria |
| `confirmation_checks` | number | Times confirmed so far (need 3 to promote) |
| `status` | string | `active` / `confirmed` / `refuted` / `expired` |
| `verdict` | string | AI-generated verdict on current evidence |
| `expiry_date` | string | Hard expiry (30 days from generation) |
| `promoted_to` | string | `permanent_check` if promoted (null otherwise) |
| `generated_at` | string | ISO timestamp |

Access via `get_active_hypotheses`, `evaluate_hypothesis` MCP tools.

---

## Chronicle Partition (v2.52.0)

**pk:** `USER#matthew#SOURCE#chronicle`  
**sk:** `DATE#YYYY-MM-DD` (Wednesday of each installment)

Stores Wednesday Chronicle installments by Elena Voss. Also published to S3 blog and `blog.averagejoematt.com`.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD (Wednesday) |
| `title` | string | Installment title |
| `thesis` | string | The central argument/idea of this installment |
| `body` | string | Full article text (HTML) |
| `word_count` | number | Approximate word count |
| `s3_key` | string | S3 path of published blog post |
| `installment_number` | number | Sequential installment number |
| `board_interview` | boolean | Whether this installment includes a BoD interview |
| `generated_at` | string | ISO timestamp |

---

## Cache Partition

**pk:** `CACHE#matthew`  
**sk:** `TOOL#<cache_key>`

Pre-computed results written nightly by the MCP Lambda warmer (EventBridge at 03:00 UTC). TTL: 26 hours. On a cache hit the MCP server returns the stored payload instantly without re-querying DynamoDB.

**Cached tools (12):**

| # | Cache Key Pattern | Tool | Added |
|---|-------------------|------|-------|
| 1 | `aggregated_summary_year_*` | `get_aggregated_summary` (yearly) | v2.14.0 |
| 2 | `aggregated_summary_month_*` | `get_aggregated_summary` (monthly) | v2.14.0 |
| 3 | `personal_records_all` | `get_personal_records` | v2.14.0 |
| 4 | `seasonal_patterns_all` | `get_seasonal_patterns` | v2.14.0 |
| 5 | `health_dashboard_today` | `get_health_dashboard` | v2.14.0 |
| 6 | `habit_dashboard_today` | `get_habit_dashboard` | v2.14.0 |
| 7 | `readiness_score_YYYY-MM-DD` | `get_readiness_score` | v2.34.0 |
| 8 | `health_risk_profile_all` | `get_health_risk_profile` | v2.34.0 |
| 9 | `body_comp_snapshot_latest` | `get_body_composition_snapshot` | v2.34.0 |
| 10 | `energy_balance_YYYY-MM-DD` | `get_energy_balance` | v2.34.0 |
| 11 | `day_type_analysis_YYYY-MM-DD` | `get_day_type_analysis` | v2.34.0 |
| 12 | `movement_score_YYYY-MM-DD` | `get_movement_score` | v2.34.0 |

Tools 7-12 check DDB cache on default queries; custom date ranges bypass cache and compute fresh. Warmer passes `_skip_cache: True` to force fresh computation.

---

## Query Patterns

### Fetch all records for a source in a date range
```
pk = "USER#matthew#SOURCE#whoop"
sk BETWEEN "DATE#2026-01-01" AND "DATE#2026-01-31"
```

### Fetch a single day across all sources
Requires N separate queries (one per source) with the same `DATE#YYYY-MM-DD` sort key — the MCP `get_daily_summary` tool handles this in parallel.

### Fetch the profile
```
pk = "USER#matthew"
sk = "PROFILE#v1"
```

---

## Data Flow

```
External API / flat file export
        ↓
Lambda ingest function
        ↓
S3 (raw backup): matthew-life-platform/
  └── raw/<source>/year=YYYY/month=MM/day=DD/
        ↓
DynamoDB (normalized): life-platform table
  └── pk: USER#matthew#SOURCE#<source>
      sk: DATE#YYYY-MM-DD
      [source-specific normalized fields]
        ↓
MCP Server (Lambda)
        ↓
Claude tools
```

---

## TTL Policy

> **TB7-14 (2026-03-13):** Per-partition retention policies documented. DynamoDB TTL is currently only enforced on `CACHE#matthew`. All other partitions use **application-level expiry** (enforced by query logic or Lambda code) or retain indefinitely. This table is the canonical reference.

DynamoDB TTL is enabled on the `life-platform` table using the `ttl` attribute.

| Partition | DDB TTL? | App-level expiry? | Policy | Enforcement | Notes |
|-----------|----------|-------------------|--------|-------------|-------|
| `CACHE#matthew` | ✅ Yes | — | 26 hours | `ttl` field set by `store_cache()` in `mcp_server.py` | Auto-expired by DDB background deletion. Avoids stale cache surviving past nightly warm cycle. |
| `SOURCE#hypotheses` | ❌ No | ✅ Yes | 30 days | `expiry_date` field checked by `hypothesis-engine` Lambda + MCP tools | 30-day hard expiry enforced at application layer (v1.1.0). Expired hypotheses are never promoted regardless of evidence count. Status set to `expired`. |
| `SOURCE#platform_memory` | ❌ No | ❌ No | ~90 days (policy, not enforced) | Query window limits (fetch_memory_records lookback) | Categories accumulate indefinitely in DDB; lookback windows (30–90 days) mean old records are never read. No cleanup needed until corpus exceeds 1,000 items. |
| `SOURCE#insights` | ❌ No | ❌ No | ~180 days (policy, not enforced) | IC-16 lookback windows (30d for weekly, 90d for monthly) | Grows ~7 records/week (one per digest). At 180-day retention target: ~180 records. Low volume — no urgent cleanup need. Revisit when insight count exceeds 500 (trigger for Insights GSI, roadmap item #17). |
| `SOURCE#decisions` | ❌ No | ❌ No | Indefinite | — | Low volume (manual or inferred). Retained permanently for trust-calibration dataset. |
| `SOURCE#field_notes` | ❌ No | ❌ No | Indefinite | — | ~52 records/year (one per week). Retained permanently as longitudinal AI-human advisor relationship record. |
| `SOURCE#ledger` | ❌ No | ❌ No | Indefinite | — | Low volume (one per achievement/challenge/experiment outcome + one TOTALS record). Retained permanently for charitable giving history. |
| `SOURCE#journal_analysis` | ❌ No | ✅ Yes (180d) | 180 days TTL | — | One record per journal entry date. Claude Haiku theme/sentiment extraction. Auto-expires after 6 months; re-analyzed nightly. |
| `SOURCE#ai_analysis` | ❌ No | ✅ Yes (8d) | 8 days TTL | — | 4 records (one per expert: mind/nutrition/training/physical). Weekly Claude Sonnet analysis. Auto-expires if Lambda fails. |
| `SOURCE#anomalies` | ❌ No | ❌ No | Indefinite | — | One record per day. Grows at ~365 records/year. Lightweight — no cleanup needed. |
| All raw ingestion partitions | ❌ No | ❌ No | Indefinite | — | `whoop`, `strava`, `garmin`, `macrofactor`, etc. Retained permanently for longitudinal trend analysis. This is the core data asset. |
| All other derived partitions | ❌ No | ❌ No | Indefinite | — | `day_grade`, `character_sheet`, `computed_metrics`, `habit_scores`, `travel`, `supplements`, `journal`, `chronicle` — all retained permanently. |

**Why most partitions have no DDB TTL:** The platform's value is in longitudinal data. Deleting raw data or computed history would break trend tools, retrocompute, and the character sheet baseline. Only ephemeral/high-churn partitions (cache, expiring hypotheses) warrant TTL.

**How DDB TTL is set:** The `store_cache` function in `mcp_server.py` sets `ttl = int(time.time()) + 93600` (26 hours in seconds). DynamoDB background deletion occurs within ~48 hours of expiry — expired items may still be returned briefly before deletion, so MCP tools should check `ttl` against `time.time()` if freshness is critical.

**Adding TTL to new partitions:** Set `ttl` to a Unix epoch integer on any item you want auto-expired. No schema migration required — DynamoDB TTL operates on a per-item basis.

---

## Coach Intelligence Partitions (v6.0.0)

Eight domain-specific AI coaches with persistent state, voice, and learning. Replaces the legacy `ai_analysis` partition.

### Coach Output & State

**pk:** `USER#matthew#SOURCE#COACH#{coach_id}`

Where `coach_id` is one of: `sleep_coach`, `nutrition_coach`, `training_coach`, `mind_coach`, `physical_coach`, `glucose_coach`, `labs_coach`, `explorer_coach`.

**SK patterns:**

| SK | Purpose | Written By |
|----|---------|-----------|
| `OUTPUT#` | Latest coach analysis prose | coach-narrative-orchestrator |
| `THREAD#{date}` | Daily analysis thread (one per generation cycle) | coach-narrative-orchestrator |
| `LEARNING#{date}` | What the coach learned from this cycle | coach-state-updater |
| `PREDICTION#{date}` | Forward predictions with confidence | coach-narrative-orchestrator |
| `VOICE#state` | Persistent voice calibration state | coach-state-updater |
| `RELATIONSHIP#state` | Coach-user relationship state (rapport, trust, context) | coach-state-updater |
| `CONFIDENCE#{subdomain}` | Per-subdomain confidence scores | coach-state-updater |
| `COMPRESSED#latest` | Compressed history summary (old threads rolled up) | coach-history-summarizer |

**OUTPUT# fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `analysis` | string | 2-4 paragraphs of coach analysis prose |
| `generated_at` | string | ISO timestamp |
| `cycle_date` | string | YYYY-MM-DD of the generation cycle |
| `lens` | string | Analytical lens used this cycle |
| `voice_version` | string | Voice spec version used |
| `quality_score` | number | Quality gate score (0.0-1.0) |

**THREAD#{date} fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `date` | string | YYYY-MM-DD |
| `analysis` | string | Full analysis text |
| `data_snapshot` | string | JSON of input metrics used |
| `lens` | string | Analytical lens applied |
| `predictions` | list | Forward-looking predictions |
| `prior_thread_ref` | string | SK of previous thread for continuity |
| `generated_at` | string | ISO timestamp |

**VOICE#state fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `voice_spec_version` | string | S3 config version |
| `tone_calibration` | map | Adjusted tone parameters |
| `vocabulary_preferences` | list | Preferred/avoided terms |
| `updated_at` | string | ISO timestamp |

**RELATIONSHIP#state fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `rapport_level` | number | 0.0-1.0 relationship strength |
| `interaction_count` | number | Total generation cycles |
| `trust_signals` | list | Evidence of prediction accuracy |
| `context_summary` | string | Compressed relationship context |
| `updated_at` | string | ISO timestamp |

**CONFIDENCE#{subdomain} fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `subdomain` | string | Specific metric/area (e.g. `hrv_trends`, `macro_adherence`) |
| `confidence` | number | 0.0-1.0 confidence in this subdomain |
| `sample_size` | number | Data points supporting this confidence |
| `last_prediction_accuracy` | number | Most recent prediction accuracy |
| `updated_at` | string | ISO timestamp |

**PREDICTION#{date} fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `date` | string | YYYY-MM-DD prediction was made |
| `predictions` | list | List of prediction objects with metric, expected_value, confidence, horizon_days |
| `evaluated` | boolean | Whether this prediction has been scored |
| `accuracy_score` | number | Prediction accuracy (null until evaluated) |
| `evaluated_at` | string | ISO timestamp of evaluation (null until evaluated) |

**LEARNING#{date} fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `date` | string | YYYY-MM-DD |
| `observations` | list | New patterns or insights detected |
| `model_updates` | map | Parameter adjustments made |
| `confidence_changes` | map | Subdomain confidence deltas |

**COMPRESSED#latest fields:**

| Field | Type | Description |
|-------|------|-------------|
| `coach_id` | string | Coach identifier |
| `compressed_from` | string | Earliest date in compressed range |
| `compressed_to` | string | Latest date in compressed range |
| `thread_count` | number | Number of threads compressed |
| `summary` | string | Compressed narrative summary |
| `key_learnings` | list | Distilled insights from compressed threads |
| `compressed_at` | string | ISO timestamp |

**Example record (OUTPUT#):**
```json
{
  "pk": "USER#matthew#SOURCE#COACH#sleep_coach",
  "sk": "OUTPUT#",
  "coach_id": "sleep_coach",
  "analysis": "Your sleep architecture this week shows a pattern worth noting...",
  "generated_at": "2026-04-06T14:00:00Z",
  "cycle_date": "2026-04-06",
  "lens": "circadian_consistency",
  "voice_version": "1.0",
  "quality_score": 0.92
}
```

### Ensemble Digest

**pk:** `USER#matthew#SOURCE#ENSEMBLE#digest`
**sk:** `CYCLE#{date}` (e.g. `CYCLE#2026-04-06`)

Cross-coach synthesis produced by `coach-ensemble-digest` Lambda. Identifies agreements, disagreements, and emergent themes across all 8 coaches.

| Field | Type | Description |
|-------|------|-------------|
| `cycle_date` | string | YYYY-MM-DD |
| `coach_count` | number | Coaches contributing to this digest |
| `consensus_themes` | list | Themes where multiple coaches agree |
| `disagreements` | list | Active cross-coach disagreements |
| `influence_scores` | map | Per-coach influence weight this cycle |
| `emergent_signals` | list | Patterns visible only in cross-coach view |
| `generated_at` | string | ISO timestamp |

### Ensemble Influence Graph

**pk:** `USER#matthew#SOURCE#ENSEMBLE#influence_graph`
**sk:** `CONFIG#v1`

Static configuration for how coaches influence each other's analyses. Loaded from `config/coaches/influence_graph.json`.

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Config version |
| `edges` | list | Directed influence edges: `{from_coach, to_coach, weight, relationship}` |
| `updated_at` | string | ISO timestamp |

### Ensemble Disagreements

**pk:** `USER#matthew#SOURCE#ENSEMBLE#disagreements`
**sk:** `ACTIVE#{slug}` (e.g. `ACTIVE#sleep-vs-training-volume`)

Tracks active cross-coach disagreements until resolved.

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL-safe disagreement identifier |
| `coaches_involved` | list | Coach IDs on each side |
| `topic` | string | What they disagree about |
| `positions` | map | Per-coach position summary |
| `evidence` | map | Per-coach supporting evidence |
| `status` | string | `active` / `resolved` |
| `opened_date` | string | YYYY-MM-DD first detected |
| `resolved_date` | string | YYYY-MM-DD resolution (null if active) |
| `resolution` | string | How it was resolved (null if active) |

### Narrative Arc

**pk:** `USER#matthew#SOURCE#NARRATIVE#arc`

Tracks the overarching narrative arc across coach generations.

| SK | Purpose |
|----|---------|
| `STATE#current` | Current arc state (active arc, phase, momentum) |
| `HISTORY#{date}` | Daily arc state snapshot |

**STATE#current fields:**

| Field | Type | Description |
|-------|------|-------------|
| `active_arc` | string | Current narrative arc identifier |
| `arc_phase` | string | Phase within arc (e.g. `rising_action`, `plateau`, `breakthrough`) |
| `momentum` | number | -1.0 to 1.0 narrative momentum |
| `arc_start_date` | string | YYYY-MM-DD arc began |
| `key_themes` | list | Dominant themes in current arc |
| `updated_at` | string | ISO timestamp |

**HISTORY#{date} fields:**

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `arc` | string | Arc identifier at this date |
| `phase` | string | Phase at this date |
| `momentum` | number | Momentum value |
| `snapshot_at` | string | ISO timestamp |

### Coach Computation Results

**pk:** `USER#matthew#SOURCE#COACH#computation`
**sk:** `RESULTS#{date}` (e.g. `RESULTS#2026-04-06`)

Pre-computed metrics written by `coach-computation-engine`. EWMA smoothing, seasonal adjustments, and anomaly detection results consumed by all coach Lambdas.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | YYYY-MM-DD |
| `metrics` | map | Per-coach metric bundles (keyed by coach_id) |
| `ewma_state` | map | Current EWMA state for each tracked metric |
| `seasonal_adjustments` | map | Applied seasonal adjustment factors |
| `anomalies_detected` | list | Metrics flagging as anomalous this cycle |
| `computation_version` | string | Engine version |
| `computed_at` | string | ISO timestamp |

**Example record:**
```json
{
  "pk": "USER#matthew#SOURCE#COACH#computation",
  "sk": "RESULTS#2026-04-06",
  "date": "2026-04-06",
  "metrics": {
    "sleep_coach": {"hrv_ewma": 62.3, "sleep_duration_ewma": 7.1, "anomaly_flags": []},
    "nutrition_coach": {"protein_ewma": 168.5, "calorie_ewma": 2150, "anomaly_flags": ["fiber_low"]}
  },
  "computed_at": "2026-04-06T13:55:00Z"
}
```

---

## Intelligence Layer V2 Partitions (v6.4.0)

### Coach Actions (`SOURCE#coach_actions`)

**pk:** `USER#matthew`
**sk:** `SOURCE#coach_actions#{action_id}` (action_id = `{date}-{domain}`)

Tracks coach-issued actions with lifecycle: open → completed/expired/superseded.

| Field | Type | Description |
|-------|------|-------------|
| `action_id` | string | Unique action ID (`YYYY-MM-DD-domain`) |
| `coach_id` | string | Issuing coach (e.g., `glucose`, `physical`) |
| `domain` | string | Domain (sleep, nutrition, training, etc.) |
| `issued_date` | string | YYYY-MM-DD |
| `issued_week` | string | YYYY-WNN |
| `action_text` | string | The action recommendation |
| `status` | string | `open` / `completed` / `expired` / `superseded` |
| `completion_date` | string | When completed (null if open) |
| `completion_method` | string | `auto_detected` / `manual` / `expired` |
| `superseded_by` | string | action_id of replacement (null if active) |

### Intelligence Quality (`SOURCE#intelligence_quality`)

**pk:** `USER#matthew`
**sk:** `SOURCE#intelligence_quality#{date}#{coach_id}`

Post-generation validation results from the intelligence validator.

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Generation date |
| `coach_id` | string | Coach that was validated |
| `domain` | string | Coach's domain |
| `checks_run` | number | Number of validation checks executed |
| `errors` | number | Error-severity flags |
| `warnings` | number | Warning-severity flags |
| `flags` | list | `[{check, severity, detail, source_text}]` |
| `validated_at` | string | ISO timestamp |

---

## Aggregation Behavior

The MCP server automatically switches from raw daily records to monthly aggregates when a requested date window exceeds 90 days (`RAW_DAY_LIMIT = 90`). This keeps response payloads manageable and costs low.

---

**Verified:** 2026-06-06 — L-08 line-by-line cross-check of all per-source tables against lambdas/ingestion/* (see CHANGELOG v8.3.1).


### ADR-058: Phase attribute

Every DDB item under `USER#matthew#SOURCE#*` carries an optional `phase` attribute:

| Value         | Meaning                                                          |
|---------------|------------------------------------------------------------------|
| `experiment`  | Record dated on or after EXPERIMENT_START_DATE (currently 2026-05-18). |
| `pilot`       | Record dated before EXPERIMENT_START_DATE.                       |
| (unset)       | Cross-phase identity record: profile, config, subscribers, genome, field_notes, baseline_snapshot, re_entry. |

Records under wipe-list partitions (chronicle, coach_threads, predictions, hypotheses,
decisions, insights, challenges, experiments, character_sheet, habit_scores, certain
platform_memory categories) additionally carry `tombstone=true`, `tombstoned_at`,
`tombstoned_reason` after the §5 wipe. `hidden=true` on chronicle items specifically.

Read-path filtering is supplied by `lambdas/phase_filter.py::with_phase_filter()`.

---

## ROUTINE# Partition (ADR-066, 2026-05-31)

Hevy routine write-loop IR (system of record). Versioned, audit-replayable, indexed by random platform UUID.

### Per-routine items

| pk | sk | Notes |
|---|---|---|
| `USER#matthew#ROUTINE#<routine_id>` | `VERSION#<padded_version>` (e.g. `VERSION#000001`) | Immutable history item. `attribute_not_exists` ConditionExpression on write so concurrent first-writes can't collide. |
| `USER#matthew#ROUTINE#<routine_id>` | `VERSION#current` | Mutable pointer to the latest version; overwritten on every version bump. |

`routine_id` is a 32-char hex UUID assigned by the platform on `draft`/cron-generation; stable across all versions of that routine.

### ID-map items (platform ↔ Hevy)

| pk | sk | Fields | Notes |
|---|---|---|---|
| `USER#matthew#SOURCE#hevy_id_map` | `PLATFORM#<routine_id>` | `hevy_routine_id` (8-char hex) | Forward lookup. Conditional write — never overwritten. |
| `USER#matthew#SOURCE#hevy_id_map` | `HEVY#<hevy_routine_id>` | `routine_id` | Reverse lookup, mirrors the forward write. |

### Versioned-item fields (selected — full shape in `lambdas/routine_ir.py:RoutineSpec`)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | Pinned to `IR_SCHEMA_VERSION = 1`. Bumps require write-side migration. |
| `version` | int | Monotonic per `routine_id`. |
| `parent_version` | int \| null | Lineage. `null` on first write. |
| `target_date` | ISO date | The day this routine is for. |
| `archetype` | string | `upper` \| `lower` \| `full` \| `aerobic` \| `mobility` \| `rest`. |
| `variant` | string | `ideal` \| `floor` \| `re_entry`. |
| `status` | string | `draft` \| `active` \| `archived` \| `superseded`. |
| `sibling_routine_id` | string \| null | Pairs ideal ↔ floor. |
| `exercises[]` | list | Each has `movement_key`, `sets[]`, `joint_friendly_score`, `skill_tier`, `rationale_tag`. |
| `budget_used` | map | `muscle -> set_count`. |
| `inputs_snapshot` | map | Volume/recovery/ACWR/z2/landmarks_hash/catalog_hash at generation time — replayable audit trail. |
| `rationale` | list[string] | Human-readable log of why each block was chosen. |
| `caps` | map | `total_sets`, `session_minutes`, `weekly_volume_per_muscle`. Hard asserts in the generator. |
| `hevy_routine_id` | string \| null | Populated on push; null while local draft. |
| `hevy_updated_at` | ISO8601 \| null | Last value Hevy returned. Drives GET-before-PUT conflict guard. |
| `hevy_pushed_at` | ISO8601 \| null | When we last sent the body to Hevy. |
| `hevy_folder_id` | int \| null | Hevy routine folder. Immutable post-create per Hevy API (`folder_id` is absent from PUT body). |

### Retention

Indefinite — mirrors the `decisions` partition stance. The IR is the only audit trail of "what was programmed when, and why." Routines may be marked `status=archived` (renamed in Hevy + folder-moved to "Archive"; Hevy has no DELETE), but their IR history stays.
