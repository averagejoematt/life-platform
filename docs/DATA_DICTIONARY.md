# Life Platform — Data Dictionary

**Version:** v3.7.22 | **Last updated:** 2026-03-14

> Maps every tracked metric to its authoritative source, update frequency, and overlap with other sources.
> For field-level DynamoDB schema, see SCHEMA.md.

---

## Source-of-Truth (SOT) Domains

Each health domain has exactly one authoritative source. When multiple devices measure the same thing, only the SOT source is used for scoring, grading, and coaching. The SOT mapping is stored in the user profile and can be changed without code deploys.

| Domain | SOT Source | Why This Source |
|--------|-----------|-----------------|
| **Cardio** (running, cycling, hiking) | Strava | GPS accuracy, activity classification, community |
| **Strength** | Hevy / MacroFactor Workouts | Set-level granularity (weight × reps × RIR) |
| **Physiology** (HRV, RHR, recovery) | Whoop | Clinical-grade optical sensor, worn 24/7, recovery algorithm |
| **Nutrition** (calories, macros, micros) | MacroFactor | User-logged meals with per-food granularity |
| **Sleep Duration & Staging** (duration, deep/REM/light, efficiency, score) | Whoop | Wrist sensor captures ALL sleep regardless of location (bed, couch, travel). Eight Sleep only sees bed time. |
| **Sleep Environment** (bed temperature, toss & turns, bed presence) | Eight Sleep | Pod sensor (pressure + temperature), unique to bed environment |
| **Body** (weight, body fat, lean mass) | Withings | Smart scale, daily weigh-in routine |
| **Steps** | Apple Health | iPhone always-on, most accurate daily step count |
| **Tasks** (productivity) | Todoist | Primary task manager |
| **Habits** (P40 completion) | Habitify | Active tracking app (replaced Chronicling Nov 2025) |
| **Stress** (physiological) | Garmin | Epix Gen 2 all-day HRV-derived stress score |
| **Body Battery** (energy reserve) | Garmin | Proprietary Garmin metric (no equivalent elsewhere) |
| **Gait** (walking speed, asymmetry) | Apple Health | Apple Watch accelerometer via Health Auto Export webhook |
| **Energy Expenditure** (TDEE) | Apple Health | Apple Watch active + basal calories (real measurement, not formula) |
| **CGM** (blood glucose) | Apple Health | Dexcom Stelo → HealthKit → webhook |
| **Caffeine** | Apple Health | Logged via caffeine tracking app → HealthKit → webhook |
| **Water** | Apple Health | Logged via water tracking app → HealthKit → webhook |
| **Journal** (subjective layer) | Notion | Structured journal templates with AI enrichment |
| **Supplements** | Supplements (MCP) | Manual logging via `log_supplement` MCP tool |
| **Weather** | Weather (Open-Meteo) | Automated Lambda sync + on-demand MCP fetch |
| **State of Mind** (mood valence) | State of Mind (How We Feel) | Via Apple HealthKit → HAE webhook |

---

## Metric Overlap Map

Where multiple sources measure the same thing:

| Metric | SOT | Also Available From | Resolution |
|--------|-----|-------------------|------------|
| **HRV** | Whoop | Garmin (`hrv_last_night`), Eight Sleep (`hrv`), Apple Health (`hrv_sdnn_apple`) | Whoop for coaching; `get_device_agreement` cross-validates Garmin |
| **Resting Heart Rate** | Whoop | Garmin (`resting_heart_rate`), Eight Sleep (`resting_heart_rate`), Apple Health (`resting_heart_rate_apple`) | Same cross-validation pattern |
| **Sleep Duration** | Whoop | Eight Sleep (`sleep_duration_hours`), Garmin (`sleep_duration_seconds`) | Whoop wrist captures all sleep incl. couch/travel (v2.55.0) |
| **Sleep Score** | Whoop | Eight Sleep (`sleep_score`), Garmin (`sleep_score`) | Whoop `sleep_quality_score`; Eight Sleep score retained for environment tool |
| **Sleep Staging** | Whoop | Eight Sleep (`deep_pct`, `rem_pct`) | Whoop hours → pct via `normalize_whoop_sleep()` in helpers.py |
| **Sleep Efficiency** | Whoop | Eight Sleep (`sleep_efficiency_pct`) | Whoop `sleep_efficiency_percentage` normalised to `sleep_efficiency_pct` |
| **Steps** | Apple Health | Garmin (`steps`) | Apple Health preferred (phone always-on); Garmin for reference |
| **Respiratory Rate** | Eight Sleep (during sleep) | Garmin (`avg_respiration`, `sleep_respiration`), Apple Health (`respiratory_rate_apple`) | Eight Sleep during sleep; Garmin for waking |
| **Sleep Bed Environment** | Eight Sleep | (no overlap) | Temperature, toss & turns, bed presence — unique to pod sensor |
| **Active Calories** | Apple Health | Garmin (`active_calories`) | Apple Health webhook for TDEE; Garmin retained for training metrics |
| **SpO2** | Garmin | Apple Health (`spo2_pct_apple`) | Garmin Epix sensor slightly more reliable |
| **Body Composition** | Withings (daily) | DEXA (semi-annual) | Withings for trending; DEXA for absolute accuracy |

### Three-Tier Source Filtering (Webhook)

The Health Auto Export webhook uses a three-tier system to prevent double-counting:

| Tier | Behavior | Metrics |
|------|----------|---------|
> **Note (v2.55.0):** Sleep in Tier 3 now refers to sleep *environment* (Eight Sleep SOT). Sleep *duration/staging/score* SOT moved to Whoop.
| **Tier 1** (Apple-exclusive) | All readings ingested | Steps, active/basal calories, gait, flights, distance, audio exposure, water, caffeine |
| **Tier 2** (Cross-device) | Filtered to Apple Watch only, `_apple` suffix | HR, RHR, HRV, respiratory rate, SpO2 |
| **Tier 3** (Skip) | Blocked at ingestion | Nutrition (MacroFactor SOT), sleep (Eight Sleep SOT), body comp (Withings SOT) |

---

## Metric Reference by Category

### Recovery & Physiology

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Recovery Score | Whoop | `recovery_score` | 0-100 | Daily |
| HRV | Whoop | `hrv` | ms | Daily |
| Resting Heart Rate | Whoop | `resting_heart_rate` | bpm | Daily |
| Strain | Whoop | `strain` | 0-21 | Daily |
| Sleep Performance | Whoop | `sleep_performance` | 0-100 | Daily |
| Body Battery | Garmin | `body_battery_high/low/end` | 0-100 | Daily |
| Stress Score | Garmin | `avg_stress` | 0-100 | Daily |
| Training Readiness | Garmin | `training_readiness` | 0-100 | Daily |
| VO2 Max (estimated) | Garmin | `vo2_max` | mL/kg/min | Daily |
| Fitness Age | Garmin | `fitness_age` | years | Daily |

### Sleep

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Sleep Score | Whoop | `sleep_quality_score` (normalised to `sleep_score`) | 0-100 | Daily |
| Sleep Efficiency | Whoop | `sleep_efficiency_percentage` (normalised to `sleep_efficiency_pct`) | % | Daily |
| Total Sleep | Whoop | `sleep_duration_hours` | hours | Daily |
| Deep Sleep | Whoop | `slow_wave_sleep_hours` (normalised to `deep_pct`) | hours / % | Daily |
| REM Sleep | Whoop | `rem_sleep_hours` (normalised to `rem_pct`) | hours / % | Daily |
| Light Sleep | Whoop | `light_sleep_hours` (normalised to `light_pct`) | hours / % | Daily |
| WASO | Whoop | `time_awake_hours` (normalised to `waso_hours`) | hours | Daily |
| Sleep Onset (time) | Whoop | `sleep_start` | ISO timestamp | Daily |
| Sleep Onset Consistency | Whoop | `sleep_onset_consistency_7d` | minutes StdDev | Daily |
| Bed Temperature | Eight Sleep | `bed_temp_f` / `bed_temp_c` | °F / °C | Daily |
| Toss & Turns | Eight Sleep | `toss_and_turns` | count | Daily |
| Sleep Onset Latency (bed) | Eight Sleep | `time_to_sleep_min` | minutes | Daily |
| Eight Sleep Sleep Score | Eight Sleep | `sleep_score` | 0-100 | Daily |

### Weight & Body Composition

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Weight | Withings | `weight_lbs` | lbs | Daily |
| Body Fat % | Withings | `body_fat_pct` | % | Daily |
| Lean Mass | Withings | `lean_mass_lbs` | lbs | Daily |
| Fat Mass | Withings | `fat_mass_lbs` | lbs | Daily |
| Lean Mass 14d Delta | Withings | `lean_mass_delta_14d` | lbs | Daily |
| Fat Mass 14d Delta | Withings | `fat_mass_delta_14d` | lbs | Daily |
| BMI | Withings | `bmi` | kg/m² | Daily |
| Visceral Fat | DEXA | `body_composition.visceral_fat_g` | grams | Semi-annual |
| FFMI | DEXA (derived) | computed | kg/m² | Semi-annual |

### Nutrition

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Calories | MacroFactor | `total_calories_kcal` | kcal | Daily |
| Protein | MacroFactor | `total_protein_g` | g | Daily |
| Carbs | MacroFactor | `total_carbs_g` | g | Daily |
| Fat | MacroFactor | `total_fat_g` | g | Daily |
| Fiber | MacroFactor | `total_fiber_g` | g | Daily |
| Sodium | MacroFactor | `total_sodium_mg` | mg | Daily |
| Omega-3 | MacroFactor | `total_omega3_g` | g | Daily |
| Potassium | MacroFactor | `total_potassium_mg` | mg | Daily |
| Magnesium | MacroFactor | `total_magnesium_mg` | mg | Daily |
| Vitamin D | MacroFactor | `total_vitamin_d_iu` | IU | Daily |
| Protein Distribution | MacroFactor | `protein_distribution_score` | % meals ≥30g | Daily |
| Micronutrient Sufficiency | MacroFactor | `micronutrient_avg_pct` | % of target | Daily |
| Caffeine | Apple Health | `caffeine_mg` | mg | ~4 hours |
| Water | Apple Health | `water_intake_ml` | mL | ~4 hours |

### Blood Glucose

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Daily Average | Apple Health | `blood_glucose_avg` | mg/dL | ~4 hours |
| Time in Range (70-180) | Apple Health | `blood_glucose_time_in_range_pct` | % | ~4 hours |
| Time in Optimal (70-120) | Apple Health | `blood_glucose_time_in_optimal_pct` | % | ~4 hours |
| Glucose Variability | Apple Health | `blood_glucose_std_dev` | mg/dL | ~4 hours |
| CGM Readings Count | Apple Health | `blood_glucose_readings_count` | count | ~4 hours |
| 5-Minute Readings | S3 | `raw/cgm_readings/YYYY/MM/DD.json` | mg/dL | ~4 hours |

### Movement & Activity

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Steps | Apple Health | `steps` | count | ~4 hours |
| Active Calories | Apple Health | `active_calories` | kcal | ~4 hours |
| Basal Calories | Apple Health | `basal_calories` | kcal | ~4 hours |
| Walking Speed | Apple Health | `walking_speed_mph` | mph | ~4 hours |
| Walking Step Length | Apple Health | `walking_step_length_in` | inches | ~4 hours |
| Walking Asymmetry | Apple Health | `walking_asymmetry_pct` | % | ~4 hours |
| Double Support Time | Apple Health | `walking_double_support_pct` | % | ~4 hours |
| Distance (activity) | Strava | `total_distance_miles` | miles | Daily |
| Elevation Gain | Strava | `total_elevation_gain_feet` | feet | Daily |
| Moving Time | Strava | `total_moving_time_seconds` | seconds | Daily |
| Zone 2 Minutes | Garmin | `zone2_minutes` | minutes | Daily |
| Training Load | Garmin | `training_load` | score | Daily |

### Habits & Productivity

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Habit Completion | Habitify | `completion_pct` | 0.0-1.0 | Daily |
| Mood | Habitify | `mood` | 1-5 | Daily |
| Tasks Completed | Todoist | `tasks_completed` | count | Daily |

### Journal (Subjective)

| Metric | SOT Source | Field | Unit | Update Freq |
|--------|-----------|-------|------|-------------|
| Sleep Quality (subjective) | Notion | `subjective_sleep_quality` | 1-5 | Daily (morning) |
| Morning Energy | Notion | `morning_energy` | 1-5 | Daily (morning) |
| Morning Mood | Notion | `morning_mood` | 1-5 | Daily (morning) |
| Day Rating | Notion | `day_rating` | 1-5 | Daily (evening) |
| Stress Level | Notion | `stress_level` | 1-5 | Daily (evening) |
| Workout RPE | Notion | `workout_rpe` | 1-10 | Daily (evening) |
| AI-Enriched Mood | Notion | `enriched_mood` | 1-5 | Daily (6:30 AM) |
| AI-Enriched Stress | Notion | `enriched_stress` | 1-5 | Daily (6:30 AM) |

---

## Known Data Gaps

| Gap | Period | Impact |
|-----|--------|--------|
| Habit tracking | 2025-11-10 → 2026-02-22 | Chronicling stopped, Habitify not yet started. No fix possible. |
| Garmin | 2026-01-19 → 2026-02-23 | App sync issue. Backfilled from Feb 23 forward. |
| MacroFactor | Before 2026-02-22 | No real nutrition data. Mock data for testing only. |
| CGM | 2025-01-25 → 2026-02-24 | Dexcom Stelo sensor gap. CGM data: Sep 2024 – Jan 2025 + Feb 2026 onward. |
| Journal | Before 2026-02-24 | Notion journal system created Feb 24. No subjective data prior. |
| Labs | Gaps between draws | 7 blood draws across 6 years; no continuous monitoring |
| State of Mind | Before 2026-02-27 | How We Feel integration added v2.41.0. Needs 30+ days for meaningful trends. |
| Supplements | Before 2026-02-26 | Manual MCP logging started v2.36.0. Adherence depends on consistent logging. |
