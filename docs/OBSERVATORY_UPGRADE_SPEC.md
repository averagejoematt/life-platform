# Observatory Upgrade Spec — Physical & Nutrition Pages

> **Version:** 1.0 (2026-03-29)
> **Author:** Product Board + Personal Board joint review
> **Target:** Claude Code implementation spec
> **Status:** Draft — pending Matthew's review & prioritization

---

## Executive Summary

Both the Training (→ Physical) and Nutrition observatory pages follow the platform's editorial design system beautifully but are **shallow on content depth**. They read as monitoring dashboards rather than observatories. Matthew's physical practice spans 8+ modalities (walking, lifting, cycling, soccer, hiking, rucking, stretching, breathwork) — the page shows a chip count. His nutrition data contains meal-level detail, protein source breakdowns, weekday/weekend patterns, and micronutrient panels — the page shows 30-day macro averages.

**The upgrade vision:** Transform both pages from summary dashboards into deep, multi-section editorial observatories that tell the full story of each domain, with modality-specific deep dives and data-driven narratives.

---

## Part 1: Physical Observatory (currently Training)

### 1.0 Page Rename

**Current:** "Training Observatory"
**Proposed:** "Physical Observatory" (or keep "Training" with expanded subtitle)

**Rationale (Sofia):** "Training" implies gym work. Matthew's physical practice includes walking, breathing, stretching, soccer, cycling, and hiking. "Physical" captures the breadth. The URL can remain `/training/` for SEO continuity.

**Hero title change:** "Training for 80, not for 30" → keep or evolve to something like "Every way the body moves" or "Building a body that lasts"

---

### 1.1 Sections to KEEP (no changes needed)

These sections are well-designed and data-backed:

| Section | Reason to Keep |
|---------|---------------|
| Hero gauges (Zone 2, workouts, strain, strength) | Good at-a-glance summary |
| Narrative intro pull-quote | Sets editorial tone |
| Banister CTL/ATL/TSB model | Unique, well-implemented |
| ACWR injury risk indicator | Clinically useful, great UX |
| 12-week training volume chart | Key trend view |
| Centenarian benchmark tracker | Core to the longevity thesis |
| 1RM progress sparklines | Good strength tracking |
| Attia pillar radar | Good balance visualization |
| N=1 training rules | Editorial signature |
| Cross-links (Nutrition × Training, Sleep × Training) | Navigation pattern |
| Narrative section | Centenarian decathlon framing |
| Methodology | Transparency |

---

### 1.2 Sections to UPGRADE

#### 1.2a Activity Mix → Activity Deep-Dive Cards

**Current:** Simple chips showing activity type + count (e.g., "12 Walk", "8 Ride")
**Proposed:** Expandable editorial cards per modality, each showing modality-specific metrics.

**Card design pattern:**
- Left-accent border in modality color
- Modality name + icon indicator (monospace header)
- Key metrics: frequency (30d), total duration, avg duration, trend arrow
- 1-2 line narrative context (e.g., "Walking is your highest-volume modality — 42% of all sessions")
- Click expands to full modality section (or links to anchor)

**Modalities to include:**
1. Walking / Rucking
2. Strength Training
3. Road Cycling
4. Soccer / Team Sports
5. Hiking
6. Stretching / Mobility
7. Breathwork
8. Running (Coming Soon)

**Data source:** Strava `sport_type` field — already captured per activity. Group by type, compute per-group stats.

**API requirement:** New field in `training_overview` response: `modality_breakdown[]` — array of objects with `{ type, count_30d, total_minutes_30d, avg_duration_min, avg_hr, total_distance_mi, total_elevation_ft, z2_minutes, trend_vs_prior_30d }`.

---

#### 1.2b Walking / Rucking Section (NEW)

**Rationale:** Walking is likely the highest-volume activity. Currently invisible beyond a chip count.

**Section layout:** Editorial 3-column spread (matching Zone 2 section pattern)

| Column 1 | Column 2 | Column 3 |
|-----------|----------|----------|
| Steps per day (30d avg) | Walking sessions (30d) | Rucking sessions (30d) |
| Data: Garmin `steps` | Data: Strava `Walk` type | Data: Strava filtered |
| Trend sparkline | Total walking miles | Z2 yield comparison |

**Additional elements:**
- Pull-quote: Rucking Z2 efficiency finding (currently exists, can enhance)
- Daily steps trend chart (7-day rolling average) from Garmin data
- Weekend vs weekday step comparison
- Walking pace trend (avg_speed from Strava Walk activities)

**Data sources:**
- Garmin: `steps`, `floors_climbed`, `active_calories` (already in DDB as `garmin` partition)
- Strava: Activities filtered by `sport_type` = "Walk" or "Hike"
- Apple Health: Step data (backup source via `apple_health` partition)

**API requirement:** New endpoint `GET /api/walking_overview` OR extend `training_overview` with `walking: { avg_daily_steps, total_walks_30d, total_rucks_30d, avg_pace_min_per_mi, total_miles_30d, z2_minutes_walking, z2_minutes_rucking, daily_steps_trend[] }`.

**Data availability:** ✅ EXISTS — Garmin steps + Strava walk activities already in DDB.

---

#### 1.2c Strength Training Deep-Dive (UPGRADE)

**Current:** Centenarian benchmarks (4 lifts) + 1RM sparklines
**Proposed:** Expand significantly:

**New sub-sections:**

1. **Current Program Indicator** — What program is Matthew running? (PPL, 5/3/1, etc.) Manual config or derived from Hevy workout names.
   - Data: Hevy workout titles, configurable label

2. **Volume Load Trend** — Total volume (sets × reps × weight) per week, 12-week chart.
   - Data: Hevy items have sets/reps/weight per exercise
   - API: Compute `weekly_volume_load` from Hevy data

3. **Muscle Group Balance** — Horizontal bar chart showing volume distribution: Push/Pull/Legs/Core
   - Data: Map Hevy exercise names to muscle groups (exercise → muscle group mapping table)
   - Could be a config file in S3

4. **Exercise Variety** — How many distinct exercises in the last 30 days? Top exercises by frequency.
   - Data: Hevy `exercise_name` field

5. **Strength Session Patterns** — Which days of the week? Time of day? Duration distribution.
   - Data: Hevy timestamps

**Keep:** Centenarian benchmarks, 1RM progress (these are excellent)

**API requirement:** New endpoint `GET /api/strength_deep_dive` with `{ volume_load_trend[], muscle_group_balance{}, exercise_variety[], session_patterns{}, current_program }`.

**Data availability:** ✅ EXISTS — Hevy data in DDB contains exercise names, sets, reps, weights, timestamps.

---

#### 1.2d Road Cycling Section (NEW)

**Section layout:** 2-column editorial

| Left Column | Right Column |
|-------------|-------------|
| Total rides (30d) | Total distance (30d) |
| Avg ride distance | Total elevation gain |
| Avg HR during rides | Longest ride |

**Additional elements:**
- Distance trend chart (weekly rolling)
- Elevation gain trend
- Ride duration distribution
- If power data available (Strava `average_watts`): FTP estimate, power zone distribution

**Data sources:**
- Strava: Activities where `sport_type` = "Ride" or "VirtualRide" — already capturing `distance_miles`, `total_elevation_gain_feet`, `average_heartrate`, `average_watts`, `kilojoules`

**API requirement:** Filter `training_overview` Strava data by sport_type, or new endpoint `GET /api/cycling_overview`.

**Data availability:** ✅ EXISTS — Strava ride data is comprehensive.

---

#### 1.2e Soccer / Sport Section (NEW)

**Section layout:** Compact card + timeline

**Metrics:**
- Matches played (30d / all-time)
- Avg strain per match (from Whoop)
- Avg recovery score day-after
- Playing time per match
- HR peak during matches

**Narrative element:** Pull-quote about the progression from "first full match" to regular play.

**Data sources:**
- Strava: Activities where `sport_type` = "Soccer" — duration, HR, distance
- Whoop: Strain on match days

**API requirement:** Filter existing data by sport_type. Could be part of modality_breakdown.

**Data availability:** ✅ EXISTS — depends on how consistently soccer is logged to Strava.

---

#### 1.2f Hiking Section (NEW)

**Section layout:** Compact card with route gallery potential

**Metrics:**
- Hikes in last 90 days
- Total elevation gain
- Longest hike (distance + elevation)
- Avg HR / Zone 2 time during hikes
- Seasonal pattern (monthly counts)

**Data sources:** Strava `sport_type` = "Hike"

**Data availability:** ✅ EXISTS

---

#### 1.2g Breathwork & Respiratory Section (NEW)

**Rationale (Dr. Kai Nakamura):** Breathwork is a distinct physical practice. The pipeline ingests Apple Health breathwork data but it surfaces *nowhere* on the site.

**Section layout:** 2-column editorial

| Left Column | Right Column |
|-------------|-------------|
| Sessions this month | Avg session duration |
| Total breathwork minutes (30d) | Technique types |
| Trend chart (weekly) | Streak / consistency |

**Correlation narrative:**
- Breathwork sessions vs same-day HRV (if pattern exists)
- Breathwork sessions vs sleep quality

**Data sources:**
- Apple Health / Health Auto Export Lambda: `breathwork_minutes`, `breathwork_sessions` — **already being written to DDB** in the `apple_health` partition
- Garmin: `avg_respiration`, `sleep_respiration`

**API requirement:** New endpoint `GET /api/breathwork_overview` or section in `training_overview`: `breathwork: { sessions_30d, total_minutes_30d, avg_session_min, weekly_trend[], types[] }`.

**Data availability:** ✅ EXISTS — `health_auto_export_lambda.py` already aggregates breathwork_minutes and breathwork_sessions into DDB.

---

#### 1.2h Stretching / Mobility Section (NEW)

**Rationale:** Part of Matthew's physical practice. Even with sparse data, the section's existence signals completeness.

**Section layout:** Compact card

**Metrics:**
- Sessions logged (30d)
- Total minutes
- Types (yoga, foam rolling, dynamic stretching)
- Frequency trend

**Data sources:**
- Apple Health / Health Auto Export: Recovery workout types include flexibility categories
- Strava: Activities typed as "Yoga" or custom
- Hevy: If stretching logged as workout

**API requirement:** Part of modality_breakdown or filtered recovery workout data from health auto export.

**Data availability:** ⚠️ PARTIAL — Health Auto Export captures `flexibility_minutes` and `recovery_workout_types`. Depends on logging consistency.

---

#### 1.2i Weekly Physical Volume Summary (NEW)

**Rationale (Raj):** No single view shows ALL physical activity for a week. This is the "total movement picture."

**Design:** Calendar-style heatmap or horizontal stacked bar per day showing modality breakdown.

| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|-----|-----|-----|-----|-----|-----|-----|
| Walk 45m + Strength 60m | Walk 30m | Ride 90m + Walk 20m | Strength 55m + Walk 40m | Walk 35m | Soccer 90m + Hike 120m | Walk 50m + Breathwork 10m |

**Each day:** Stacked bar with color-coded modalities. Total active minutes shown.

**Data sources:** Strava (all activities) + Garmin (steps/daily summary) + Health Auto Export (breathwork/flexibility)

**API requirement:** New endpoint `GET /api/weekly_physical_summary` returning 7-day array with per-day modality breakdown. Or extend `training_overview`.

**Data availability:** ✅ EXISTS — all data sources are in DDB already.

---

#### 1.2j Running Journey — "Coming Soon" (NEW)

**Section layout:** Minimal teaser card

**Content:**
- "Running — Coming Soon" header
- Brief text: "The data infrastructure is ready. When the first run happens, this section auto-populates."
- Empty gauge ring (0/X target)
- Subscribe CTA for updates

**Data source:** Will use Strava `sport_type` = "Run" when available.

**Data availability:** 🔜 FUTURE — infrastructure ready, awaiting Matthew's first logged run.

---

### 1.3 Hero Gauge Updates

**Current gauges:** Zone 2 avg, Workouts (30d), Avg strain, Strength (30d)

**Proposed additions/changes:**
- Add: **Daily steps avg** (from Garmin — the most universal physical metric)
- Add: **Active modalities** count (e.g., "7 modalities this month")
- Consider: Replace "Avg strain" with something more universally meaningful, or add a 3rd row of 2 gauges

---

## Part 2: Nutrition Observatory

### 2.0 Sections to KEEP

| Section | Reason to Keep |
|---------|---------------|
| Hero gauges (calories, protein, deficit, fiber) | Good summary |
| Narrative intro | Editorial tone |
| Daily average macro breakdown | Core data |
| Protein adherence | Key tracking |
| Top meals (30d) | Good existing section |
| Calorie trend chart | Key trend |
| TDEE adaptation tracking | Unique & valuable |
| Behavioral trigger analysis | Unique & insightful |
| N=1 nutrition rules | Editorial signature |
| Cross-links | Navigation |
| Methodology | Transparency |

---

### 2.1 New Sections

#### 2.1a Protein Source Breakdown (NEW)

**Rationale (Dr. Marcus Webb):** "Where does protein actually come from?" is the #1 nutrition question visitors will have.

**Section layout:** Horizontal stacked bar or donut chart

**Data visualization:**
- Top protein sources by contribution (chicken, eggs, whey, Greek yogurt, beef, etc.)
- Each source: grams contributed per day (avg), percentage of total protein
- Trend: has the source mix changed over time?

**Data source:** MacroFactor `food_log[]` entries — each entry has `food_name` and `protein_g`. Aggregate by food name, sum protein contribution.

**API requirement:** New endpoint `GET /api/protein_sources` or extend `nutrition_overview`:
```json
{
  "protein_sources": [
    { "food": "Chicken Breast", "avg_daily_g": 48.2, "pct_of_total": 24.1, "frequency": 22 },
    { "food": "Whey Protein", "avg_daily_g": 30.0, "pct_of_total": 15.0, "frequency": 28 },
    { "food": "Eggs", "avg_daily_g": 18.6, "pct_of_total": 9.3, "frequency": 25 }
  ]
}
```

**Implementation notes:**
- Normalize food names (MacroFactor may log "Chicken Breast (grilled)" and "Chicken Breast" separately)
- Group by primary protein source, not exact meal name
- Show top 8-10 sources

**Data availability:** ✅ EXISTS — `food_log[]` with per-item `protein_g` is already in MacroFactor DDB records. `handle_frequent_meals()` already parses food_log — this is an extension.

---

#### 2.1b Top Foods / Dietary Backbone (NEW)

**Rationale (Ava):** Beyond protein — what foods appear most often? This is the most relatable content.

**Section layout:** Grid of food cards (similar to activity chips but richer)

**Each card:**
- Food name
- Frequency (times in 30d)
- Avg macros per serving
- Protein density score (protein cal % of total)
- CGM grade if available (from meal_glucose data)

**Data source:** MacroFactor `food_log[]` — frequency count by `food_name`

**API requirement:** `handle_frequent_meals()` already returns top 8 meals with frequency and avg macros. Could extend with more entries and additional fields.

**Data availability:** ✅ EXISTS — endpoint already built.

---

#### 2.1c Weekend vs Weekday Analysis (NEW)

**Rationale (Dr. Marcus Webb):** Eating patterns differ dramatically. This is where adherence breaks down.

**Section layout:** Side-by-side comparison (2-column editorial)

| Weekday (Mon-Fri) | Weekend (Sat-Sun) |
|-------------------|-------------------|
| Avg calories: X | Avg calories: Y |
| Avg protein: X g | Avg protein: Y g |
| Avg carbs: X g | Avg carbs: Y g |
| Protein adherence: X% | Protein adherence: Y% |
| Eating window: X hrs | Eating window: Y hrs |
| Deficit: X cal | Deficit: Y cal |

**Narrative context:** "Weekend Matthew eats 340 more calories than Weekday Matthew. Protein compliance drops 18 points."

**Data source:** MacroFactor daily records — filter by day-of-week. All fields already in DDB.

**API requirement:** New section in `nutrition_overview` response: `weekday_vs_weekend: { weekday: { avg_cal, avg_protein, ... }, weekend: { avg_cal, avg_protein, ... } }`. Simple Python: `datetime.strptime(date, '%Y-%m-%d').weekday() >= 5`.

**Data availability:** ✅ EXISTS — just needs weekday/weekend grouping of existing data.

---

#### 2.1d Restaurant / Takeout Analysis (NEW)

**Rationale (Sofia):** Real, relatable content. Where does Matthew actually order from?

**Section layout:** Compact card grid

**Metrics:**
- Food delivery orders this month (count)
- Food delivery index (0-10 score already computed)
- Top platforms (DoorDash vs UberEats vs GrubHub)
- Avg spend per order
- Orders per week trend
- Correlation: delivery days vs calorie overshoot

**Data source:** `food_delivery` DDB partition — already being ingested by `food_delivery_lambda.py` with merchant, platform, amount, date, and binge detection.

**API requirement:** New endpoint `GET /api/food_delivery_overview`: `{ orders_30d, avg_spend, platform_breakdown[], weekly_trend[], delivery_index, binge_days_30d }`.

**Data availability:** ✅ EXISTS — food_delivery_lambda.py writes per-transaction records with platform, amount, and binge flags.

---

#### 2.1e Macro Deep-Dives: Carbs, Fats, Fiber (NEW)

**Rationale:** Protein gets its own adherence section. Carbs, fats, and fiber deserve the same treatment.

**Section layout:** 3-column editorial spread (matching Zone 2 pattern)

| Carbs | Fats | Fiber |
|-------|------|-------|
| Avg daily: X g | Avg daily: X g | Avg daily: X g |
| Target: X g | Target: X g | Target: 30+ g |
| Adherence: X% | Adherence: X% | Adherence: X% |
| 30d trend sparkline | 30d trend sparkline | 30d trend sparkline |

**Additional depth (Phase 2):**
- Carb quality: complex vs simple (requires food-level carb type data)
- Fat sources: saturated vs unsaturated (requires food-level fat breakdown)
- Fiber sources: which foods contribute most

**Data source:** MacroFactor daily records — `carbs_g`, `fat_g`, `fiber_g` already in DDB.

**API requirement:** Extend `nutrition_overview` with per-macro targets and adherence calculations. Targets can be config values.

**Data availability:** ✅ EXISTS for basic macro tracking. ⚠️ PARTIAL for sub-type breakdowns (complex carbs, sat fat, etc. — depends on MacroFactor data granularity).

---

#### 2.1f Micronutrient Dashboard (UPGRADE)

**Current:** Single section "Micronutrient Gaps" with a few items.
**Proposed:** Full traffic-light panel covering 15-20 key micronutrients.

**Section layout:** Grid of micro cards (5 per row, 3-4 rows)

**Each card:**
- Nutrient name
- Avg daily intake (from food)
- RDA target
- Status: 🟢 ≥100% RDA / 🟡 60-99% / 🔴 <60%
- Source: "Food" / "Supplement" / "Both" (cross-ref with supplements page)

**Key micronutrients to track:**
Vitamin D, Vitamin B12, Vitamin C, Vitamin K, Vitamin A, Vitamin E, Folate, Iron, Zinc, Magnesium, Calcium, Potassium, Sodium, Selenium, Omega-3 (if trackable), Iodine

**Data sources:**
- Apple Health Lambda already captures: `nutrition_sodium_mg`, `nutrition_cholesterol_mg`, `nutrition_water_ml` and other dietary fields from Health Auto Export
- MacroFactor may export some micronutrient data
- Supplement stack data from supplements page (S3 config)

**API requirement:** New endpoint `GET /api/micronutrient_panel` or section in `nutrition_overview`: `micronutrients: [{ name, avg_daily, rda, pct_rda, status, source }]`.

**Data availability:** ⚠️ PARTIAL — Some micronutrients come through Apple Health, but depends on how granularly MacroFactor exports. Phase 2 candidate for deeper tracking.

---

#### 2.1g Meal Timing / Eating Window (NEW)

**Rationale (Mara):** When does eating start and stop? Is there an IF pattern?

**Section layout:** Timeline visualization

**Metrics:**
- Avg eating window (hours between first and last meal)
- Avg first meal time
- Avg last meal time
- Eating window trend (30d)
- Consistency score

**Data source:** MacroFactor `food_log[]` entries have `time` fields. Calculate eating window from first and last entry per day.

**API requirement:** Extend `nutrition_overview`: `eating_window: { avg_hours, avg_first_meal, avg_last_meal, trend[] }`.

**Data availability:** ✅ EXISTS — MacroFactor food_log entries include timestamps. `handle_meal_glucose()` already parses time fields for meal categorization.

---

#### 2.1h Caloric Periodization (NEW)

**Rationale:** Key protocol — higher calories on training days, lower on rest days. Data exists to show it.

**Section layout:** 2-column comparison (like weekend vs weekday)

| Training Days | Rest Days |
|--------------|-----------|
| Avg calories | Avg calories |
| Avg protein | Avg protein |
| Avg deficit | Avg deficit |
| Count (30d) | Count (30d) |

**Data source:** Cross-reference MacroFactor dates with Strava activity dates. If Strava has an activity on a given date = training day.

**API requirement:** Extend `nutrition_overview`: `periodization: { training_day: { avg_cal, avg_pro, count }, rest_day: { avg_cal, avg_pro, count } }`.

**Data availability:** ✅ EXISTS — MacroFactor + Strava dates are both in DDB. Just needs cross-referencing.

---

#### 2.1i Per-Meal Protein Distribution Enhancement (UPGRADE)

**Current:** Shows protein distribution across meals (breakfast/lunch/dinner/snack).
**Proposed:** Do the same for ALL macros, not just protein.

**Add:** Carb distribution, fat distribution, calorie distribution by meal slot.

**Data source:** MacroFactor `food_log[]` with time-based meal categorization (already implemented in `handle_meal_glucose()`).

**Data availability:** ✅ EXISTS

---

#### 2.1j Hydration Deep-Dive (UPGRADE)

**Current:** Single hydration section.
**Proposed:** Expand with:
- Daily water intake trend (30d chart)
- Avg daily intake vs target
- Correlation with training volume (more active days → more water?)
- Correlation with sleep quality
- Weekend vs weekday hydration

**Data source:** Apple Health `nutrition_water_ml` — already captured in `apple_health` DDB partition.

**Data availability:** ✅ EXISTS

---

#### 2.1k "What I Actually Eat" Gallery (NEW)

**Rationale (Ava):** The most human, shareable content on the entire site. A visual grid of actual meals logged.

**Section layout:** Gallery grid (3 columns)

**Each card:**
- Meal name (from food_log)
- Macros summary (cal / pro / carb / fat)
- Meal timing badge (breakfast / lunch / dinner)
- CGM grade badge if available (A/B/C/D)
- Protein density indicator

**Shows:** Last 10-15 distinct meals, most recent first.

**Data source:** MacroFactor food_log + meal_glucose endpoint for CGM grades.

**API requirement:** `handle_frequent_meals()` already returns top meals. Could add a "recent meals" variant showing the last N distinct meals.

**Data availability:** ✅ EXISTS

---

#### 2.1l Nutrition × Training Cross-Analysis (NEW)

**Current:** Brief mention in cross-links.
**Proposed:** Full section with actual data.

**Metrics:**
- Deficit depth vs training quality (strain on deficit days vs surplus days)
- Protein intake vs recovery score next day
- Calorie intake vs training volume correlation (scatter or paired bars)

**Data source:** Cross-reference MacroFactor, Strava, Whoop.

**API requirement:** New endpoint or section: `nutrition_training_cross: { deficit_vs_strain[], protein_vs_recovery[] }`.

**Data availability:** ✅ EXISTS — all three sources in DDB, just need cross-date joins.

---

## Part 3: Implementation Plan

### Phase 1 — Existing Data, Minimal API Work (Target: ~2 sessions)

**Physical page:**
1. Activity deep-dive cards (modality_breakdown from Strava sport_type grouping)
2. Walking section (Garmin steps + Strava walks)
3. Breathwork section (health_auto_export breathwork data)
4. Weekly physical volume summary (cross-source day grouping)
5. Hero gauge additions (steps, modality count)
6. Running "Coming Soon" teaser

**Nutrition page:**
1. Protein source breakdown (food_log protein aggregation)
2. Weekend vs weekday analysis (date filtering)
3. Meal timing / eating window (food_log timestamps)
4. Caloric periodization (MacroFactor × Strava cross-ref)
5. Per-meal macro distribution upgrade (extend existing)
6. "What I Actually Eat" gallery (food_log recent entries)

**API work required:**
- Extend `handle_training_overview()` with modality_breakdown, walking stats, breathwork stats
- New: `GET /api/weekly_physical_summary` (7-day modality breakdown)
- Extend `handle_nutrition_overview()` with weekday/weekend, eating_window, periodization
- New: `GET /api/protein_sources` (food_log protein aggregation)
- Extend `handle_frequent_meals()` with recent meals variant

### Phase 2 — Deeper Data, New Tracking (Target: ~2 sessions later)

**Physical page:**
1. Strength training deep-dive (exercise variety, volume load, muscle group balance)
2. Cycling section (ride-specific aggregation, elevation trends)
3. Soccer section (match tracking)
4. Hiking section
5. Stretching/mobility section (sparse data OK)
6. HR recovery enhancement

**Nutrition page:**
1. Restaurant / takeout analysis (food_delivery data)
2. Macro deep-dives (carbs, fats, fiber individual sections)
3. Micronutrient dashboard (depends on data granularity)
4. Hydration deep-dive (Apple Health water data)
5. Nutrition × Training cross-analysis

**API work required:**
- New: `GET /api/strength_deep_dive`
- New: `GET /api/cycling_overview`
- New: `GET /api/food_delivery_overview`
- New: `GET /api/micronutrient_panel`
- New: nutrition × training cross-analysis endpoint

### Phase 3 — Polish & New Features (Ongoing)

- GPS route gallery with real Strava polyline data
- Interactive modality explorer (click any modality → full-page detail)
- Sub-macro breakdowns (complex vs simple carbs, sat vs unsat fat)
- Supplement × micronutrient gap overlap analysis
- Content engine: auto-generated weekly nutrition/training summaries for email digest

---

## Part 4: Design Guidelines for Claude Code

### Editorial Pattern Reuse

All new sections MUST follow the established observatory editorial design system:

1. **Section headers:** Monospace, uppercase, trailing em-dashes (`n-section-header` / `t-section-header` pattern)
2. **Pull-quotes:** Staggered serif, left/right offset, watermark numbers, evidence badges
3. **Data spreads:** 3-column editorial grid with bar fills and big numbers
4. **Rule cards:** Left-accent border, finding + evidence pattern
5. **Narrative context:** Italic interpretive sentences between data sections
6. **Color system:** Maintain page accent colors (amber for nutrition, crimson for training/physical)

### CSS Pattern

- New sections can use the page's existing `<style>` block (self-contained per observatory page)
- Eventually consolidate to shared `observatory.css` (tracked debt)
- All sections get `reveal` class for scroll animation

### Data Loading Pattern

- All data fetched from site API via `fetch(API + '/api/endpoint')`
- Loading states: monospace uppercase "LOADING..." text
- Error states: graceful fallback message
- Progressive rendering: show each section as its data arrives (don't block entire page)

### Dynamic Content Strategy

- All new sections render from API data, not hardcoded HTML
- Template: set up HTML structure with placeholder IDs → populate via JavaScript
- Follow existing patterns in training.html and nutrition/index.html

---

## Part 5: Data Source Inventory

| Data Source | DDB Partition | Key Fields Available | Used By |
|-------------|--------------|---------------------|---------|
| Strava | `strava` | sport_type, distance_miles, duration_minutes, average_heartrate, max_heartrate, total_elevation_gain_feet, average_watts, kilojoules, average_speed | Physical page |
| Hevy | `hevy` | exercise_name, sets, reps, weight, workout_date | Physical page (strength) |
| Garmin | `garmin` | steps, floors_climbed, zone2_minutes, active_calories, avg_stress, body_battery, vo2_max, training_load, training_readiness, avg_respiration | Physical page |
| Whoop | `whoop` | strain, recovery_score, hrv, resting_heart_rate + per-workout zone data | Physical page |
| Apple Health / HAE | `apple_health` | breathwork_minutes, breathwork_sessions, flexibility_minutes, recovery_workout_types, nutrition_water_ml, respiratory_rate, mindful_minutes | Physical + Nutrition |
| MacroFactor | `macrofactor` | calories, protein_g, carbs_g, fat_g, fiber_g, food_log[] (with food_name, calories_kcal, protein_g, carbs_g, fat_g, time), tdee, expenditure | Nutrition page |
| Food Delivery | `food_delivery` | merchant, platform, amount, date, binge flag | Nutrition page |
| Dexcom | `dexcom` | average_glucose, max_glucose, min_glucose, time_in_range_pct | Nutrition page (CGM grades) |

---

## Appendix: Board Votes

### Product Board Unanimous

- Activity deep-dive cards (not just chips) — **8/8**
- Protein source breakdown — **8/8**
- Weekend vs weekday analysis — **8/8**
- "What I Actually Eat" gallery — **7/8** (James abstained — wants to confirm data richness first)

### Product Board Strong Majority

- Walking section — **7/8**
- Breathwork section — **7/8**
- Weekly physical volume summary — **6/8**
- Meal timing / eating window — **7/8**
- Restaurant / takeout analysis — **6/8**
- Caloric periodization — **6/8**

### Personal Board Endorsements

- Dr. Sarah Chen: Walking + Breathwork sections "fill the biggest gaps"
- Dr. Marcus Webb: Protein sources + Weekend vs weekday "are the data stories I'd want to see in any nutrition observatory"
- Dr. Rhonda Patrick: Micronutrient dashboard "is Phase 2 but strategically important — ties supplements page to nutrition page"
- Coach Maya: Weekly physical volume summary "makes the diversity visible — that's the behavior change trigger"

### Design Notes (Tyrell)

- New sections should not inflate page load time significantly — lazy-load below-the-fold sections
- Consider collapsible modality sections for mobile (expand on tap)
- Physical page could benefit from a modality color system (each activity gets a consistent color across all visualizations)
