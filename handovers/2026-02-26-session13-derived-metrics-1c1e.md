# Handover — Session 13: Derived Metrics Phase 1c-1e

**Date:** 2026-02-26  
**Version:** v2.30.0

---

## What happened this session

### Phase 1c: CGM Time-in-Optimal — DEPLOYED ✅
- Patched `health_auto_export_lambda.py` with `blood_glucose_time_in_optimal_pct` (70–120 mg/dL)
- Attia optimal range — stricter than standard 70–180 `time_in_range_pct`
- One counter + one field added alongside existing range calculations
- Backfilled ~139 days of CGM data from S3 raw readings
- Handler: `health_auto_export_lambda.lambda_handler` — no filename issue

### Phase 1d: Protein Distribution Score — DEPLOYED ✅
- Patched `macrofactor_lambda.py` with `compute_protein_distribution()` helper
- Groups food_log entries into meals by 30-min time proximity
- **Key design decision:** Eating occasions <400 kcal excluded as snacks — prevents a banana counting against MPS score
- Constants: `MEAL_CALORIE_THRESHOLD = 400`, `PROTEIN_MPS_THRESHOLD = 30`
- New fields: `protein_distribution_score`, `meals_above_30g_protein`, `total_meals`, `total_snacks`
- Backfilled all historical MacroFactor records
- Handler: `macrofactor_lambda.lambda_handler` — no filename issue

### Phase 1e: Micronutrient Sufficiency — DEPLOYED ✅
- Patched `macrofactor_lambda.py` (on top of 1d) with `compute_micronutrient_sufficiency()`
- Board of Directors consensus targets: Fiber 38g, Potassium 3400mg, Magnesium 420mg, Vitamin D 100mcg (4000 IU), Omega-3 3g
- New fields: `micronutrient_sufficiency` (nested map), `micronutrient_avg_pct`
- Each nutrient capped at 100% — exceeding target still scores max
- Targets stored as `MICRONUTRIENT_TARGETS` dict constant for easy tuning
- Backfilled all historical MacroFactor records

---

## Lambda handler reference (updated)

| Lambda | Handler | Zip filename |
|--------|---------|-------------|
| `whoop-data-ingestion` | `lambda_function.lambda_handler` | `lambda_function.py` |
| `withings-data-ingestion` | `withings_lambda.lambda_handler` | `withings_lambda.py` |
| `health-auto-export-webhook` | `health_auto_export_lambda.lambda_handler` | `health_auto_export_lambda.py` |
| `macrofactor-data-ingestion` | `macrofactor_lambda.lambda_handler` | `macrofactor_lambda.py` |

**Rule:** Always check handler with `aws lambda get-function-configuration --function-name <n> --query Handler` before deploying.

---

## Derived Metrics Progress

| Phase | Metric | Status |
|-------|--------|--------|
| 1a | `sleep_onset_consistency_7d` | ✅ Deployed (Session 12) |
| 1b | `lean_mass_delta_14d` + `fat_mass_delta_14d` | ✅ Deployed (Session 12) |
| 1c | `blood_glucose_time_in_optimal_pct` | ✅ Deployed (Session 13) |
| 1d | `protein_distribution_score` | ✅ Deployed (Session 13) |
| 1e | `micronutrient_sufficiency` | ✅ Deployed (Session 13) |
| 1f | `ascvd_risk_10yr` | Pending (Session C) |

**Pattern A complete: 5/6 metrics deployed.** Phase 1f (ASCVD) is the last Pattern A metric, then Phase 2 (MCP tool enhancements).

---

## Files created
- `patch_cgm_optimal.py` — Apple Health Lambda patch
- `backfill_cgm_optimal.py` — S3-based CGM backfill
- `deploy_cgm_optimal.sh` — End-to-end deploy
- `patch_protein_distribution.py` — MacroFactor Lambda patch (meal grouping + snack filter)
- `backfill_protein_distribution.py` — DynamoDB query-based backfill
- `deploy_protein_distribution.sh` — End-to-end deploy
- `patch_micronutrient_sufficiency.py` — MacroFactor Lambda patch (5 nutrients)
- `backfill_micronutrient_sufficiency.py` — DynamoDB query-based backfill
- `deploy_micronutrient_sufficiency.sh` — End-to-end deploy

## Files modified
- `health_auto_export_lambda.py` — Added CGM optimal % (patched)
- `macrofactor_lambda.py` — Added protein distribution + micronutrient sufficiency (patched twice)
- `SCHEMA.md` — Added all new derived fields, bumped version
- `PROJECT_PLAN.md` — Updated progress, bumped version
- `CHANGELOG.md` — v2.30.0 entry

---

## Next session: Derived Metrics Phase 1f + Phase 2 (Session C per plan)

Reference: `DERIVED_METRICS_PLAN.md` → Phase 1f, Phase 2

| Step | Metric | Target | Effort |
|------|--------|--------|--------|
| 1f | `ascvd_risk_10yr` | seed_labs.py | 1.25 hr |
| 2a | `acwr` | MCP get_training_load | 30 min |
| 2b | `fiber_per_1000kcal` | MCP get_nutrition_summary | 15 min |
| 2c | `day_type` | MCP utility function | 15 min |
| 2d | `strength_to_bw_ratio` | MCP get_strength_standards | 30 min |

**Before deploying any Lambda:** Check handler filename with `aws lambda get-function-configuration`.

**DST reminder:** March 8 (10 days). All EventBridge crons shift +1 hour.

---

## Remaining from prior sessions (low priority)
- S3 bucket 2.3GB growth — uninvestigated
- MCP server latency trending 1.2s → 2.8s — uninvestigated
- WAF rate limiting (#10)
- MCP API key rotation (#11)
