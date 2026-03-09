#!/bin/bash
# Fix 5 retry — Add SQS SendMessage permission to roles, then attach DLQs
set -eo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
DLQ_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:life-platform-ingestion-dlq"

FUNCS="garmin-data-ingestion habitify-data-ingestion notion-journal-ingestion dropbox-poll activity-enrichment journal-enrichment"
ROLES="lambda-garmin-ingestion-role lambda-habitify-ingestion-role lambda-notion-ingestion-role lambda-dropbox-poll-role lambda-enrichment-role lambda-journal-enrichment-role"

FUNC_ARR=($FUNCS)
ROLE_ARR=($ROLES)

echo "Step 1: Adding sqs:SendMessage to each role..."
for i in "${!FUNC_ARR[@]}"; do
  FUNC="${FUNC_ARR[$i]}"
  ROLE="${ROLE_ARR[$i]}"
  echo "  Processing $ROLE (for $FUNC)..."

  POLICY_NAME=$(aws iam list-role-policies --role-name "$ROLE" --region $REGION --query "PolicyNames[0]" --output text)
  EXISTING_POLICY=$(aws iam get-role-policy --role-name "$ROLE" --policy-name "$POLICY_NAME" --region $REGION --query "PolicyDocument" --output json)

  if echo "$EXISTING_POLICY" | grep -q "sqs:SendMessage"; then
    echo "    ⏭️  Already has sqs:SendMessage"
    continue
  fi

  UPDATED_POLICY=$(echo "$EXISTING_POLICY" | python3 -c "
import json, sys
policy = json.load(sys.stdin)
policy['Statement'].append({
    'Sid': 'DLQAccess',
    'Effect': 'Allow',
    'Action': ['sqs:SendMessage'],
    'Resource': '${DLQ_ARN}'
})
print(json.dumps(policy))
")

  aws iam put-role-policy \
    --role-name "$ROLE" \
    --policy-name "$POLICY_NAME" \
    --policy-document "$UPDATED_POLICY" \
    --region $REGION

  echo "    ✅ sqs:SendMessage added"
done

echo ""
echo "Waiting 10s for IAM propagation..."
sleep 10

echo ""
echo "Step 2: Attaching DLQs..."
for FUNC in ${FUNCS}; do
  CURRENT_DLQ=$(aws lambda get-function-configuration \
    --function-name "$FUNC" \
    --region $REGION \
    --query "DeadLetterConfig.TargetArn" \
    --output text 2>/dev/null || echo "None")

  if [ "$CURRENT_DLQ" = "None" ] || [ -z "$CURRENT_DLQ" ]; then
    echo "  Adding DLQ to $FUNC..."
    aws lambda update-function-configuration \
      --function-name "$FUNC" \
      --dead-letter-config "TargetArn=${DLQ_ARN}" \
      --region $REGION \
      --query "FunctionName" \
      --output text
    echo "    ✅ DLQ added"
    sleep 2
  else
    echo "  ⏭️  $FUNC already has DLQ"
  fi
done

echo ""
echo "--- DLQ coverage summary ---"
aws lambda list-functions --region $REGION --query "Functions[*].[FunctionName,DeadLetterConfig.TargetArn || 'NO DLQ']" --output table

echo ""
echo "✅ Fix 5 complete"
