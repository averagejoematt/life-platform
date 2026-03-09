# Handover — v3.3.6 — 2026-03-09

## What was done this session

### PROD-1 complete ✅ (see v3.3.5 handover)
All 7 CDK stacks deployed. See CHANGELOG for full details.

### Post-deploy alarm triage + hotfixes

**Bug 1: CDK code packaging (all 23 CDK-managed Lambdas broken)**
- CDK's `Code.from_asset("..")` packages files at `lambdas/X.py` path inside the zip,
  but Lambda expects the handler module at the zip root.
- Every Lambda deployed via CDK since the Compute/Email stacks was silently broken.
- Fixed by `deploy/redeploy_all_cdk_lambdas.sh` — redeployed all 23 via `deploy_lambda.sh`.
- **TODO (next session):** Fix `lambda_helpers.py` to use `Code.from_asset("../lambdas")`
  so future CDK deploys don't break Lambda code again.

**Bug 2: `platform_logger.set_date` missing (13 ingestion Lambdas broken)**
- Old-convention ingestion Lambdas had a stale bundled copy of the logger without `set_date()`.
- Fixed by `deploy/redeploy_ingestion_with_logger.sh` — redeployed all 13 with `platform_logger.py`.

**Alarm status after fixes:**
- `slo-mcp-availability` → cleared (MCP Lambda restored)
- All compute/email/operational alarms → will clear on next scheduled invocation
- All ingestion alarms → will clear on next scheduled run tonight
- `slo-daily-brief-delivery`, `slo-source-freshness` → will self-clear overnight
- `life-platform-dlq-depth-warning` → pre-existing, worth investigating separately

---

## Immediate next steps

### CRITICAL (do first) — Fix CDK lambda_helpers.py packaging
Before any future `cdk deploy` touches Lambda code, update `Code.from_asset`:
```python
# In cdk/stacks/lambda_helpers.py, change:
code=_lambda.Code.from_asset("..", exclude=_ASSET_EXCLUDES)
# To:
code=_lambda.Code.from_asset("../lambdas")
```
This ensures CDK zips from the `lambdas/` directory as root, so handler files
land at the zip root where Lambda expects them.

### Option A — Brittany weekly email
`brittany-weekly-email` Lambda already exists in AWS (spotted during CDK work,
confirmed deployed today via redeploy script). Check what's in it:
```bash
aws lambda get-function-configuration --function-name brittany-weekly-email \
  --region us-west-2 \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize}"
```

### Option B — DLQ depth investigation
`life-platform-dlq-depth-warning` has been in ALARM state since March 8.
There are messages stuck in the DLQ. Check what they are:
```bash
aws sqs receive-message \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --region us-west-2 --max-number-of-messages 10
```

### Option C — Freshness checker stack cleanup (low priority)
Delete individual `life-platform-freshness-checker` CFn stack, redeploy Lambda,
add back to OperationalStack.

---

## Platform state

**Version:** v3.3.6

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 | ✅ |
| PROD-1 | ✅ All 7 stacks deployed. TODO: fix lambda_helpers.py Code.from_asset path |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |

## Known unmanaged drift (intentional)
- All EventBridge rules (AWS rejects PutRule on imported rules with existing targets)
- life-platform-mcp Function URL (409 conflict on create)
- life-platform-freshness-checker Lambda (in separate individual CFn stack)
