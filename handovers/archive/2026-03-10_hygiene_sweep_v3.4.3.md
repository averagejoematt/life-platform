# Life Platform Handover — v3.4.3 (2026-03-10)

## Session Summary

Hygiene sweep — all 10 items from Architecture Review #4 actioned. No new features.
No code deployed to AWS. Requires one deploy: `failure_pattern_compute_lambda.py` (TTL addition).

---

## What Was Done

### 1. INCIDENT_LOG — 5 missing v3.4.0/v3.4.1 incidents added ✅
Added all 5 incidents retroactively (marked "Identified during Architecture Review #4"):
- P1: CDK IAM bulk migration — Lambda execution role gap (wednesday-chronicle, nutrition-review)
- P2: CoreStack SQS DLQ ARN changed — DLQ send failures for ~30 min
- P3: EB rule recreation gap — 2 ingestion Lambdas (withings, eightsleep) missed morning window
- P3: Orphan Lambda adoption — failure-pattern-compute EB rule not in CDK Compute stack
- P4: Duplicate CloudWatch alarms for 3 orphan Lambdas after CDK Monitoring adoption

> **⚠️ Review these entries and correct specifics** — these were reconstructed from the v3.4.0
> changelog and deployment context, not from actual CloudWatch logs. Adjust Lambda names, 
> timings, and data-loss details as needed.

### 2. Archive 19 one-time deploy/ scripts ✅
All 19 one-time scripts moved to `deploy/archive/20260310/`.
Active deploy/ directory now contains only 9 files:
- `deploy_lambda.sh` — primary deploy tool
- `build_layer.sh` — Lambda layer builds
- `p3_build_shared_utils_layer.sh` — shared utils layer rebuild
- `p3_attach_shared_utils_layer.sh` — attach layer to Lambdas
- `p3_build_garmin_layer.sh` — Garmin-specific layer
- `generate_review_bundle.sh` — architecture review bundle generator
- `maint3_archive_deploy.sh` — template for future archive operations
- `SMOKE_TEST_TEMPLATE.sh` — test template
- `MANIFEST.md` — deploy directory manifest
- `cleanup_dead_files.sh` — new: run once to delete dead lambdas files (see item 3)

### 3. Dead files — cleanup script written ✅
Cannot delete files via Filesystem tools. Script written: `deploy/cleanup_dead_files.sh`.

**Run this:**
```bash
bash deploy/cleanup_dead_files.sh
```
Deletes:
- `lambdas/weather_lambda.py.archived`
- `lambdas/freshness_checker.py` (active is `freshness_checker_lambda.py`)

### 4. ADRs 021–023 added to DECISIONS.md ✅
- **ADR-021:** EventBridge rule naming convention (CDK) — lowercase-hyphenated, explicit `rule_name=`, CDK authoritative
- **ADR-022:** CoreStack scoping — DLQ + SNS + Layer; DDB/S3 excluded (stateful); use `from_queue_arn()` import for existing resources
- **ADR-023:** Sick day checker as shared Layer utility — not standalone Lambda; synchronous with compute

> **Note:** ADR-023 was written based on `sick_day_checker.py` being a shared module.
> Verify the interface (`detect_sick_day` return type) matches actual implementation.

### 5. needs_kms=True audit — role_policies.py ✅
6 compute functions updated to include `needs_kms=True`:
- `compute_anomaly_detector` (reads CMK-encrypted DDB)
- `compute_daily_insight` (writes platform_memory partition)
- `compute_adaptive_mode` (writes adaptive_mode record)
- `compute_hypothesis_engine` (writes hypothesis records)
- `compute_dashboard_refresh` (reads CMK-encrypted DDB)
- `compute_failure_pattern` (writes failure_pattern records)

**⚠️ These CDK policy changes need a `cdk deploy LifePlatformComputeStack` to take effect.**

### 6. TTL added to failure_pattern_compute records ✅
`lambdas/failure_pattern_compute_lambda.py` — `store_failure_patterns()` now sets `ttl` field
to `now + 90 days` on every record. DynamoDB TTL attribute is `ttl` (configured on table).

**⚠️ Deploy this Lambda:**
```bash
bash deploy/deploy_lambda.sh failure-pattern-compute
```

### 7. PlatformLogger %s fix ✅ (already done)
`platform_logger.py` v1.0.1 already contains the `*args %s` compat fix. No action needed.

### 8. ARCHITECTURE.md header + CDK section updated ✅
- Header: v3.4.2, 147 tools, 31-module, 41 Lambdas, 8 CDK stacks
- CDK resource table: updated to 8 stacks with Core stack listed

### 9. habitify secret reference fixed in role_policies.py ✅
`ingestion_habitify()` now references `life-platform/habitify` (was `life-platform/api-keys`).

**⚠️ Action required before 2026-04-07 (api-keys deletion deadline):**
```bash
# Create the secret (one-time)
aws secretsmanager create-secret \
  --name life-platform/habitify \
  --description "Habitify API key for life-platform" \
  --region us-west-2

# Populate it (get key from current api-keys secret first)
aws secretsmanager put-secret-value \
  --secret-id life-platform/habitify \
  --secret-string '{"habitify_api_key": "<value from api-keys secret>"}'

# Then deploy CDK to push updated IAM policy
cdk deploy LifePlatformIngestionStack
```
Also update ARCHITECTURE.md secrets table when done.

### 10. "Archive deploy/" added to session-end checklist ✅
Memory updated. Step now appears as item (1) in end-of-session procedure.

---

## Deploys Required (from this session)

| Lambda | Why | Command |
|--------|-----|---------|
| `failure-pattern-compute` | TTL field added | `bash deploy/deploy_lambda.sh failure-pattern-compute` |
| CDK LifePlatformComputeStack | needs_kms added to 6 compute functions | `cd cdk && cdk deploy LifePlatformComputeStack` |
| CDK LifePlatformIngestionStack | habitify secret ref changed | After creating `life-platform/habitify` secret |

---

## One-Time Actions Required

1. **Run dead file cleanup:** `bash deploy/cleanup_dead_files.sh`
2. **Create `life-platform/habitify` secret** before 2026-04-07 (see item 9 above)
3. **Review the 5 INCIDENT_LOG entries** and correct specific Lambda names / timing details if wrong

---

## Next Steps

1. **Brittany weekly accountability email** — next major feature
2. **SIMP-1 (MCP tool usage audit)** — ~2026-04-08 after 30 days of usage data
3. **Review #5** — ~2026-04-08

---

## Git Commit

```bash
git add -A && git commit -m "v3.4.3: Hygiene sweep — INCIDENT_LOG +5, ADRs 021-023, needs_kms audit, TTL failure_pattern, 19 scripts archived, ARCHITECTURE.md updated" && git push
```
