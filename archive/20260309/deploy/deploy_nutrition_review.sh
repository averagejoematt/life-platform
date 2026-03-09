#!/bin/bash
set -euo pipefail

# Deploy Nutrition Review Lambda
# Creates: Lambda function, EventBridge rule (Sat 9am PT), IAM permissions
#
# Usage:
#   chmod +x deploy/deploy_nutrition_review.sh
#   deploy/deploy_nutrition_review.sh              # first-time setup
#   deploy/deploy_nutrition_review.sh --update     # update code only
#   deploy/deploy_nutrition_review.sh --test       # invoke manually (sends email NOW)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

FUNCTION_NAME="nutrition-review"
LAMBDA_FILE="lambdas/nutrition_review_lambda.py"
ZIP_FILE="lambdas/nutrition_review_lambda.zip"
REGION="us-west-2"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="lambda-weekly-digest-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "=== Nutrition Review Deploy ==="
cd "$PROJECT_DIR"

# ────────────────────────────────────────────────────
# Test mode: just invoke
# ────────────────────────────────────────────────────
if [ "${1:-}" = "--test" ]; then
    echo "Invoking $FUNCTION_NAME..."
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --payload '{}' \
        --cli-binary-format raw-in-base64-out \
        /tmp/nutrition-review-output.json \
        --no-cli-pager
    echo ""
    echo "Response:"
    cat /tmp/nutrition-review-output.json
    echo ""
    echo ""
    echo "Check CloudWatch for full logs:"
    echo "  aws logs tail /aws/lambda/$FUNCTION_NAME --since 5m --region $REGION"
    exit 0
fi

# ────────────────────────────────────────────────────
# Package
# ────────────────────────────────────────────────────
echo "1. Packaging..."
cd "$PROJECT_DIR"
cp "$LAMBDA_FILE" /tmp/lambda_function.py
cd /tmp
zip -j nutrition_review_lambda.zip lambda_function.py
cp nutrition_review_lambda.zip "$PROJECT_DIR/$ZIP_FILE"
cd "$PROJECT_DIR"
echo "   ✅ Packaged $(du -h $ZIP_FILE | cut -f1)"

# ────────────────────────────────────────────────────
# Update-only mode
# ────────────────────────────────────────────────────
if [ "${1:-}" = "--update" ]; then
    echo "2. Updating Lambda code..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Lambda updated"
    exit 0
fi

# ────────────────────────────────────────────────────
# Full deploy
# ────────────────────────────────────────────────────

# Step 1: Create or update Lambda
echo "2. Creating/updating Lambda function..."
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Lambda code updated"
else
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 120 \
        --memory-size 256 \
        --environment "Variables={TABLE_NAME=life-platform,USER_ID=matthew,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com}" \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Lambda created"
    echo "   Waiting for active state..."
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi

# Step 2: EventBridge rule — Saturday 9:00 AM PT = 17:00 UTC
echo "3. Setting up EventBridge schedule..."
RULE_NAME="nutrition-review-saturday"
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 17 ? * SAT *)" \
    --state ENABLED \
    --description "Nutrition Review - Saturday 9am PT" \
    --region "$REGION" --no-cli-pager
echo "   ✅ Rule: $RULE_NAME (Sat 9am PT)"

# Step 3: Add Lambda as target
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=nutrition-review-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" --no-cli-pager
echo "   ✅ Target added"

# Step 4: Grant EventBridge permission to invoke Lambda
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "nutrition-review-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "   (permission already exists)"

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Schedule: Every Saturday at 9:00 AM PT"
echo "Lambda:   $FUNCTION_NAME (120s timeout, 256MB)"
echo ""
echo "Commands:"
echo "  Test now:    deploy/deploy_nutrition_review.sh --test"
echo "  Update code: deploy/deploy_nutrition_review.sh --update"
echo "  Check logs:  aws logs tail /aws/lambda/$FUNCTION_NAME --since 5m --region $REGION"
