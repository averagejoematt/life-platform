# Handover — PROD-1 IngestionStack Import Complete
**Date:** 2026-03-09  
**Version:** v3.2.8  
**Session:** PROD-1 CDK IngestionStack — cdk import succeeded

---

## What Was Accomplished

`cdk import LifePlatformIngestion` **succeeded** after resolving 4 categories of errors:

### Errors Fixed (in order encountered)

1. **Bootstrap missing** — `npx cdk bootstrap aws://205930651321/us-west-2` (one-time, done)

2. **DefaultPolicy DependsOn** — `iam.Role()` auto-generates a `DefaultPolicy` attached to the role, which creates `DependsOn` on the Lambda. CloudFormation rejects import changesets with unresolved dependencies.  
   **Fix:** `iam.Role.from_role_arn()` — CDK treats it as immutable external reference, no policy generated.

3. **DLQ grant DependsOn** — Even with `from_role_arn`, passing `dead_letter_queue=` to `_lambda.Function()` triggers CDK's internal `grant_send_messages`, generating another IAM policy with a `DependsOn`.  
   **Fix:** Pass `dead_letter_queue=None` and set via L1 escape hatch: `fn.node.default_child.dead_letter_config = CfnFunction.DeadLetterConfigProperty(target_arn=dlq.queue_arn)`

4. **Cross-stack Fn::ImportValue** — IngestionStack received table, bucket, DLQ, and alerts topic as CDK construct references from CoreStack. This generates `Fn::ImportValue` in the template. CoreStack isn't in CloudFormation yet, so those exports don't exist → rollback.  
   **Fix:** Resolve all four locally using `from_*` lookups by hardcoded ARN/name constants at module level. The passed-in `table`, `bucket`, `dlq`, `alerts_topic` params from `app.py` are now **unused** inside IngestionStack — local references shadow them.

5. **EventBridge import map key** — Rules need `{"Arn": "arn:aws:events:..."}` not `{"Name": "rule-name"}`.

---

## Current State

**LifePlatformIngestion stack:** IMPORT_COMPLETE ✅  
- 15 Lambdas under CDK management  
- 14 EventBridge rules under CDK management  
- IAM roles, CloudWatch alarms, DLQ config: external references (not managed by CDK)

**Next step recommended:** Run a `cdk deploy LifePlatformIngestion` to reconcile any drift (alarms, Lambda permissions that were skipped during import). CDK will show a diff first.

Or proceed to the next CDK stack session.

---

## Patterns Established for All Remaining Stacks

These apply to every stack that references CoreStack resources (ComputeStack, EmailStack, OperationalStack, McpStack, MonitoringStack):

```python
# ✅ Reference existing IAM roles — never create new ones
role = iam.Role.from_role_arn(self, f"{id}Role", existing_role_arn)

# ✅ Set DLQ via L1 escape hatch — never use dead_letter_queue= param with existing roles
fn = _lambda.Function(..., dead_letter_queue=None, ...)
fn.node.default_child.dead_letter_config = _lambda.CfnFunction.DeadLetterConfigProperty(
    target_arn=dlq.queue_arn
)

# ✅ Resolve core resources locally — don't use CFn cross-stack exports
local_table  = dynamodb.Table.from_table_name(self, "Table", "life-platform")
local_bucket = s3.Bucket.from_bucket_name(self, "Bucket", "matthew-life-platform")
local_dlq    = sqs.Queue.from_queue_arn(self, "DLQ", f"arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq")
local_topic  = sns.Topic.from_topic_arn(self, "Topic", f"arn:aws:sns:us-west-2:205930651321:life-platform-alerts")

# ✅ EventBridge import map — use Arn, not Name
{"RuleLogicalId123": {"Arn": "arn:aws:events:us-west-2:205930651321:rule/rule-name"}}
```

---

## Files Modified This Session

| File | Change |
|------|--------|
| `cdk/stacks/lambda_helpers.py` | Added `existing_role_arn` param; `from_role_arn` branch; L1 DLQ escape hatch |
| `cdk/stacks/ingestion_stack.py` | ARN constants for all 4 core resources; `from_*` local lookups; HAE uses local refs |
| `cdk/ingestion-import-map.json` | Roles removed; EventBridge entries use `Arn` key |

---

## Pending / Next Steps

### Immediate
1. **Optional: `cdk deploy LifePlatformIngestion`** — reconciles skipped resources (alarms, Lambda permissions). Safe to run; CDK will show diff before applying.
2. **PROD-2 manual follow-up** — SES receipt rule + S3 event notification for insight-email-parser: update prefix `raw/inbound_email/` → `raw/matthew/inbound_email/` (AWS console)
3. **Old S3 path cleanup** (~2026-03-16): `aws s3 rm s3://matthew-life-platform/raw/ --recursive --exclude 'raw/matthew/*'` + delete old `config/*.json`

### PROD-1 Remaining CDK Stacks (Sessions 3–6)
Apply the patterns above to:
- **ComputeStack** — character-sheet-compute, dashboard-refresh-afternoon/evening, anomaly-detector, day-grader, habit-scores
- **EmailStack** — daily-brief, weekly-digest, monthly-digest, nutrition-review, wednesday-chronicle, weekly-plate-schedule
- **OperationalStack** — life-platform-mcp, life-platform-key-rotator, health-alert-notifier, qa-smoke, canary
- **McpStack** — API Gateway, Function URL config
- **MonitoringStack** — CloudWatch alarms, dashboards

### Other Upcoming
- Brittany weekly email (fully unblocked)
- Prompt Intelligence fixes P1-P5
- Google Calendar integration
