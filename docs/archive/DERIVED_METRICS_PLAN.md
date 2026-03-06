# Derived Metrics Implementation Plan

> Board of Directors schema review → implementation roadmap
> Created: 2026-02-26 | Target version: v2.29.0+
> Reference: Board review identified 22 potential derived metrics; 16 selected for implementation.

---

## Architecture Decision

**Three patterns, chosen per-metric based on trending/storage/compute cost analysis:**

- **Pattern A** — Store at ingestion time (enrich source Lambda)
- **Pattern B** — Compute on read (MCP tool only, no storage)
- **Pattern C** — Nightly batch enrichment Lambda (cross-source or heavy compute)

---

## Pattern A: Enrich at Source Ingestion (6 metrics)

### A1. `sleep_onset_consistency_7d` → Whoop Lambda
- **What:** 7-day rolling StdDev of sleep onset time (minutes from midnight)
- **New fields on whoop record:** `sleep_onset_minutes` (int), `sleep_onset_consistency_7d` (float, StdDev in minutes)
- **Thresholds:** <30 min = excellent, 30-60 = fair, >60 = poor
- **Lambda:** `whoop_lambda.py` | **Backfill:** `backfill_sleep_consistency.py`

### A2. `lean_mass_delta_14d` + `fat_mass_delta_14d` → Withings Lambda
- **What:** 14-day rolling change in lean mass and fat mass (lbs)
- **New fields on withings record:** `lean_mass_delta_14d` (float), `fat_mass_delta_14d` (float)
- **Lambda:** `withings_lambda.py` | **Backfill:** `backfill_body_comp_deltas.py`

### A3. `time_in_optimal_pct` → Apple Health Webhook Lambda
- **What:** % of CGM readings 70-120 mg/dL (Attia optimal, stricter than standard 70-180)
- **New field on apple_health record:** `blood_glucose_time_in_optimal_pct` (float)
- **Lambda:** `health_auto_export_lambda.py` | **Backfill:** `backfill_cgm_optimal.py`

### A4. `protein_distribution_score` → MacroFactor Lambda
- **What:** % of meals hitting ≥30g protein (leucine/MPS threshold)
- **New fields on macrofactor record:** `protein_distribution_score` (float), `meals_above_30g_protein` (int), `total_meals` (int)
- **Lambda:** `macrofactor_lambda.py` | **Backfill:** `backfill_protein_distribution.py`

### A5. `micronutrient_sufficiency` → MacroFactor Lambda
- **What:** Per-nutrient % of optimal daily target
- **Targets:** fiber 38g, potassium 3400mg, magnesium 420mg, vitamin D 4000 IU, omega-3 3g
- **New fields on macrofactor record:** `micronutrient_sufficiency` (object), `micronutrient_avg_pct` (float)
- **Lambda:** `macrofactor_lambda.py` | **Backfill:** `backfill_micronutrient_sufficiency.py`

### A6. `ascvd_risk_10yr` → Labs seed script
- **What:** 10-year ASCVD risk score (Pooled Cohort Equations)
- **New fields on labs record:** `ascvd_risk_10yr_pct` (float), `ascvd_inputs` (object)
- **Script:** `seed_labs.py` | **Backfill:** Reprocess 2 existing draws

---

## Pattern B: Compute on Read — MCP Tools Only (4 metrics)

### B1. `acwr` — Enhance `get_training_load`
### B2. `fiber_per_1000kcal` — Enhance `get_nutrition_summary`
### B3. `day_type` — Utility function for segmented analysis
### B4. `strength_to_bw_ratio` — Enhance `get_strength_standards`

---

## Pattern C: Nightly Batch Enrichment Lambda (6 metrics)

New Lambda: `derived-metrics-enrichment`
Schedule: EventBridge 08:00 UTC (midnight PT)
Writes to: `USER#matthew#SOURCE#derived_metrics`

### C1. `caffeine_at_bedtime_mg` — Cross: apple_health + whoop + genome CYP1A2
### C2. `energy_delta` — Cross: notion morning + evening journal
### C3. `training_monotony` — Rolling 7d from garmin/whoop
### C4. `habit_grade_correlations` — Statistical compute (weekly refresh)
### C5. `genome_nutrition_alignment` — Cross: genome + macrofactor (weekly)
### C6. `streak_records` — Cross: multiple sources, current + all-time

---

## Deployment Sequence

### Phase 1: Pattern A — Source Lambda Enrichment
| Step | Metric | Lambda | Effort |
|------|--------|--------|--------|
| 1a | sleep_onset_consistency_7d | whoop_lambda.py | 1.5 hr |
| 1b | lean_mass_delta_14d | withings_lambda.py | 1.25 hr |
| 1c | time_in_optimal_pct | health_auto_export_lambda.py | 1.25 hr |
| 1d | protein_distribution_score | macrofactor_lambda.py | 1.5 hr |
| 1e | micronutrient_sufficiency | macrofactor_lambda.py | 1.5 hr |
| 1f | ascvd_risk_10yr | seed_labs.py | 1.25 hr |

### Phase 2: Pattern B — MCP Tool Enhancements (single deploy)
| Step | Metric | Tool | Effort |
|------|--------|------|--------|
| 2a | acwr | get_training_load | 30 min |
| 2b | fiber_per_1000kcal | get_nutrition_summary | 15 min |
| 2c | day_type | utility function | 15 min |
| 2d | strength_to_bw_ratio | get_strength_standards | 30 min |

### Phase 3: Pattern C — Nightly Enrichment Lambda
| Step | Metric | Depends On | Effort |
|------|--------|------------|--------|
| 3a | Lambda scaffold | — | 1 hr |
| 3b | caffeine_at_bedtime_mg | Phase 1a | 1.5 hr |
| 3c | energy_delta | Notion entries | 30 min |
| 3d | training_monotony | — | 45 min |
| 3e | streak_records | — | 1.5 hr |
| 3f | habit_grade_correlations | — | 1.5 hr |
| 3g | genome_nutrition_alignment | — | 2 hr |

### Phase 4: Backfills (run after Lambda deploys)
### Phase 5: Brief + Digest Integration

---

## Derived Metrics Partition Schema

```
PK: USER#matthew#SOURCE#derived_metrics
SK: DATE#YYYY-MM-DD                      — daily cross-source metrics
SK: CORRELATIONS#habits_to_grade         — weekly habit↔grade correlations
SK: CORRELATIONS#genome_nutrition        — weekly genome↔nutrition alignment
SK: STREAKS#current                      — current active streaks
SK: STREAKS#alltime                      — all-time streak records
```

---

## Session Plan

| Session | Work | Est. Time |
|---------|------|-----------|
| **A** | Phase 1a (sleep consistency) + 1b (lean mass/fat deltas) + backfills | 3 hr |
| **B** | Phase 1c (CGM optimal) + 1d-1e (protein + micronutrients) + backfills | 3.5 hr |
| **C** | Phase 1f (ASCVD) + Phase 2 (all MCP enhancements) | 2.5 hr |
| **D** | Phase 3a-3d (nightly Lambda scaffold + caffeine + monotony + energy) | 3 hr |
| **E** | Phase 3e-3g (streaks + correlations + genome alignment) + backfill | 3.5 hr |
| **F** | Phase 5 (brief/digest/anomaly integration) + docs | 2.5 hr |

**Total: ~18 hr across 6 sessions**
