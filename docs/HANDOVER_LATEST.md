# Handover — v3.3.4 — 2026-03-09

## What was done this session

### LifePlatformIngestion ✅ deployed
- Root cause of EventBridge "Internal Failure": CDK was calling `PutRule` on imported rules, which AWS rejects
- Fix: removed all `schedule=` params from `ingestion_stack.py`, replaced with `fn.add_permission()` using hardcoded rule ARNs
- Deploy succeeded: Lambda::Permission resources created for all 15 Lambdas
- EventBridge rules managed as unmanaged drift (they work fine, CDK just doesn't update them)

### LifePlatformOperational ✅ imported + deployed
- 7 of 8 Lambdas imported (dlq-consumer, canary, pip-audit, qa-smoke, key-rotator, data-export, data-reconciliation)
- 8 alarms imported (freshness-checker-errors, key-rotator-errors, data-export-errors, 4x canary, dlq-depth)
- Lambda::Permission resources created on deploy
- **freshness-checker Lambda EXCLUDED** — it lives in its own individual CFn stack (`life-platform-freshness-checker`)
  and cannot be imported into LifePlatformOperational while it exists there
- Pattern documented in operational_stack.py: same approach as Ingestion (no `schedule=`, use `add_permission()`)

### Freshness checker stack situation
- `life-platform-freshness-checker` individual CFn stack contains the Lambda with inline code (placeholder handler)
- The actual Lambda code is deployed separately via `deploy_lambda.sh`
- Options for cleanup:
  A. Delete individual stack (Lambda has inline placeholder — no data loss), redeploy via `deploy_lambda.sh`,
     then add freshness-checker back to OperationalStack and run `cdk import`
  B. Leave as-is indefinitely — Lambda runs fine, alarm is tracked in LifePlatformOperational

---

## CDK stack status

| Stack | Status | Notes |
|-------|--------|-------|
| LifePlatformCore | Not in CFn | DDB + S3 + SQS + SNS — import deferred |
| LifePlatformIngestion | ✅ Deployed | EventBridge rules = unmanaged drift |
| LifePlatformCompute | ✅ Deployed | |
| LifePlatformEmail | ✅ Deployed | |
| LifePlatformOperational | ✅ Deployed | freshness-checker Lambda in separate stack |
| LifePlatformMcp | 🔴 Not built | Next |
| LifePlatformMonitoring | 🔴 Not built | |
| LifePlatformWeb | 🔴 Not built | |

---

## Immediate next steps

### Option A — Build LifePlatformMcp (next PROD-1 stack)
Check Lambda config first:
```bash
aws lambda get-function-configuration --function-name life-platform-mcp \
  --region us-west-2 \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize,env:Environment.Variables}"
```
Also check if it has a Function URL:
```bash
aws lambda get-function-url-config --function-name life-platform-mcp --region us-west-2
```

### Option B — Brittany weekly email (fully unblocked)
Note: `brittany-weekly-email` Lambda already exists in AWS (spotted last session).
Check what's in it before building:
```bash
aws lambda get-function-configuration --function-name brittany-weekly-email \
  --region us-west-2 \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize}"
```

### Option C — Freshness checker stack cleanup
```bash
# 1. Delete individual stack (Lambda has inline placeholder code, safe to delete stack)
aws cloudformation delete-stack --stack-name life-platform-freshness-checker --region us-west-2
# 2. Redeploy Lambda code
bash deploy/deploy_lambda.sh life-platform-freshness-checker
# 3. Add back to operational_stack.py + cdk import + cdk deploy
```

---

## Key lessons learned this session

**EventBridge "Internal Failure" on imported rules is consistent** — affects both IngestionStack
and OperationalStack. The fix is permanent: never use `schedule=` for imported Lambdas;
always use `fn.add_permission()` with hardcoded rule ARNs instead. Apply this pattern to all
future stacks (Mcp, Monitoring, etc.) that contain pre-existing EventBridge rules.

**Individual CFn stacks block import** — any Lambda already managed in its own CloudFormation
stack cannot be imported into a different stack. Check `aws cloudformation list-stacks` before
building new stacks to identify conflicts.

**`--force` flag on `cdk import` skips interactive prompts for resources CDK can auto-resolve**
(Lambdas by function_name, alarms by alarm_name). Lambda::Permissions cannot be imported
(no importable identifier) — they're always skipped and created on `cdk deploy`.

---

## Platform state

**Version:** v3.3.4

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ Compute ✅ Email ✅ Ingestion ✅ Operational ✅; 3 stacks remaining (Mcp, Monitoring, Web) |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
