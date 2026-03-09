# Handover — v3.3.5 — 2026-03-09

## What was done this session

### PROD-1 complete ✅ — all 7 CDK stacks deployed

| Stack | Status | Notes |
|-------|--------|-------|
| LifePlatformCore | Not in CFn | DDB + S3 + SQS + SNS — import deferred (safe, stable) |
| LifePlatformIngestion | ✅ Deployed | 15 Lambdas + Lambda::Permissions. EB rules = unmanaged drift |
| LifePlatformCompute | ✅ Deployed | |
| LifePlatformEmail | ✅ Deployed | |
| LifePlatformOperational | ✅ Deployed | 7 Lambdas + 8 alarms. freshness-checker Lambda in separate individual stack |
| LifePlatformMcp | ✅ Deployed | Lambda + 2 alarms. Function URL = unmanaged drift (409 on create) |
| LifePlatformMonitoring | ✅ Deployed | 21 alarms (SLO + daily-brief + AI token budgets + DDB item size) |
| LifePlatformWeb | ✅ Deployed | 3 CloudFront distributions (us-east-1). Bootstrapped us-east-1 |

### Key patterns established (apply to all future stacks)
1. **No `schedule=` on imported Lambdas** — always use `fn.add_permission()` with hardcoded rule ARNs. CDK never touches EB rules.
2. **No `add_function_url()` on existing Lambdas** — Function URLs cannot be imported; they 409 on create. Leave as unmanaged drift.
3. **CloudFront stacks deploy to us-east-1** — bootstrapped this session.
4. **`--force` on `cdk import`** — auto-resolves Lambdas by function_name, alarms by alarm_name. Lambda::Permissions always skipped (no importable identifier), created on deploy.

### Unmanaged drift (intentional, documented)
- All EventBridge rules (EB refuses to UPDATE imported rules with existing targets)
- life-platform-mcp Function URL (409 conflict on create)
- life-platform-freshness-checker Lambda (in separate individual CFn stack)

---

## Immediate next steps

### Option A — Brittany weekly email
`brittany-weekly-email` Lambda already exists in AWS (spotted earlier). Check first:
```bash
aws lambda get-function-configuration --function-name brittany-weekly-email \
  --region us-west-2 \
  --query "{handler:Handler,role:Role,timeout:Timeout,memory:MemorySize,env:Environment.Variables}"
```

### Option B — Freshness checker stack cleanup (low priority)
Individual CFn stack `life-platform-freshness-checker` contains Lambda with inline placeholder code.
Options:
  A. Delete stack → redeploy via `deploy_lambda.sh` → add to OperationalStack + `cdk import`
  B. Leave as-is indefinitely

### Option C — LifePlatformCore import
DDB, S3, SQS, SNS. These are the most critical resources — import is safe but low urgency
since they're stable. Approach: use L1 CfnTable/CfnBucket with DeletionPolicy=Retain.

---

## Platform state

**Version:** v3.3.5

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 | ✅ |
| PROD-1 | ✅ All 7 stacks deployed (Core deferred — low priority) |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
