# Handover — v3.3.3 — 2026-03-09

## What was done this session

### Option A — LifePlatformIngestion deploy script ✅

Wrote `deploy/deploy_ingestion_stack.sh`. Key finding: the 7 old-convention Lambdas
(`lambda_function.lambda_handler`) were already corrected in `ingestion_stack.py` during
the import session. **No handler drift will occur on deploy.** The deploy will:
- Create 7 missing alarms (garmin, notion, habitify, journal-enrichment, weather, dropbox-poll, hae-webhook)
- Add Lambda::Permission resources (S3/API Gateway invoke permissions)

**To run:**
```bash
bash deploy/deploy_ingestion_stack.sh
```

---

### Option B — LifePlatformOperational stack built ✅

New file: `cdk/stacks/operational_stack.py`
Import map: `cdk/operational-import-map.json`
Deploy script: `deploy/deploy_operational_stack.sh`
`cdk/app.py`: OperationalStack uncommented and wired

**8 Lambdas modeled** (all configs verified from AWS):

| Lambda | Function Name | Handler | Timeout | Memory | Schedule | DLQ | Alarm |
|--------|-------------|---------|---------|--------|----------|-----|-------|
| FreshnessChecker | life-platform-freshness-checker | `lambda_function.lambda_handler` | 30s | 128MB | cron(45 16 * * ? *) | ✅ | freshness-checker-errors |
| DlqConsumer | life-platform-dlq-consumer | `dlq_consumer_lambda.lambda_handler` | 120s | 256MB | rate(6 hours) | ❌ | none |
| Canary | life-platform-canary | `canary_lambda.lambda_handler` | 60s | 256MB | rate(4 hours) | ❌ | 4 custom (below) |
| PipAudit | life-platform-pip-audit | `pip_audit_lambda.lambda_handler` | 300s | 512MB | cron(0 17 ? * MON *) | ❌ | none |
| QaSmoke | life-platform-qa-smoke | `qa_smoke_lambda.lambda_handler` | 120s | 256MB | cron(30 18 ? * * *) | ❌ | none |
| KeyRotator | life-platform-key-rotator | `lambda_function.lambda_handler` | 30s | 128MB | SM rotation only | ❌ | key-rotator-errors |
| DataExport | life-platform-data-export | `data_export_lambda.lambda_handler` | 300s | 512MB | none (on-demand) | ❌ | life-platform-data-export-errors |
| DataReconciliation | life-platform-data-reconciliation | `data_reconciliation_lambda.lambda_handler` | 120s | 256MB | cron(30 7 ? * MON *) | ❌ | none |

**Special resources:**
- 4 canary alarms in `LifePlatform/Canary` namespace (custom metrics: CanaryDDBFail, CanaryMCPFail, CanaryS3Fail)
- DLQ depth alarm on SQS (`life-platform-dlq-depth-warning`) — AWS/SQS namespace, Maximum statistic
- Secrets Manager invoke permission for key-rotator (will be CREATED on first deploy)
- Note: `life-platform-canary-any-failure` and `-ddb-failure` both watch `CanaryDDBFail` — AWS actual, preserved as-is

**Key findings during build:**
- All Operational Lambdas use `life-platform-` prefix (not bare names like `freshness-checker`)
- Only `freshness-checker` has a DLQ; all others dlq=None
- `key-rotator` has no env vars in AWS; triggered by SM rotation, not EventBridge
- `pip-audit` schedule is every Monday (not first-Monday-only as described in PROJECT_PLAN)
- `brittany-weekly-email` Lambda already exists in AWS! (spotted in list-functions)

**To run:**
```bash
bash deploy/deploy_operational_stack.sh
```

---

## CDK stack status

| Stack | Status | Notes |
|-------|--------|-------|
| LifePlatformCore | Not in CFn | DDB + S3 + SQS + SNS — import deferred |
| LifePlatformIngestion | ✅ Imported | **Run deploy_ingestion_stack.sh** |
| LifePlatformCompute | ✅ Deployed | |
| LifePlatformEmail | ✅ Deployed | |
| LifePlatformOperational | 🟡 Ready to import | **Run deploy_operational_stack.sh** |
| LifePlatformMcp | 🔴 Not built | Next after Operational |
| LifePlatformMonitoring | 🔴 Not built | |
| LifePlatformWeb | 🔴 Not built | |

---

## Immediate next steps

### Option A (5 min) — Deploy LifePlatformIngestion
```bash
bash deploy/deploy_ingestion_stack.sh
```

### Option B (20 min) — Import + Deploy LifePlatformOperational
```bash
bash deploy/deploy_operational_stack.sh
```
Should be clean: all 8 Lambdas, 6 rules, 12 alarms already exist in AWS.
Only new resource created: SM invoke permission on key-rotator.

### Option C — Build LifePlatformMcp
The MCP stack covers `life-platform-mcp` Lambda + Function URL.
Before building, run role discovery:
```bash
aws lambda get-function-configuration --function-name life-platform-mcp \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize}" \
  --region us-west-2
```

### Option D — Brittany weekly email (fully unblocked, separate from CDK)

---

## Key lessons learned this session

**Operational Lambdas use `life-platform-` prefix** — not bare names. `freshness-checker` in
AWS is `life-platform-freshness-checker`. Verify with `list-functions` before building any stack.

**`brittany-weekly-email` already exists in Lambda** — visible in list-functions output.
The Lambda was deployed previously (likely during a session not reflected in handover notes).
Check what it does before the Brittany email feature session.

**Canary alarms use custom CloudWatch namespace** — can't be modeled with `fn.metric_errors()`.
Use `cloudwatch.Metric` + `cloudwatch.Alarm` directly with `LifePlatform/Canary` namespace.

**DLQ depth alarm is SQS-based** — belongs in OperationalStack (not MonitoringStack)
because it monitors the same DLQ that DlqConsumer processes.

---

## Platform state

**Version:** v3.3.3

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ Compute ✅ Email ✅ Ingestion ✅; Operational 🟡 ready; 3 stacks remaining |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
