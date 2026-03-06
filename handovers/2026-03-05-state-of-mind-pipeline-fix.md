# Handover — 2026-03-05 — State of Mind Pipeline Fix

## What We Did

Fixed two stacked bugs preventing State of Mind data from flowing through the Health Auto Export webhook pipeline.

### Bug 1: Deploy Filename Mismatch (systemic, primary blocker)

**Root cause:** All deploy scripts for the `health-auto-export-webhook` Lambda were packaging the source file as `lambda_function.py` inside the zip:
```bash
cp health_auto_export_lambda.py lambda_function.py
zip -q health_auto_export_lambda.zip lambda_function.py
```

But the Lambda's handler is configured as `health_auto_export_lambda.lambda_handler`, which expects `health_auto_export_lambda.py`. The zip contained the wrong filename, so Lambda kept loading a stale cached version of the original `health_auto_export_lambda.py` that was deployed when the Lambda was first created.

**Why it was hard to find:** The deploy command returned success, CloudWatch showed cold starts (fresh code load), and the source file on disk had the correct code. The zip even contained the correct code — just with the wrong filename. Multiple debug logging rounds showed zero output because the Lambda was never executing the updated code.

**Fix:** Zip with the original filename:
```bash
zip -q health_auto_export_lambda.zip health_auto_export_lambda.py
```

**Systemic fix:** Created `deploy/deploy_lambda.sh` — a universal deploy helper that queries AWS for the Lambda's handler config before packaging. It extracts the expected module name from the handler string and zips with the correct filename automatically. All future deploys should use this helper.

### Bug 2: HAE Date Field Name (code fix)

**Root cause:** Health Auto Export sends Apple's native State of Mind data with timestamps in a `"start"` field:
```json
{
  "start": "2026-03-05T04:23:28Z",
  "end": "2026-03-05T04:23:28Z",
  "valence": 0.4049,
  ...
}
```

But `process_state_of_mind()` only checked `"date"`, `"startDate"`, `"start_date"`, and `"timestamp"`. Every entry was silently dropped because `date_field` resolved to empty string.

**Fix:** Added `raw.get("start")` and `raw.get("end")` to the date extraction chain.

## Files Changed

| File | Change |
|------|--------|
| `lambdas/health_auto_export_lambda.py` | Added `"start"` and `"end"` to SoM date field extraction; removed debug logging |
| `deploy/deploy_lambda.sh` | **NEW** — Universal Lambda deploy helper that reads handler config from AWS |
| `deploy/deploy_som_date_fix.sh` | Created during debugging (used wrong zip convention) |
| `deploy/deploy_som_debug.sh` | Created during debugging (used wrong zip convention) |

## Verification

- State of Mind MCP tool (`get_state_of_mind_trend`) returns data successfully
- March 5 entry: "proud", work-associated, valence 0.405 (pleasant)
- Data in both DynamoDB (`som_avg_valence` etc.) and S3 (`raw/state_of_mind/`)

## State of Mind Status: ✅ LIVE

- Source: Apple Health native State of Mind logger (not How We Feel)
- Pipeline: Apple Health → Health Auto Export (State of Mind data type) → Lambda webhook → DynamoDB + S3
- HAE automation should be set to "Since Last Sync" for ongoing collection

## Key Learnings

1. **Handler-to-filename mapping varies per Lambda** — never assume `lambda_function.py`. Always check the handler config.
2. **`deploy/deploy_lambda.sh` is the canonical deploy method** — it reads AWS handler config, zips correctly, and validates before deploying.
3. **HAE State of Mind payload uses `"start"`/`"end"` for timestamps** — different from other HealthKit data types that use `"date"`.
4. **Cold starts don't guarantee new code** — if the zip contains the wrong filename, Lambda loads from its own cached copy of the correctly-named file.
