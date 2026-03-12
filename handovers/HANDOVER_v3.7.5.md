# Life Platform Handover — v3.7.5
**Date:** 2026-03-12
**Session type:** P0 follow-up — CDK source fix + prevention linter suite

---

## What Was Done

After v3.7.4 patched the live environment, this session fixed the CDK source itself
so future `cdk deploy` runs won't re-introduce the same bugs. Then built a full
linter/smoke suite to permanently catch this class of regression in CI.

---

## CDK Source Fixes (4 changes)

### 1. operational_stack.py — 3 wrong handler names
All three were `handler="lambda_function.lambda_handler"` (generic placeholder).
Fixed to actual module names:
- `life-platform-freshness-checker` → `freshness_checker_lambda.lambda_handler`
- `life-platform-key-rotator` → `key_rotator_lambda.lambda_handler`
- `insight-email-parser` → `insight_email_parser_lambda.lambda_handler`

### 2. role_policies.py — Todoist S3 path
`ingestion_todoist()` was using the default `raw/matthew/todoist/*` prefix.
Added explicit `s3_prefix="raw/todoist/*"` to match actual Lambda write path.

### 3. ingestion_stack.py — HAE webhook noqa annotation
HAE webhook uses `code=from_asset` (not `source_file=`), so handler is legitimately
"orphaned" from the linter's perspective. Added `# noqa: CDK_HANDLER_ORPHAN` annotation.

---

## Prevention Suite (new files)

| File | Purpose |
|------|---------|
| `tests/test_cdk_handler_consistency.py` | H1–H5: handler/source_file match, no `lambda_function`, source file exists |
| `tests/test_cdk_s3_paths.py` | S1–S4: IAM S3 paths follow convention or are documented in manifest |
| `ci/lambda_s3_paths.json` | Living manifest of S3 path exceptions (todoist, dropbox) |
| `deploy/post_cdk_reconcile_smoke.sh` | Run after every `cdk deploy` — checks handlers live + invokes Lambdas |

Both test files run in CI `test` job (offline, no AWS credentials needed). 9/9 passing.

### Rule going forward
**After every `cdk deploy`:** `bash deploy/post_cdk_reconcile_smoke.sh`

---

## Pending Actions (carry forward)

1. **⚠️ TB7-4 — api-keys grep sweep (DEADLINE 2026-03-17)**
   ```bash
   grep -rn "api-keys" lambdas/ mcp/ deploy/ --include="*.py" --include="*.sh" --include="*.json"
   ```
   Confirm clean, then permanently delete `life-platform/api-keys`.

2. **TB7-1** — Verify GitHub Settings → Environments → `production` has required reviewers.

3. **TB7-2 / Brittany email** — Set `BRITTANY_EMAIL` env var to her real address.

4. **TB7-15** — Run `bash deploy/create_ai_cost_alarm.sh` (enable billing alerts in AWS Console first).

5. **TB7-17** — Run `bash deploy/verify_dlq_alarm_periods.sh`.

6. **Google Calendar integration** — Next major feature (6–8h).

---

## Key Architecture Notes
- AWS account: `205930651321`, region: `us-west-2`
- Platform: v3.7.5, 42 Lambdas, 19 data sources, 42 alarms, 8 CDK stacks
- All 6 alarms cleared (0 in ALARM state)
- CI now has 6 offline test suites: shared_modules, role_policies, wiring_coverage, ddb_patterns, cdk_handler_consistency, cdk_s3_paths
- New rule: run `post_cdk_reconcile_smoke.sh` after every `cdk deploy`
