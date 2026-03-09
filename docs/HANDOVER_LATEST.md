# Handover — v3.3.1 — 2026-03-09

## What was done this session

### PROD-1 CDK — LifePlatformCompute + LifePlatformEmail fully deployed ✅

Two deploy attempts, three `continue-update-rollback` recoveries, two root causes found and fixed.

#### Root cause 1: Wrong role ARNs (compute_stack.py)
Three Lambdas had placeholder `lambda-weekly-digest-role` — actual roles are:
- `anomaly-detector` → `life-platform-email-role`
- `character-sheet-compute` → `life-platform-compute-role`
- `dashboard-refresh` → `lambda-mcp-server-role`

#### Root cause 2: Shared-role Lambdas can't configure DLQ via CDK
4 Lambdas use pre-SEC-1 shared roles that lack `sqs:SendMessage`. CDK's L1 escape hatch for DLQ config triggers a permission check at deploy time → `UPDATE_FAILED` on all 7 Lambdas in both stacks.

**Fix pattern** (applied to both stacks):
```python
shared_with_dlq = dict(table=..., bucket=..., dlq=local_dlq, alerts_topic=...)
shared_no_dlq   = dict(table=..., bucket=..., dlq=None,      alerts_topic=...)
```

| Lambda | Role | DLQ in CDK |
|--------|------|------------|
| anomaly-detector | life-platform-email-role (shared) | `shared_no_dlq` |
| character-sheet-compute | life-platform-compute-role (shared) | `shared_no_dlq` |
| dashboard-refresh | lambda-mcp-server-role (shared) | `shared_no_dlq` |
| brittany-weekly-email | life-platform-email-role (shared) | `shared_no_dlq` |
| all others | dedicated SEC-1 roles | `shared_with_dlq` |

DLQ state on the 3 compute Lambdas that have a real DLQ in AWS is now unmanaged drift — acceptable given they're operational.

#### What was also fixed earlier this session (v3.3.0)
- All 15 handler names corrected from `lambda_function.lambda_handler` → `{module}.lambda_handler`
- Garth layer support added to ingestion_stack.py + lambda_helpers.py
- `deploy/prepare_cdk_import.sh` written for ingestion import prep

---

## CDK stack status

| Stack | Status | Notes |
|-------|--------|-------|
| LifePlatformCore | Not in CFn | DDB + S3 + SQS + SNS — import deferred |
| LifePlatformIngestion | ⚠️ Synth ✅ | Import pending — run prepare_cdk_import.sh first |
| LifePlatformCompute | ✅ Deployed | Handler fix + role fix + DLQ split live |
| LifePlatformEmail | ✅ Deployed | Handler fix + DLQ split live |

---

## Immediate next steps

### Option A — LifePlatformIngestion import (next PROD-1 step)

```bash
cd ~/Documents/Claude/life-platform
bash deploy/prepare_cdk_import.sh
```

Script will:
1. Look up real garth layer ARN and patch `GARTH_LAYER_ARN` in ingestion_stack.py
2. Verify all 30 Lambda handler strings
3. Print EventBridge rule names needed for import prompts

Then:
```bash
cd cdk && source .venv/bin/activate
npx cdk import LifePlatformIngestion
```

⚠️ Before running import — also check ingestion stack for the same DLQ pattern issue.
Run this to see which ingestion Lambdas have shared roles:
```bash
for fn in whoop-data-ingestion garmin-data-ingestion notion-journal-ingestion \
    withings-data-ingestion habitify-data-ingestion strava-data-ingestion \
    journal-enrichment todoist-data-ingestion eightsleep-data-ingestion \
    activity-enrichment macrofactor-data-ingestion weather-data-ingestion \
    dropbox-poll apple-health-ingestion health-auto-export-webhook; do
  role=$(aws lambda get-function-configuration --function-name $fn --query Role --output text 2>/dev/null | awk -F'/' '{print $NF}')
  echo "$fn → $role"
done
```

Any that show a generic shared role (not `lambda-<fn>-role` pattern) will need `shared_no_dlq`.

### Option B — Brittany weekly email (fully unblocked)

### Option C — Remaining PROD-1 stacks (future sessions)
- operational_stack.py (freshness, dlq-consumer, canary, pip-audit, qa-smoke, key-rotator, data-export, data-reconciliation)
- mcp_stack.py
- monitoring_stack.py
- web_stack.py

---

## Key lesson learned this session

**The shared-role DLQ pattern is a systemic issue** across all CDK stacks, not just compute/email. Any Lambda using a pre-SEC-1 shared role (`life-platform-email-role`, `life-platform-compute-role`, `lambda-mcp-server-role`) will fail CDK deploy if DLQ is configured via the escape hatch. Pattern to apply: verify role per Lambda, use `shared_no_dlq` for shared-role Lambdas. Document this in ARCHITECTURE.md when doing docs pass.

---

## Platform state

**Version:** v3.3.1

| Epic | Status |
|------|--------|
| SEC-1,2,3,5 | ✅ |
| IAM-1,2 | ✅ |
| REL-1,2,3,4 | ✅ |
| OBS-1,2,3 | ✅ |
| COST-1,2,3 | ✅ |
| MAINT-1,2,3,4 | ✅ |
| DATA-1,2,3 | ✅ |
| AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ Compute ✅ Email ✅; Ingestion import pending; 4 stacks remaining |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
