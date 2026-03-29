# Handover — Session 12: Audit Cleanup + Derived Metrics Phase 1a-1b

**Date:** 2026-02-26  
**Version:** v2.29.0

---

## What happened this session

### Task 1: Verified yesterday's deploys ✅
- **Anomaly detector** — First automated run 8:05 AM today. Checked Feb 25, 0 anomalies, record written. Minor: first cold-start hit ImportModuleError but Lambda auto-retried successfully.
- **Daily Brief (SES scoping)** — Feb 25 brief sent (Grade 73, B-, 7 sources). Feb 26 brief sent (Grade 27, F, Whoop only). **SES domain-scoped permissions confirmed working. Revert plan no longer needed.**
- **DST reminder:** March 8 (10 days). All EventBridge crons shift +1 hour.

### Task 2: Notion Lambda investigation ✅
- Invoked `notion-journal-ingestion` with `full_sync`. Found 16 pages, all 16 skipped with `date=None, template=None`.
- **Not a bug.** No journal entries created yet. The 16 pages are empty Notion DB rows. Lambda correctly skips them.
- Property extraction code matches `create_notion_db.py` schema — will work when first real entry is created.

### Task 3: Documented `macrofactor_workouts` in SCHEMA.md ✅
- Added full schema: 422 items, 2021-04-12 → 2026-02-24
- Day-level summary fields + nested workout → exercise → set structure
- Added `macrofactor_workouts` to valid source identifiers list

### Board of Directors Schema Review
- Full expert panel (Huberman, Attia, Patrick, Galpin, Norton, Ferriss, MD) reviewed data model
- Identified 22 potential derived metrics, selected 16 for implementation
- **Architecture debate:** "Store vs compute-on-read" evaluated per-metric
  - 9 → Store at ingestion (Pattern A) — trending, anomaly detection, brief
  - 4 → Compute on read (Pattern B) — trivial divisions, no storage value
  - 4 → Nightly batch (Pattern C) — cross-source joins, heavy compute
- Created `DERIVED_METRICS_PLAN.md` — 6-session roadmap, ~18 hr total

### Phase 1a: Sleep Onset Consistency — DEPLOYED ✅
- Patched `whoop_lambda.py` with `sleep_onset_minutes` + `sleep_onset_consistency_7d`
- **Gotcha encountered:** Whoop Lambda handler expects `lambda_function.lambda_handler` (filename `lambda_function.py`), not `whoop_lambda.py`. Deploy script now copies before zipping. Initial deploy briefly broke Lambda — fixed immediately.
- **Gotcha encountered:** Only 3/1,992 records had `sleep_start` in DynamoDB (field added in Phase 3, v2.25.0). Rewrote backfill to read from S3 raw files at `raw/whoop/sleep/YYYY/MM/DD.json`.
- Backfilled **1,816 records** with sleep_onset_minutes + consistency. Also backfilled `sleep_start` to DynamoDB using `if_not_exists`.
- **Initial finding:** Recent consistency ~80 min StdDev (poor, >60 threshold). Huberman's #1 sleep optimization target.

### Phase 1b: Body Composition Deltas — DEPLOYED ✅
- Patched `withings_lambda.py` with `lean_mass_delta_14d` + `fat_mass_delta_14d`
- Withings handler is `withings_lambda.lambda_handler` — no filename issue.
- Backfilled all historical Withings records.

---

## Lambda handler reference (prevent future deploy errors)

| Lambda | Handler | Zip filename |
|--------|---------|-------------|
| `whoop-data-ingestion` | `lambda_function.lambda_handler` | `lambda_function.py` |
| `withings-data-ingestion` | `withings_lambda.lambda_handler` | `withings_lambda.py` |
| `notion-journal-ingestion` | (check before deploy) | (check before deploy) |
| `daily-brief` | (check before deploy) | (check before deploy) |

**Rule:** Always check handler with `aws lambda get-function-configuration --function-name <name> --query Handler` before deploying.

---

## Files created
- `DERIVED_METRICS_PLAN.md` — Full implementation roadmap
- `patch_sleep_consistency.py` — Whoop Lambda patch
- `backfill_sleep_consistency.py` — S3-based backfill (1,816 records)
- `deploy_sleep_consistency.sh` — End-to-end deploy (fixed handler + function name)
- `patch_body_comp_deltas.py` — Withings Lambda patch
- `backfill_body_comp_deltas.py` — Historical backfill
- `deploy_body_comp_deltas.sh` — End-to-end deploy (fixed function name)

## Files modified
- `whoop_lambda.py` — Added sleep onset consistency (patched)
- `withings_lambda.py` — Added body comp deltas (patched)
- `SCHEMA.md` — Added macrofactor_workouts, updated timestamp
- `PROJECT_PLAN.md` — Added Derived Metrics epic
- `CHANGELOG.md` — v2.29.0 entry

---

## Next session: Derived Metrics Phase 1c-1e (Session B per plan)

Reference: `DERIVED_METRICS_PLAN.md` → Phase 1c, 1d, 1e

| Step | Metric | Lambda | Effort |
|------|--------|--------|--------|
| 1c | `time_in_optimal_pct` (CGM 70-120) | health_auto_export_lambda.py | 1.25 hr |
| 1d | `protein_distribution_score` | macrofactor_lambda.py | 1.5 hr |
| 1e | `micronutrient_sufficiency` | macrofactor_lambda.py | 1.5 hr |

**Before deploying any Lambda:** Check handler filename with `aws lambda get-function-configuration`.

---

## Remaining from prior sessions (low priority)
- S3 bucket 2.3GB growth — uninvestigated
- MCP server latency trending 1.2s → 2.8s — uninvestigated
- WAF rate limiting (#10)
- MCP API key rotation (#11)
