# Handover — v3.3.7 — 2026-03-09

## Session Summary

This session completed PROD-1 (all 7 CDK stacks deployed), diagnosed and fixed two bugs that
caused 120+ alarm emails, and applied a permanent fix to prevent the packaging bug from
recurring on future CDK deploys.

---

## What Was Done

### PROD-1 — All 7 CDK Stacks Deployed ✅

| Stack | Resources | Notes |
|-------|-----------|-------|
| LifePlatformIngestion | 15 Lambdas + permissions | EventBridge rules = unmanaged drift (AWS rejects PutRule on imported rules) |
| LifePlatformCompute | 7 Lambdas | adaptive-mode, anomaly-detector, character-sheet, daily-insight, daily-metrics, dashboard-refresh, hypothesis-engine |
| LifePlatformEmail | 8 Lambdas | brittany-weekly, daily-brief, monday-compass, monthly-digest, nutrition-review, wednesday-chronicle, weekly-digest, weekly-plate |
| LifePlatformOperational | 7 Lambdas + 8 alarms | freshness-checker Lambda excluded (lives in its own individual CFn stack) |
| LifePlatformMcp | 1 Lambda + 2 alarms | Function URL = unmanaged drift (409 on create) |
| LifePlatformMonitoring | 21 alarms | SLO alarms, AI token budget alarms, DDB item size |
| LifePlatformWeb | 3 CloudFront distributions | Deployed to us-east-1 (bootstrapped this session) |

**Core stack (DDB + S3 + SQS + SNS):** deferred — low risk, low priority.

### Bug 1: CDK Code Packaging (23 Lambdas broken)

**Root cause:** `Code.from_asset("..")` bundles files with `lambdas/` prefix inside the zip.
Lambda resolves handler modules from the zip root, so every import failed with
`No module named 'X'`.

**Impact:** Every Lambda deployed by CDK since the Compute/Email stacks were first deployed
was silently overwriting working code with a broken package. This caused 120+ alarm emails.

**Fix:** `deploy/redeploy_all_cdk_lambdas.sh` — redeployed all 23 via `deploy_lambda.sh`.

**Permanent fix (v3.3.7):** `cdk/stacks/lambda_helpers.py` and `cdk/stacks/ingestion_stack.py`
now use `Code.from_asset("../lambdas")`. The `lambdas/` directory is the asset root, so
handler files land at the zip root where Lambda expects them. Verified clean with `cdk synth`.

### Bug 2: `platform_logger.set_date` Missing (13 ingestion Lambdas broken)

**Root cause:** Old-convention ingestion Lambdas had a stale bundled copy of the logger
that predated the `set_date()` method added in OBS-1.

**Fix:** `deploy/redeploy_ingestion_with_logger.sh` — redeployed all 13 with
`--extra-files lambdas/platform_logger.py`.

**Affected Lambdas:** whoop, eightsleep, withings, strava, todoist, macrofactor, garmin,
habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment.

### CDK Established Patterns (permanent reference)

**EventBridge "Internal Failure" fix:**
Never use `schedule=` on imported Lambdas. CDK calling `PutRule` on imported EB rules
with existing targets fails with "Internal Failure" (AWS/CFN bug). Fix: use
`fn.add_permission()` with hardcoded rule ARNs. EB rules = unmanaged drift.

**Function URL conflict:**
`add_function_url()` on an existing Lambda causes 409. Leave as unmanaged drift.

**Import approach:**
`npx cdk import <Stack> --force` — Lambda::Permissions always skipped (no importable
identifier), created fresh on `cdk deploy`. CloudFront distributions: enter IDs manually.

**CloudFront stacks:** Must be deployed to us-east-1. Bootstrap: `npx cdk bootstrap aws://205930651321/us-east-1`

**Ingestion Lambdas:** Always need `--extra-files lambdas/platform_logger.py` when deploying
via `deploy_lambda.sh` (old-convention Lambdas bundle their own copy).

---

## Unmanaged Drift (Intentional, Documented)

| Resource | Reason |
|----------|--------|
| All EventBridge rules | AWS rejects PutRule UPDATE on imported rules with existing targets |
| life-platform-mcp Function URL | 409 conflict on create; URL stable |
| life-platform-freshness-checker Lambda | In pre-CDK individual CFn stack |

---

## Alarm Status (end of session)

- `slo-mcp-availability` → **cleared** (MCP Lambda restored)
- All compute/email/operational alarms → will **self-clear** on next scheduled invocation
- All ingestion alarms → will **self-clear** on tonight's runs
- `slo-daily-brief-delivery`, `slo-source-freshness` → will self-clear overnight
- `life-platform-dlq-depth-warning` → **pre-existing**, worth investigating next session

---

## Files Changed This Session

| File | Change |
|------|--------|
| `cdk/stacks/lambda_helpers.py` | `Code.from_asset("../lambdas")` + simplified excludes |
| `cdk/stacks/ingestion_stack.py` | `Code.from_asset("../lambdas")` + simplified excludes on HAE webhook |
| `deploy/redeploy_all_cdk_lambdas.sh` | New — redeploys all 23 CDK-managed Lambdas |
| `deploy/redeploy_ingestion_with_logger.sh` | New — redeploys 13 ingestion Lambdas with platform_logger |
| `docs/HANDOVER_LATEST.md` | This file |
| `docs/CHANGELOG.md` | v3.3.6 + v3.3.7 entries |
| `docs/PROJECT_PLAN.md` | PROD-1 marked ✅, hardening table updated, version/completed table updated |
| `docs/ARCHITECTURE.md` | Version header, CDK row in AWS Resources table |

---

## Immediate Next Steps

### Option A — Brittany Weekly Email (fully unblocked)
`brittany-weekly-email` Lambda already exists in AWS. Start here:
```bash
aws lambda get-function-configuration --function-name brittany-weekly-email \
  --region us-west-2 \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize,env:Environment.Variables}"
```

### Option B — DLQ Depth Investigation
`life-platform-dlq-depth-warning` has been in ALARM since March 8. Check what's stuck:
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --region us-west-2
```

### Option C — Freshness Checker Stack Cleanup (low priority)
Delete individual `life-platform-freshness-checker` CFn stack → redeploy Lambda → import
into LifePlatformOperational. Not urgent — Lambda is running fine, just unmanaged.

### Option D — PROD-2 Implementation
Remove hardcoded single-user assumptions. Audit already done. 3 sessions of implementation.

---

## Platform State

**Version:** v3.3.7 | **Git:** committed + pushed (`33c014c`)

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4; SIMP-2 | ✅ |
| PROD-1 | ✅ All 7 stacks deployed. Core (DDB/S3/SQS/SNS) deferred. |
| PROD-2 | ⚠️ Audit done, 3 sessions implementation remaining |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
