#!/bin/bash
# Deploy The Weekly Plate Lambda + EventBridge schedule
# New Lambda: weekly-plate (26th Lambda)
# Schedule: Friday 6:00 PM PT = Saturday 02:00 UTC
# Usage:
#   bash deploy/deploy_weekly_plate.sh              # deploy
#   bash deploy/deploy_weekly_plate.sh --dry-run    # preview only
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REGION="us-west-2"
FUNCTION_NAME="weekly-plate"
BUCKET="matthew-life-platform"
# Auto-detect role from existing Lambda
ROLE_ARN=$(aws lambda get-function-configuration \
    --function-name daily-brief \
    --region "$REGION" \
    --output text --query 'Role' 2>/dev/null || echo "")
if [[ -z "$ROLE_ARN" ]]; then
    echo "ERROR: Could not detect IAM role from daily-brief Lambda."
    echo "Set ROLE_ARN manually and re-run."
    exit 1
fi
SCHEDULE_NAME="weekly-plate"
SCHEDULE_EXPR="cron(0 2 ? * SAT *)"  # Saturday 02:00 UTC = Friday 6:00 PM PT
LAMBDA_DIR="$(cd "$(dirname "$0")/.." && pwd)/lambdas"
DEPLOY_DIR="/tmp/weekly-plate-deploy"

echo "═══════════════════════════════════════════════════════"
echo "The Weekly Plate — Deploy"
echo "═══════════════════════════════════════════════════════"
echo "  Function:  $FUNCTION_NAME"
echo "  Role:      $ROLE_ARN"
echo "  Schedule:  $SCHEDULE_EXPR (Friday 6:00 PM PT)"
echo "  Mode:      $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE DEPLOY' )"
echo ""

# ── Build zip ──
echo "[1/4] Building deployment package..."
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

cp "$LAMBDA_DIR/weekly_plate_lambda.py" "$DEPLOY_DIR/lambda_function.py"

# Include board_loader if present (for future voice customization)
if [ -f "$LAMBDA_DIR/board_loader.py" ]; then
    cp "$LAMBDA_DIR/board_loader.py" "$DEPLOY_DIR/board_loader.py"
    echo "  Included: lambda_function.py + board_loader.py"
else
    echo "  Included: lambda_function.py"
fi

cd "$DEPLOY_DIR"
zip -q weekly-plate.zip ./*
ZIP_SIZE=$(du -h weekly-plate.zip | cut -f1)
echo "  Package: $ZIP_SIZE"

if $DRY_RUN; then
    echo ""
    echo "[DRY RUN] Would deploy:"
    echo "  • Create Lambda: $FUNCTION_NAME"
    echo "  • Runtime: python3.12, 512 MB, 120s timeout"
    echo "  • Env: TABLE_NAME=life-platform, S3_BUCKET=$BUCKET, USER_ID=matthew"
    echo "  • Email: awsdev@mattsusername.com"
    echo "  • Schedule: EventBridge rule '$SCHEDULE_NAME' at $SCHEDULE_EXPR"
    echo ""
    echo "Contents:"
    unzip -l weekly-plate.zip
    rm -rf "$DEPLOY_DIR"
    exit 0
fi

# ── Deploy Lambda ──
echo ""
echo "[2/4] Deploying Lambda..."

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "  Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://weekly-plate.zip" \
        --region "$REGION" \
        --output text --query 'FunctionArn'
else
    echo "  Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file "fileb://weekly-plate.zip" \
        --timeout 120 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=$BUCKET,USER_ID=matthew,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com}" \
        --region "$REGION" \
        --output text --query 'FunctionArn'
fi

echo "  ✅ Lambda deployed"

# ── EventBridge schedule ──
echo ""
echo "[3/4] Setting up EventBridge schedule..."

RULE_ARN=$(aws events put-rule \
    --name "$SCHEDULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPR" \
    --state ENABLED \
    --description "The Weekly Plate — Friday 6PM PT food magazine email" \
    --region "$REGION" \
    --output text --query 'RuleArn')
echo "  Rule: $RULE_ARN"

LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --output text --query 'Configuration.FunctionArn')

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "eventbridge-weekly-plate" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$SCHEDULE_NAME" \
    --targets "Id=weekly-plate-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --output text
echo "  ✅ EventBridge schedule configured"

# ── Test invoke ──
echo ""
echo "[4/4] Test invocation..."
INVOKE_RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/weekly-plate-invoke.json 2>&1)
echo "  Invoke result: $INVOKE_RESULT"
echo "  Response:"
cat /tmp/weekly-plate-invoke.json | python3 -m json.tool 2>/dev/null || cat /tmp/weekly-plate-invoke.json
echo ""

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ The Weekly Plate deployed (26th Lambda)"
echo "   Schedule: Friday 6:00 PM PT (Saturday 02:00 UTC)"
echo "   First run: This Friday evening"
echo ""
echo "   Manual test:"
echo "   aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "═══════════════════════════════════════════════════════"
