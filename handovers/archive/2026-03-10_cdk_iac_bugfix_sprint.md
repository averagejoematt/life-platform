# Handover: CDK IaC Bugfix Sprint
**Date:** 2026-03-10
**Version:** v3.4.3
**Status:** All Lambdas operational — PlatformLogger fixed, all stacks healthy

---

## What Was Done This Session

This session was a multi-bug CDK infrastructure recovery sprint triggered by the PlatformLogger
hotfix deploy revealing a cascade of issues in the CDK stack definitions.

### Bug 1: PlatformLogger `*args` fix (carried from previous session)
- **Root cause:** `PlatformLogger.info()` et al didn't accept positional `*args`, so old-style
  `logger.info("msg: %s", value)` calls raised `takes 2 positional arguments but 3 were given`
- **Fix:** `platform_logger.py` updated to accept `*args, **kwargs` + `%` interpolation
- **Layer version:** SharedUtilsLayer:7 (deployed to all stacks)

### Bug 2: Missing `role_policies.py` methods
- **Root cause:** CDK `app.py` synths all stacks at once; methods were called but never defined
- **First wave:** `compute_daily_insight`, `compute_adaptive_mode`, `compute_hypothesis_engine`,
  `compute_dashboard_refresh`, `compute_failure_pattern` (5 compute methods)
- **Second wave:** All 8 `email_*`, 8 `operational_*`, and `mcp_server` methods (17 more)
- **Fix:** Added all 22 missing methods + `_email_base()` helper to `role_policies.py`
- **Pattern:** Email Lambdas share a new `_email_base()` helper (DDB + S3 config + ai-keys + SES + DLQ)

### Bug 3: Wrong Lambda handlers in `ingestion_stack.py`
- **Root cause:** 7 Lambdas had `handler="lambda_function.lambda_handler"` — a placeholder that
  was never corrected after scaffolding. These had always been deployed via `deploy_lambda.sh`
  which reads handler config from AWS directly, so the CDK value was never enforced until now.
- **Affected:** whoop, withings, habitify, strava, todoist, eightsleep, apple-health
- **Fix:** Corrected all 7 to match actual filenames (e.g. `whoop_lambda.lambda_handler`)

### Bug 4: Missing KMS policy in `_ingestion_base()`
- **Root cause:** The DynamoDB table uses a customer-managed KMS key. CDK-created ingestion roles
  lacked `kms:Decrypt` + `kms:GenerateDataKey`, causing `AccessDeniedException` on all DDB reads
- **Fix:** Added KMS statement unconditionally to `_ingestion_base()` — all ingestion Lambdas
  touch DDB and all need KMS

### Remediation Steps Completed
1. `bash deploy/build_layer.sh` → rebuilt layer with fixed `platform_logger.py`
2. `cdk deploy LifePlatformCore` → published SharedUtilsLayer:7
3. `cdk deploy LifePlatformIngestion` (×3 — once per bug fix round)
4. All other stacks (Compute, Email, Operational, Mcp, Monitoring, Web) confirmed `UPDATE_COMPLETE`
5. Manual invoke of `whoop-data-ingestion` → clean 200, no FunctionError ✅
6. Manual invoke of `daily-metrics-compute` → clean 200, no FunctionError ✅
7. DLQ purged (11 dead messages cleared)

---

## Current State

- **All 7 CDK stacks:** `UPDATE_COMPLETE`
- **Layer:** SharedUtilsLayer:7
- **`role_policies.py`:** 40 public methods covering all 37 Lambdas across all stacks
- **Alarms:** 26 still in ALARM state — will auto-resolve within 24h as scheduled runs succeed
- **DLQ:** Purged clean

---

## Key Files Changed

| File | Change |
|------|--------|
| `lambdas/platform_logger.py` | `*args` support + `%` interpolation in all log methods |
| `cdk/stacks/role_policies.py` | +22 methods: compute (5), email (9 incl. `_email_base`), operational (8), mcp (1); +KMS in `_ingestion_base` |
| `cdk/stacks/ingestion_stack.py` | 7 handler strings corrected |

---

## Lessons Learned

- **CDK deploy ≠ individual Lambda deploy:** `deploy_lambda.sh` reads handler config from AWS
  and doesn't validate the CDK source — so wrong values in CDK can persist indefinitely until
  a full CDK deploy enforces them. All handler strings in CDK stacks need to be treated as
  authoritative and verified.
- **`_ingestion_base` was missing KMS from the start** — this was masked because pre-CDK IAM
  roles had been manually created with KMS access. CDK-created roles inherited none of that.
- **Synth-time AttributeErrors surface all at once:** CDK synths all stacks before deploying any,
  so a missing method in `role_policies.py` blocks the entire deploy even if targeting one stack.

---

## Next Steps

1. **Monitor alarms** — should clear over next 24h as scheduled Lambda runs succeed
2. **Brittany email** — next major feature (prerequisite: reward seeding is done)
3. **COST-A** — CloudWatch alarm audit & pruning (~87 → ~35 alarms, saves ~$2/mo)
4. **COST-B** — Secrets Manager consolidation review (todoist/notion/dropbox → ingestion-keys)
5. **Architecture Review #5** — ~2026-04-08
