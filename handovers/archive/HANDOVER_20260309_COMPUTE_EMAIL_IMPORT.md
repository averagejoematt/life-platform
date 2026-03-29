# Handover — PROD-1 ComputeStack + EmailStack Import Complete
**Date:** 2026-03-09
**Version:** v3.2.10
**Session:** PROD-1 CDK — ComputeStack + EmailStack written and imported

---

## What Was Accomplished

Three CDK stacks now in CloudFormation:
- ✅ `LifePlatformIngestion` (v3.2.8) — 15 Lambdas + 14 EventBridge rules
- ✅ `LifePlatformCompute` (v3.2.10) — 7 Lambdas + 8 EventBridge rules
- ✅ `LifePlatformEmail` (v3.2.10) — 8 Lambdas + 8 EventBridge rules

**Total under CDK: 30 Lambdas + 30 EventBridge rules**

---

## Import Map Format — Established Pattern

The import map format that works (learned from ingestion session, confirmed on compute + email):

```json
{
  "AnomalyDetectorA36086E5": { "FunctionName": "anomaly-detector" },
  "AnomalyDetectorScheduleD1E9ACF8": { "Arn": "arn:aws:events:us-west-2:205930651321:rule/anomaly-detector-daily" }
}
```

**To get the right keys for any future stack:**
```bash
cat cdk.out/LifePlatformXxx.template.json | python3 -c "
import json, sys
t = json.load(sys.stdin)
for lid, res in t['Resources'].items():
    rt = res['Type']
    if rt in ('AWS::Lambda::Function', 'AWS::Events::Rule'):
        props = res.get('Properties', {})
        name = props.get('FunctionName') or props.get('Name') or props.get('ScheduleExpression', '')
        print(f'{rt:<30} {lid:<55} {name}')
"
```
This outputs the exact hashed logical IDs from the synth template. Use those as keys.

**Do NOT** use nested resource type format (`{"AWS::Lambda::Function": {"FunctionName": "..."}}`) — that's wrong and causes "Unrecognized resource identifiers" errors.

---

## CDK Pattern Cheat Sheet (all four bugs solved)

For all remaining stacks (OperationalStack, McpStack, MonitoringStack):

1. **IAM roles** → `iam.Role.from_role_arn()` — no DefaultPolicy, no DependsOn
2. **DLQ** → pass `dead_letter_queue=None`, set via L1 escape hatch after construction
3. **Core resources** → `from_queue_arn / from_table_name / from_bucket_name / from_topic_arn` — no Fn::ImportValue
4. **Import map keys** → hashed logical IDs from `cdk.out/*.template.json`, flat `{FunctionName}` or `{Arn}` values
5. **EventBridge rules** → always `Arn` (not `Name`)

---

## Remaining PROD-1 Stacks (Sessions 4–6)

| Stack | Lambdas | Status |
|-------|---------|--------|
| LifePlatformOperational | dlq-consumer, freshness-checker, canary, qa-smoke, key-rotator, insight-email-parser, data-export, data-reconciliation, pip-audit | 🔴 Not started |
| LifePlatformMcp | life-platform-mcp | 🔴 Not started |
| LifePlatformMonitoring | CloudWatch alarms, dashboards | 🔴 Not started |
| LifePlatformCore | DynamoDB, S3, SQS, SNS | 🔴 Not started |
| LifePlatformWeb | CloudFront distributions | 🔴 Not started |

---

## Other Pending Items

### PROD-2 Manual Follow-ups
- SES receipt rule + S3 event notification for `insight-email-parser`: update prefix `raw/inbound_email/` → `raw/matthew/inbound_email/` (AWS console)

### Old S3 Path Cleanup (~2026-03-16)
```bash
aws s3 rm s3://matthew-life-platform/raw/ --recursive --exclude 'raw/matthew/*'
# + delete old config/*.json files
```

### Feature Work (fully unblocked)
- Brittany weekly email
- Prompt Intelligence fixes P1-P5
- Google Calendar integration

---

## CDK Environment Reference
- Location: `~/Documents/Claude/life-platform/cdk/`
- Activate: `source .venv/bin/activate`
- Account: `205930651321` / Region: `us-west-2`
- Stacks in CFn: LifePlatformIngestion ✅ LifePlatformCompute ✅ LifePlatformEmail ✅
