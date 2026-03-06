# Board of Directors — Derived Metrics Implementation Plan

> Created: 2026-02-26 | Board Review of SCHEMA.md
> Principle: Compute on-the-fly in MCP tools and daily brief — no new DynamoDB fields, no backfill needed.

---

## Already Implemented (No Action Needed)

| Recommendation | Where | Notes |
|----------------|-------|-------|
| ACWR (Acute:Chronic Workload Ratio) | `tool_get_training_load` L1031 | Full injury risk classification |
| Sleep onset consistency (SD) | `tool_get_sleep_analysis` L2578 | `sleep_onset_consistency_sd_hours` |
| Wake consistency (SD) | `tool_get_sleep_analysis` L2579 | `wake_consistency_sd_hours` |
| Social jetlag (weekday vs weekend) | `tool_get_sleep_analysis` L2547 | Full circadian analysis |
| Lean mass change (total period) | `tool_get_body_composition_trend` L1716 | `lean_mass_change_lbs` + composition alert |
| Meal timing distribution | `tool_get_meal_timing` L2870 | morning/midday/evening/late split |
| Protein % of calories | `tool_get_nutrition_summary` L3152 | `protein_pct_of_calories` |

---

## Phase 1 — Easy Patches to Existing Tools (1-2 hours total)

Small additions to return payloads of existing functions. No new tools needed.

### 1A. Fiber per 1000 kcal
- **Where:** `tool_get_nutrition_summary` (~L3150)
- **Compute:** `fiber_g / (calories_kcal / 1000)` per day + period average
- **Add to:** daily_rows and averages
- **Target:** ≥14g per 1000 kcal (Norton)
- **Effort:** 10 min

### 1B. Protein Distribution Score
- **Where:** `tool_get_nutrition_summary` OR `tool_get_meal_timing` (~L2870)
- **Compute:** Parse `food_log` per day, count meals with ≥30g protein, divide by total meals
- **Add to:** daily_rows as `protein_distribution_score` (0-100%)
- **Target:** ≥75% of meals hit 30g threshold (Norton)
- **Effort:** 20 min (need to read food_log structure)

### 1C. Lean Mass Velocity (14-day rolling)
- **Where:** `tool_get_body_composition_trend` (~L1730)
- **Compute:** For each data point with lean_mass_lbs, find record ~14 days prior, compute delta
- **Add to:** series as `lean_mass_delta_14d`; summary as `current_lean_velocity_lbs_per_week`
- **Coaching:** Alert if lean velocity < -0.5 lbs/week during a cut
- **Effort:** 15 min

### 1D. Training Monotony
- **Where:** `tool_get_training_load` (~L1065)
- **Compute:** Last 7 days mean(daily_load) / stdev(daily_load). Add `training_monotony` + `training_strain` (monotony × weekly sum)
- **Risk:** monotony > 2.0 = overtraining risk
- **Effort:** 10 min

### 1E. Time in Optimal Range (70-120 mg/dL)
- **Where:** CGM daily aggregation in `health_auto_export_lambda.py` OR new section in `tool_get_cgm_dashboard`
- **Compute:** From raw S3 CGM readings, % of readings 70-120 (vs existing 70-180)
- **Note:** May need to read from S3 like `tool_get_glucose_meal_response` does
- **Effort:** 30 min

### 1F. Strength-to-Bodyweight Ratios
- **Where:** `tool_get_strength_standards` (~L2321)
- **Compute:** Pull latest Withings weight, divide each PR by bodyweight
- **Add to:** PR entries as `ratio_to_bodyweight`; add interpretation (novice/intermediate/advanced per ExRx)
- **Effort:** 15 min

---

## Phase 2 — Medium Complexity (2-3 hours total)

Cross-source computations, pharmacokinetic models, correlation matrices.

### 2A. Caffeine at Bedtime Estimate
- **Where:** New section in `tool_get_caffeine_sleep_correlation` (~L3344) OR daily brief
- **Compute:** Sum caffeine from food_log entries with timestamps. Apply half-life decay (5.5h default, adjust to 3.5h for CYP1A2 rs762551 A/A fast metabolizer from genome data). Estimate residual mg at sleep_start time from Whoop.
- **Data needed:** MacroFactor food_log (timestamps + caffeine), Whoop sleep_start, genome CYP1A2
- **Effort:** 45 min

### 2B. Morning-to-Evening Energy Delta
- **Where:** `tool_get_journal_correlations` or `tool_get_mood_trend`
- **Compute:** For days with both morning + evening journal entries, compute `morning_energy - energy_eod`
- **Coaching:** Persistent negative delta → adrenal load or poor glucose management
- **Effort:** 20 min

### 2C. Micronutrient Sufficiency Percentages
- **Where:** `tool_get_micronutrient_report` (~L2775)
- **Compute:** For each tracked micronutrient, compute % of RDA/optimal target
- **Targets:** Vitamin D (50mcg), Magnesium (400mg), Potassium (3500mg), Fiber (30g), Omega-3 (2g), Sodium (<2300mg)
- **Add to:** Return as `sufficiency_heatmap` object
- **Effort:** 20 min

### 2D. Habit-to-Day-Grade Correlation Matrix
- **Where:** New enhancement to `tool_get_keystone_habits` (~L5048)
- **Compute:** Query day_grade partition + habitify partition for overlapping dates. Compute Pearson r for each habit vs total_score.
- **Return:** Top 10 positive correlators, top 5 negative correlators
- **Effort:** 30 min

### 2E. ASCVD Risk Score (10-year)
- **Where:** New section in `tool_get_health_risk_profile` (~L6739)
- **Compute:** Pooled Cohort Equations using total_cholesterol, HDL, systolic_BP (from labs), age, sex, diabetes status, smoking status
- **Note:** Only recompute per new lab draw. Return "insufficient data" if missing inputs.
- **Effort:** 30 min

---

## Phase 3 — Larger Efforts (future sessions)

### 3A. Genome-Nutrition Alignment Score
- Cross-reference genome `actionable_recs` with MacroFactor rolling averages
- Weekly computed, surfaces in weekly digest
- Effort: 2 hours

### 3B. Volume Load by Muscle Group
- Map MacroFactor workout exercise names → muscle groups
- Requires exercise taxonomy (push/pull/legs/core or specific muscles)
- Effort: 2-3 hours

### 3C. Streaks as First-Class Partition
- New DynamoDB partition `USER#matthew#SOURCE#streaks`
- Persist current + historical streaks for key behaviors
- Daily brief reads this instead of recomputing
- Effort: 3-4 hours

### 3D. Supplement Tracking Partition
- Map Habitify supplement habits → supplement name + dose
- Enable correlation with labs biomarker changes
- Effort: 2 hours

---

## Daily Brief Integration Points

Once MCP tools compute these, the daily brief can surface:
- `fiber_per_1000kcal` in Nutrition Report section
- `protein_distribution_score` in Nutrition Report section
- `lean_mass_velocity` in Weight Phase Tracker section
- `training_monotony` in Training Report section
- `caffeine_at_bedtime` in CGM/Sleep section
- `time_in_optimal_pct` in CGM Spotlight section

---

## Implementation Order

1. **Phase 1A-1D** (fiber, protein dist, lean velocity, monotony) — pure math patches, 55 min
2. **Phase 1E** (time in optimal) — S3 read, 30 min
3. **Phase 1F** (strength:BW) — cross-source, 15 min
4. **Phase 2A** (caffeine at bedtime) — pharmacokinetic model, 45 min
5. **Phase 2B-2C** (energy delta, micronutrient %) — journal + nutrition, 40 min
6. **Phase 2D-2E** (habit correlations, ASCVD) — analytics, 60 min
