# Life Platform — Handover v3.4.0
**Date:** 2026-03-10
**Session:** Full IaC — CDK-manage IAM roles, EventBridge rules, Core resources

---

## Platform State

| Dimension | Value |
|---|---|
| Version | v3.4.0 |
| MCP Tools | 144 across 30 modules |
| Lambdas | 41 |
| Secrets | 8 |
| Alarms | ~47 |
| CDK Stacks | 8 |
| Cost | ~$25/month |
| AWS | Account 205930651321, us-west-2 |

---

## What Was Done This Session

### Item 6: CDK-manage IAM roles — COMPLETE
- Created `cdk/stacks/role_policies.py` — centralized least-privilege IAM policy definitions for all 41 Lambdas
- Enhanced `lambda_helpers.py` with `custom_policies` parameter (deprecates `existing_role_arn`)
- Updated all 5 Lambda stacks to use `custom_policies=rp.<function>()` instead of `existing_role_arn`
- Deployed all 5 stacks sequentially: MCP → Operational → Compute → Ingestion → Email
- All 41 Lambdas now use CDK-created roles (`LifePlatform*` prefix)
- Deleted 39 orphaned console-created IAM roles

### Item 7: CDK-manage EventBridge rules — COMPLETE
- Switched Ingestion stack (14 rules) + Operational stack (6 rules) from `add_permission` workaround to `schedule=`
- CDK now creates EB rules directly, wires Lambda permissions automatically
- Deleted 40 old console-created EB rules
- 2 rules intentionally kept outside CDK: `life-platform-nightly-warmer` (MCP custom payload), `life-platform-monthly-export`

### 3 previously unmanaged Lambdas adopted
- `failure-pattern-compute` → LifePlatformCompute (deleted orphan Lambda, CDK recreated)
- `life-platform-freshness-checker` → LifePlatformOperational (deleted old CFn stack, CDK recreated)
- `insight-email-parser` → LifePlatformOperational (deleted orphan Lambda, CDK recreated)

### CoreStack (new) — COMPLETE
- SQS DLQ imported into CDK management via `cdk import`
- SNS topic imported into CDK management via `cdk import`
- Lambda Layer v5 published via CDK (pre-built by `deploy/build_layer.sh`)
- DDB table + S3 bucket referenced via `from_table_name`/`from_bucket_name` (deliberately unmanaged)

---

## Deploy Status

All deploys confirmed live as of 2026-03-10:
- ✅ LifePlatformCore — SQS + SNS imported, Layer v5 published
- ✅ LifePlatformMcp — CDK-owned IAM role
- ✅ LifePlatformOperational — CDK-owned IAM roles + EB rules + freshness-checker + insight-parser
- ✅ LifePlatformCompute — CDK-owned IAM roles + failure-pattern-compute
- ✅ LifePlatformIngestion — CDK-owned IAM roles + EB rules
- ✅ LifePlatformEmail — CDK-owned IAM roles
- ✅ 39 old IAM roles deleted
- ✅ 40 old EB rules deleted
- ✅ Old `life-platform-freshness-checker` CFn stack deleted

---

## CDK Coverage (8 stacks)

| Stack | Resources |
|---|---|
| LifePlatformCore | SQS DLQ, SNS topic, Lambda Layer |
| LifePlatformIngestion | 15 Lambdas + 15 EB rules + 16 IAM roles |
| LifePlatformCompute | 8 Lambdas + 9 EB rules + 8 IAM roles |
| LifePlatformEmail | 8 Lambdas + 8 EB rules + 8 IAM roles |
| LifePlatformOperational | 9 Lambdas + 6 EB rules + 9 IAM roles + 6 CW alarms |
| LifePlatformMcp | 1 Lambda + 1 IAM role + 2 CW alarms |
| LifePlatformWeb | 3 CloudFront distributions + ACM certs |
| LifePlatformMonitoring | CW dashboard + 21 alarms |

### Deliberately unmanaged (by design)
- DynamoDB table `life-platform` (stateful — replacement = data loss)
- S3 bucket `matthew-life-platform` (stateful — replacement = data loss)
- MCP Function URL (stable, conflicting resource-based policies)
- 2 EventBridge rules (`life-platform-nightly-warmer`, `life-platform-monthly-export`)
- CloudFront Lambda@Edge auth functions (us-east-1 cross-region)

---

## Hardening Status

35/35 complete. All items from Architecture Review #3 resolved.
- SIMP-1 (MCP tool usage audit) — revisit ~2026-04-08 after 30 days of EMF usage data
- PROD-1 (CDK) — ✅ fully complete as of v3.4.0 (was "all 7 stacks", now 8 stacks with full IaC)

---

## Next Steps

1. **Architecture Review #4:** ~2026-04-08
2. **Next feature: Brittany weekly email** (Lambda slot + source file exist)
3. **SIMP-1:** MCP tool usage audit after 30 days of CloudWatch EMF data
4. Monitor CloudWatch overnight for any permission errors from new CDK roles

---

## Key Paths

- `cdk/stacks/role_policies.py` — NEW: centralized IAM policies for all 41 Lambdas
- `cdk/stacks/lambda_helpers.py` — UPDATED: `custom_policies` param
- `cdk/stacks/core_stack.py` — NEW: SQS + SNS + Lambda Layer
- `cdk/stacks/ingestion_stack.py` — UPDATED: CDK IAM + CDK EB rules
- `cdk/stacks/compute_stack.py` — UPDATED: CDK IAM + failure-pattern-compute
- `cdk/stacks/email_stack.py` — UPDATED: CDK IAM
- `cdk/stacks/operational_stack.py` — UPDATED: CDK IAM + CDK EB rules + freshness + insight-parser
- `cdk/stacks/mcp_stack.py` — UPDATED: CDK IAM
- `deploy/build_layer.sh` — NEW: pre-builds Lambda Layer for CDK
- `deploy/cleanup_old_roles.sh` — ran, 39 roles deleted
