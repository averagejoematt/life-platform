# PROD-1: CDK Infrastructure as Code — Design & Implementation Plan

> Scaffolding code: `cdk/` directory
> Generated: 2026-03-09 v3.2.1

---

## What's Built (Session 1)

| File | Purpose |
|------|---------|
| `cdk.json` | CDK config with all context values (account, region, resource names, domains) |
| `cdk/app.py` | CDK app entry point — defines 8-stack architecture, only core enabled |
| `cdk/stacks/core_stack.py` | DynamoDB + S3 + SQS DLQ + SNS — import-ready for existing resources |
| `cdk/stacks/lambda_helpers.py` | `create_platform_lambda()` — standardized Lambda factory with IAM, DLQ, alarms, EventBridge |
| `cdk/requirements.txt` | CDK Python dependencies |

## 8-Stack Architecture

```
LifePlatformCore          → DynamoDB, S3, SQS, SNS (import existing)
LifePlatformIngestion     → 13 ingestion Lambdas + EventBridge
LifePlatformCompute       → 5 compute Lambdas + EventBridge
LifePlatformEmail         → 7 email Lambdas + EventBridge
LifePlatformOperational   → Anomaly, freshness, canary, DLQ consumer, etc.
LifePlatformMcp           → MCP Lambda + Function URLs
LifePlatformWeb           → 3 CloudFront distributions + ACM
LifePlatformMonitoring    → ~51 CloudWatch alarms + ops dashboard
```

## `create_platform_lambda()` — The Key Abstraction

Every Lambda in the platform follows the same pattern. The helper function encodes all conventions:

```python
fn = create_platform_lambda(self, "WhoopIngestion",
    function_name="whoop-data-ingestion",
    source_file="lambdas/whoop_lambda.py",
    handler="lambda_function.lambda_handler",
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    secrets=["life-platform/whoop"],
    schedule="cron(0 14 * * ? *)",      # 7:00 AM PT
)
```

This single call creates: Lambda function + per-function IAM role (DDB + S3 + Secrets + DLQ scoped) + EventBridge rule + CloudWatch error alarm + SNS action. 39 Lambdas become 39 calls to this helper.

## Import Strategy for Existing Resources

The core stack defines resources that already exist in AWS. First deployment uses `cdk import`:

```bash
# Prerequisites
pip install -r cdk/requirements.txt
cdk bootstrap aws://205930651321/us-west-2

# Import existing resources (interactive — prompts for physical IDs)
cdk import LifePlatformCore
# Enter when prompted:
#   DynamoDB table: life-platform
#   S3 bucket: matthew-life-platform
#   SQS queue URL: https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq
#   SNS topic ARN: arn:aws:sns:us-west-2:205930651321:life-platform-alerts
```

**Risk:** If `cdk import` mismatches a resource, CDK will try to create a duplicate. Always use `cdk diff` before `cdk deploy` to verify no unexpected creates/deletes.

## Remaining Sessions

| Session | What | Effort |
|---------|------|--------|
| 2 | First Lambda (whoop) via `create_platform_lambda()`. Verify IAM, EventBridge, DLQ, alarm all match current state. | 3-4 hr |
| 3 | Remaining 12 ingestion Lambdas (bulk, template pattern from session 2). | 3-4 hr |
| 4 | Compute + email + operational Lambdas. Shared Layer construct. | 3-4 hr |
| 5 | MCP stack (Function URLs, OAuth) + web stack (CloudFront, ACM cross-region). | 3-4 hr |
| 6 | Monitoring stack (51 alarms, ops dashboard) + cleanup + retire bash scripts. | 2-3 hr |

## Key Risks

| Risk | Mitigation |
|------|-----------|
| Import misidentifies resource → creates duplicate | Always `cdk diff` first. Start with one resource at a time. |
| Lambda code packaging differs from deploy_lambda.sh | CDK `Code.from_asset()` uses the same directory. Handler config must match. |
| CloudFront + ACM cross-region (us-east-1) | Web stack needs cross-region stack or custom resource for ACM. |
| Lambda Layer versioning conflict | CDK auto-increments layer versions. May need to import existing layer first. |
| 39 Lambda IAM roles drift from CDK-managed | Compare `cdk diff` output against current IAM state before any deploy. |
