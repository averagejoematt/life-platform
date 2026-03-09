#!/bin/bash
# Life Platform — Audit Fix Script: Phase 1 (Critical) + Phase 2 (Security)
# Generated: 2026-02-25 Session 11
# Safe to re-run (idempotent)

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "============================================"
echo "Phase 1: CRITICAL FIXES"
echo "============================================"

# ─────────────────────────────────────────────────
# FIX 1: Anomaly detector — create missing EventBridge trigger
# The Lambda exists and works, but no EventBridge rule was ever created
# to invoke it on schedule. The daily brief reads empty anomaly data.
# Schedule: 8:05 AM PT = 16:05 UTC (PST, pre-DST)
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 1: Create anomaly-detector EventBridge rule ---"

# Check if rule already exists
EXISTING=$(aws events describe-rule --name anomaly-detector-daily --region $REGION 2>/dev/null || echo "NOTFOUND")
if echo "$EXISTING" | grep -q "NOTFOUND"; then
  echo "Creating EventBridge rule: anomaly-detector-daily"
  aws events put-rule \
    --name anomaly-detector-daily \
    --schedule-expression "cron(5 16 * * ? *)" \
    --state ENABLED \
    --description "Anomaly detector — 8:05 AM PT, before daily brief" \
    --region $REGION

  echo "Adding target: anomaly-detector Lambda"
  aws events put-targets \
    --rule anomaly-detector-daily \
    --targets "Id=anomaly-detector-target,Arn=arn:aws:lambda:${REGION}:${ACCOUNT}:function:anomaly-detector" \
    --region $REGION

  echo "Adding Lambda invoke permission for EventBridge"
  aws lambda add-permission \
    --function-name anomaly-detector \
    --statement-id anomaly-detector-eventbridge \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/anomaly-detector-daily" \
    --region $REGION 2>/dev/null || echo "  (Permission already exists — OK)"

  echo "✅ Fix 1 complete: anomaly-detector-daily rule created"
else
  echo "⏭️  Fix 1 skipped: anomaly-detector-daily rule already exists"
fi

# ─────────────────────────────────────────────────
# FIX 2: Enrichment alarm — wrong function name dimension
# Alarm monitors "activity-enrichment-nightly" (EventBridge rule name)
# instead of "activity-enrichment" (Lambda function name). Will never fire.
# Fix: delete and recreate with correct dimension.
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 2: Fix enrichment alarm function name ---"

# Check current alarm dimension
CURRENT_DIM=$(aws cloudwatch describe-alarms \
  --alarm-names ingestion-error-enrichment \
  --region $REGION \
  --query "MetricAlarms[0].Dimensions[?Name=='FunctionName'].Value" \
  --output text 2>/dev/null || echo "")

if [ "$CURRENT_DIM" = "activity-enrichment-nightly" ]; then
  echo "Deleting alarm with wrong function name dimension..."
  aws cloudwatch delete-alarms \
    --alarm-names ingestion-error-enrichment \
    --region $REGION

  echo "Recreating alarm with correct function name: activity-enrichment"
  aws cloudwatch put-metric-alarm \
    --alarm-name ingestion-error-enrichment \
    --alarm-description "Alert on activity-enrichment Lambda errors" \
    --namespace AWS/Lambda \
    --metric-name Errors \
    --dimensions "Name=FunctionName,Value=activity-enrichment" \
    --statistic Sum \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts" \
    --region $REGION

  echo "✅ Fix 2 complete: enrichment alarm now watches 'activity-enrichment'"
elif [ "$CURRENT_DIM" = "activity-enrichment" ]; then
  echo "⏭️  Fix 2 skipped: alarm already watches correct function name"
else
  echo "⚠️  Fix 2: unexpected dimension value '$CURRENT_DIM' — manual review needed"
fi


echo ""
echo "============================================"
echo "Phase 2: SECURITY FIXES"
echo "============================================"

# ─────────────────────────────────────────────────
# FIX 3: MCP server role — remove dynamodb:Scan
# The MCP server should never need Scan (single-table, all access by PK+SK).
# PutItem is kept — the cache warmer needs it.
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 3: Remove dynamodb:Scan from MCP server role ---"

# Check if Scan is in the policy
HAS_SCAN=$(aws iam get-role-policy \
  --role-name lambda-mcp-server-role \
  --policy-name mcp-server-permissions \
  --region $REGION \
  --query "PolicyDocument.Statement[?Sid=='DynamoDBRead'].Action[]" \
  --output text 2>/dev/null || echo "")

if echo "$HAS_SCAN" | grep -q "dynamodb:Scan"; then
  echo "Updating MCP role policy — removing Scan..."
  aws iam put-role-policy \
    --role-name lambda-mcp-server-role \
    --policy-name mcp-server-permissions \
    --policy-document '{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "DynamoDBRead",
          "Effect": "Allow",
          "Action": [
            "dynamodb:GetItem",
            "dynamodb:Query",
            "dynamodb:PutItem"
          ],
          "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        },
        {
          "Sid": "SecretsRead",
          "Effect": "Allow",
          "Action": [
            "secretsmanager:GetSecretValue"
          ],
          "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/mcp-api-key*"
        },
        {
          "Sid": "S3ReadCGM",
          "Effect": "Allow",
          "Action": [
            "s3:GetObject"
          ],
          "Resource": "arn:aws:s3:::matthew-life-platform/raw/cgm_readings/*"
        }
      ]
    }' \
    --region $REGION

  echo "✅ Fix 3 complete: dynamodb:Scan removed from MCP role"
else
  echo "⏭️  Fix 3 skipped: dynamodb:Scan not found in policy"
fi

# ─────────────────────────────────────────────────
# FIX 4a: Weekly digest role — scope SES to domain identity
# Currently: ses:SendEmail + sesv2:SendEmail on Resource: "*"
# Fix: scope to SES domain identity ARN
# This role is shared by daily-brief, weekly-digest, monthly-digest
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 4a: Scope SES on weekly-digest role (shared by 3 email Lambdas) ---"

aws iam put-role-policy \
  --role-name lambda-weekly-digest-role \
  --policy-name weekly-digest-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:PutItem"
        ],
        "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
      },
      {
        "Effect": "Allow",
        "Action": [
          "secretsmanager:GetSecretValue"
        ],
        "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ses:SendEmail",
          "sesv2:SendEmail"
        ],
        "Resource": "arn:aws:ses:us-west-2:205930651321:identity/mattsusername.com"
      }
    ]
  }' \
  --region $REGION

echo "✅ Fix 4a complete: weekly-digest role SES scoped to mattsusername.com"

# ─────────────────────────────────────────────────
# FIX 4b: Anomaly detector role — scope SES to domain identity
# Same pattern as 4a
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 4b: Scope SES on anomaly-detector role ---"

aws iam put-role-policy \
  --role-name lambda-anomaly-detector-role \
  --policy-name anomaly-detector-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:PutItem"
        ],
        "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
      },
      {
        "Effect": "Allow",
        "Action": [
          "secretsmanager:GetSecretValue"
        ],
        "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "sesv2:SendEmail"
        ],
        "Resource": "arn:aws:ses:us-west-2:205930651321:identity/mattsusername.com"
      }
    ]
  }' \
  --region $REGION

echo "✅ Fix 4b complete: anomaly-detector role SES scoped to mattsusername.com"


# ─────────────────────────────────────────────────
# FIX 5: Add DLQ to Lambdas missing it
# Currently only 5/20 have DLQ. Adding to the 6 ingestion/enrichment
# Lambdas identified in the audit.
# ─────────────────────────────────────────────────
echo ""
echo "--- Fix 5: Add DLQ to missing ingestion Lambdas ---"

DLQ_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:life-platform-ingestion-dlq"

for FUNC in garmin-data-ingestion habitify-data-ingestion notion-journal-ingestion dropbox-poll activity-enrichment journal-enrichment; do
  CURRENT_DLQ=$(aws lambda get-function-configuration \
    --function-name $FUNC \
    --region $REGION \
    --query "DeadLetterConfig.TargetArn" \
    --output text 2>/dev/null || echo "None")

  if [ "$CURRENT_DLQ" = "None" ] || [ -z "$CURRENT_DLQ" ]; then
    echo "Adding DLQ to $FUNC..."
    aws lambda update-function-configuration \
      --function-name $FUNC \
      --dead-letter-config "TargetArn=${DLQ_ARN}" \
      --region $REGION \
      --query "FunctionName" \
      --output text
    echo "  ✅ DLQ added to $FUNC"
    # Small delay to avoid throttling on consecutive config updates
    sleep 2
  else
    echo "  ⏭️  $FUNC already has DLQ"
  fi
done

echo ""
echo "============================================"
echo "VERIFICATION"
echo "============================================"

echo ""
echo "--- Verifying anomaly detector EventBridge rule ---"
aws events describe-rule --name anomaly-detector-daily --region $REGION --query "[Name,State,ScheduleExpression]" --output text

echo ""
echo "--- Verifying enrichment alarm dimension ---"
aws cloudwatch describe-alarms --alarm-names ingestion-error-enrichment --region $REGION --query "MetricAlarms[0].Dimensions[0].Value" --output text

echo ""
echo "--- Verifying MCP role (should NOT have Scan) ---"
aws iam get-role-policy --role-name lambda-mcp-server-role --policy-name mcp-server-permissions --region $REGION --query "PolicyDocument.Statement[?Sid=='DynamoDBRead'].Action[]" --output text

echo ""
echo "--- Verifying SES scoping on weekly-digest role ---"
aws iam get-role-policy --role-name lambda-weekly-digest-role --policy-name weekly-digest-access --region $REGION --query "PolicyDocument.Statement[2].Resource" --output text

echo ""
echo "--- Verifying SES scoping on anomaly-detector role ---"
aws iam get-role-policy --role-name lambda-anomaly-detector-role --policy-name anomaly-detector-access --region $REGION --query "PolicyDocument.Statement[2].Resource" --output text

echo ""
echo "--- DLQ coverage summary ---"
aws lambda list-functions --region $REGION --query "Functions[*].[FunctionName,DeadLetterConfig.TargetArn || 'NO DLQ']" --output table

echo ""
echo "============================================"
echo "ALL PHASE 1-2 FIXES COMPLETE"
echo "============================================"
echo ""
echo "Next: Test anomaly detector invocation:"
echo "  aws lambda invoke --function-name anomaly-detector --region us-west-2 --payload '{}' /tmp/anomaly-test.json && cat /tmp/anomaly-test.json"
echo ""
echo "Next: Test daily-brief still sends (SES scoping):"
echo "  aws lambda invoke --function-name daily-brief --region us-west-2 --payload '{}' /tmp/brief-test.json && cat /tmp/brief-test.json"
