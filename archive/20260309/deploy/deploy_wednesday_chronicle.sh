#!/bin/bash
# Deploy Wednesday Chronicle Lambda — "The Measured Life" by Elena Voss
# v1.0 — Phase 1: Lambda + Email + Blog
#
# Prerequisites:
#   - Lambda role: lambda-weekly-digest-role (already exists, used by all email Lambdas)
#   - SES verified: awsdev@mattsusername.com
#   - S3 bucket: matthew-life-platform
#   - Anthropic key in Secrets Manager: life-platform/anthropic
#
# Usage: bash deploy/deploy_wednesday_chronicle.sh

set -euo pipefail

FUNCTION_NAME="wednesday-chronicle"
HANDLER="lambda_function.lambda_handler"
RUNTIME="python3.12"
ROLE="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/lambda-weekly-digest-role"
REGION="us-west-2"
TIMEOUT=120
MEMORY=256
LAMBDA_DIR="lambdas"
DEPLOY_DIR="deploy"

echo "========================================="
echo "  Deploying: Wednesday Chronicle v1.0"
echo "  \"The Measured Life\" by Elena Voss"
echo "========================================="

# ── Step 1: Create deployment zip ──────────────────────────────────
echo ""
echo "[1/5] Creating deployment package..."
cd "$LAMBDA_DIR"
cp wednesday_chronicle_lambda.py lambda_function.py
zip -j ../deploy/wednesday_chronicle.zip lambda_function.py
rm lambda_function.py
cd ..
echo "  ✓ wednesday_chronicle.zip created"

# ── Step 2: Create or update Lambda ───────────────────────────────
echo ""
echo "[2/5] Deploying Lambda function..."

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Function exists — updating code..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://deploy/wednesday_chronicle.zip \
        --region "$REGION" \
        --no-cli-pager
    
    echo "  Waiting for update to complete..."
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    
    echo "  Updating configuration..."
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,USER_ID=matthew,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com}" \
        --region "$REGION" \
        --no-cli-pager
else
    echo "  Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime "$RUNTIME" \
        --handler "$HANDLER" \
        --role "$ROLE" \
        --zip-file fileb://deploy/wednesday_chronicle.zip \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,USER_ID=matthew,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com}" \
        --region "$REGION" \
        --no-cli-pager
    
    echo "  Waiting for function to be active..."
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi
echo "  ✓ Lambda deployed"

# ── Step 3: Configure Dead Letter Queue (if available) ────────────
echo ""
echo "[3/5] Checking DLQ configuration..."
DLQ_ARN=$(aws sqs get-queue-attributes \
    --queue-url "https://sqs.${REGION}.amazonaws.com/$(aws sts get-caller-identity --query Account --output text)/life-platform-dlq" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text \
    --region "$REGION" 2>/dev/null || echo "NONE")

if [ "$DLQ_ARN" != "NONE" ] && [ "$DLQ_ARN" != "" ]; then
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --dead-letter-config "TargetArn=$DLQ_ARN" \
        --region "$REGION" \
        --no-cli-pager 2>/dev/null || true
    echo "  ✓ DLQ configured: $DLQ_ARN"
else
    echo "  ⚠ No DLQ found — skipping (non-critical)"
fi

# ── Step 4: Create EventBridge schedule ───────────────────────────
echo ""
echo "[4/5] Setting up EventBridge schedule..."
RULE_NAME="wednesday-chronicle-schedule"

# Wednesday 7:00 AM PT = 15:00 UTC (PDT) or 15:00 UTC (PST equivalent for cron)
# Using 14:00 UTC for PST (winter), will adjust for DST manually
# Current: PST so 7am PT = 15:00 UTC
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 15 ? * WED *)" \
    --state ENABLED \
    --description "Wednesday Chronicle - The Measured Life by Elena Voss - Wed 7:00 AM PT" \
    --region "$REGION" \
    --no-cli-pager

LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeWednesdayChronicle" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:$(aws sts get-caller-identity --query Account --output text):rule/${RULE_NAME}" \
    --region "$REGION" \
    --no-cli-pager 2>/dev/null || echo "  (Permission already exists)"

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=WednesdayChronicleTarget,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --no-cli-pager

echo "  ✓ Scheduled: Wednesday 7:00 AM PT (15:00 UTC)"

# ── Step 5: Test invocation ───────────────────────────────────────
echo ""
echo "[5/5] Running test invocation..."
echo "  This will generate the first installment and send an email."
echo ""
read -p "  Run test now? (y/n): " RUN_TEST

if [ "$RUN_TEST" = "y" ] || [ "$RUN_TEST" = "Y" ]; then
    echo "  Invoking Lambda (this takes 30-60 seconds for AI generation)..."
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --cli-read-timeout 120 \
        --payload '{}' \
        /tmp/chronicle_response.json \
        --no-cli-pager
    
    echo ""
    echo "  Response:"
    cat /tmp/chronicle_response.json
    echo ""
else
    echo "  Skipped test. To invoke manually:"
    echo "  aws lambda invoke --function-name $FUNCTION_NAME --region $REGION --cli-read-timeout 120 --payload '{}' /tmp/chronicle_response.json"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  ✓ Wednesday Chronicle deployed!"
echo "========================================="
echo ""
echo "  Lambda:    $FUNCTION_NAME"
echo "  Schedule:  Wednesdays 7:00 AM PT"
echo "  Email:     Newsletter to awsdev@mattsusername.com"
echo "  Blog:      s3://matthew-life-platform/blog/"
echo "  DynamoDB:  USER#matthew#SOURCE#chronicle"
echo "  Model:     Sonnet 4.5, temp 0.6"
echo "  Cost:      ~\$0.04/week (~\$0.17/month)"
echo ""
echo "  Blog URL (once CloudFront is configured):"
echo "  https://averagejoematt.com/blog/"
echo ""
echo "  Next steps (Phase 2):"
echo "  1. CloudFront distribution for averagejoematt.com/blog"
echo "  2. ACM certificate + Route 53 DNS"
echo "  3. Review first installment and tune Elena's voice"
echo ""
