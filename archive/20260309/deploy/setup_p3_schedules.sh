#!/usr/bin/env bash
# deploy/setup_p3_schedules.sh
# Create EventBridge schedules for new P3 Lambdas.
# Run AFTER deploy_p3_lambdas.sh creates the Lambda functions.
#
# Schedules:
#   data-reconciliation:  Sunday 11:30 PM PT  = Monday 07:30 UTC
#   pip-audit:            1st Monday monthly  = 17:00 UTC (9 AM PT)
#
# Usage: bash deploy/setup_p3_schedules.sh
set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"

echo "Setting up EventBridge schedules for P3 Lambdas..."
echo ""

# ── 1. data-reconciliation — weekly Sunday 23:30 PT = Monday 07:30 UTC ───────
RECON_FUNCTION="life-platform-data-reconciliation"
RECON_RULE="life-platform-data-reconciliation-weekly"

echo "→ Creating reconciliation schedule (Mondays 07:30 UTC)"
aws events put-rule \
  --name "$RECON_RULE" \
  --schedule-expression "cron(30 7 ? * MON *)" \
  --description "Weekly data reconciliation — checks all 19 sources x 7 days. Fires Monday 07:30 UTC (Sun 11:30 PM PT)" \
  --state ENABLED \
  --region "$REGION" \
  --output text --query 'RuleArn'

aws events put-targets \
  --rule "$RECON_RULE" \
  --targets "Id=DataReconciliationTarget,Arn=arn:aws:lambda:${REGION}:${ACCOUNT}:function:${RECON_FUNCTION}" \
  --region "$REGION" \
  --output text --query 'FailedEntryCount'

aws lambda add-permission \
  --function-name "$RECON_FUNCTION" \
  --statement-id "AllowEventBridgeReconciliation" \
  --action "lambda:InvokeFunction" \
  --principal "events.amazonaws.com" \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RECON_RULE}" \
  --region "$REGION" \
  --output text --query 'Statement' 2>/dev/null \
  || echo "  (permission already exists — skipping)"

echo "  ✓ data-reconciliation schedule: cron(30 7 ? * MON *)"

# ── 2. pip-audit — first Monday of month at 17:00 UTC (9 AM PT) ──────────────
# EventBridge doesn't have "first Monday" natively. Closest: every Monday at 17:00
# UTC, and the Lambda checks if it's the first Monday (day ≤ 7). This is a standard
# pattern — add a guard in the Lambda if you want strict first-Monday-only behaviour.
# Alternatively, trigger manually or set up via EventBridge Scheduler (newer service).
AUDIT_FUNCTION="life-platform-pip-audit"
AUDIT_RULE="life-platform-pip-audit-monthly"

echo ""
echo "→ Creating pip-audit schedule (all Mondays 17:00 UTC — Lambda self-guards first-Monday)"
aws events put-rule \
  --name "$AUDIT_RULE" \
  --schedule-expression "cron(0 17 ? * MON *)" \
  --description "Monthly pip-audit scan. Fires every Monday 17:00 UTC; Lambda checks if first Monday of month." \
  --state ENABLED \
  --region "$REGION" \
  --output text --query 'RuleArn'

aws events put-targets \
  --rule "$AUDIT_RULE" \
  --targets "Id=PipAuditTarget,Arn=arn:aws:lambda:${REGION}:${ACCOUNT}:function:${AUDIT_FUNCTION}" \
  --region "$REGION" \
  --output text --query 'FailedEntryCount'

aws lambda add-permission \
  --function-name "$AUDIT_FUNCTION" \
  --statement-id "AllowEventBridgePipAudit" \
  --action "lambda:InvokeFunction" \
  --principal "events.amazonaws.com" \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${AUDIT_RULE}" \
  --region "$REGION" \
  --output text --query 'Statement' 2>/dev/null \
  || echo "  (permission already exists — skipping)"

echo "  ✓ pip-audit schedule: cron(0 17 ? * MON *)"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  EventBridge schedules created."
echo ""
echo "  data-reconciliation: every Monday 07:30 UTC (Sun 11:30 PM PT)"
echo "  pip-audit:           every Monday 17:00 UTC (first-Monday guard in Lambda)"
echo ""
echo "  Test manually:"
echo "    aws lambda invoke --function-name life-platform-data-reconciliation \\"
echo "      --payload '{}' /tmp/recon_out.json --region us-west-2 && cat /tmp/recon_out.json"
echo ""
echo "    aws lambda invoke --function-name life-platform-pip-audit \\"
echo "      --payload '{}' /tmp/audit_out.json --region us-west-2 && cat /tmp/audit_out.json"
echo "════════════════════════════════════════════════════════════"
