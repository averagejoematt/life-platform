#!/bin/bash
# Deploy Character Sheet Compute Lambda + EventBridge schedule
# Usage:
#   bash deploy/deploy_character_sheet_compute.sh              # deploy
#   bash deploy/deploy_character_sheet_compute.sh --dry-run    # preview only
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REGION="us-west-2"
FUNCTION_NAME="character-sheet-compute"
BUCKET="matthew-life-platform"
# Auto-detect role from existing Lambda (avoids hardcoding ARN)
ROLE_ARN=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --output text --query 'Role' 2>/dev/null || echo "")
if [[ -z "$ROLE_ARN" ]]; then
    echo "ERROR: Could not detect IAM role from life-platform-mcp Lambda."
    echo "Set ROLE_ARN manually and re-run."
    exit 1
fi
SCHEDULE_NAME="character-sheet-compute"
SCHEDULE_EXPR="cron(35 17 * * ? *)"  # 9:35 AM PT = 17:35 UTC
LAMBDA_DIR="$(cd "$(dirname "$0")/.." && pwd)/lambdas"
DEPLOY_DIR="/tmp/character-sheet-compute-deploy"

echo "═══════════════════════════════════════════════════════"
echo "Character Sheet Compute Lambda — Deploy"
echo "═══════════════════════════════════════════════════════"
echo "  Function:  $FUNCTION_NAME"
echo "  Role:      $ROLE_ARN"
echo "  Schedule:  $SCHEDULE_EXPR (9:35 AM PT daily)"
echo "  Mode:      $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE DEPLOY' )"
echo ""

# ── Build zip ──
echo "[1/4] Building deployment package..."
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Lambda handler
cp "$LAMBDA_DIR/character_sheet_lambda.py" "$DEPLOY_DIR/lambda_function.py"

# Shared module — character_engine.py
cp "$LAMBDA_DIR/character_engine.py" "$DEPLOY_DIR/character_engine.py"

cd "$DEPLOY_DIR"
zip -q character-sheet-compute.zip lambda_function.py character_engine.py
ZIP_SIZE=$(du -h character-sheet-compute.zip | cut -f1)
echo "  Package: $ZIP_SIZE (lambda_function.py + character_engine.py)"

if $DRY_RUN; then
    echo ""
    echo "[DRY RUN] Would deploy:"
    echo "  • Create/update Lambda: $FUNCTION_NAME"
    echo "  • Runtime: python3.12, 512 MB, 60s timeout"
    echo "  • Env: TABLE_NAME=life-platform, S3_BUCKET=$BUCKET, USER_ID=matthew"
    echo "  • Schedule: EventBridge rule '$SCHEDULE_NAME' at $SCHEDULE_EXPR"
    echo ""
    echo "Contents:"
    unzip -l character-sheet-compute.zip
    rm -rf "$DEPLOY_DIR"
    exit 0
fi

# ── Deploy Lambda ──
echo ""
echo "[2/4] Deploying Lambda..."

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "  Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://character-sheet-compute.zip" \
        --region "$REGION" \
        --output text --query 'FunctionArn'

    # Wait for update to propagate
    sleep 3

    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --timeout 60 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=$BUCKET,USER_ID=matthew}" \
        --region "$REGION" \
        --output text --query 'FunctionArn'
else
    echo "  Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file "fileb://character-sheet-compute.zip" \
        --timeout 60 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=$BUCKET,USER_ID=matthew}" \
        --region "$REGION" \
        --output text --query 'FunctionArn'
fi

echo "  ✅ Lambda deployed"

# ── EventBridge schedule ──
echo ""
echo "[3/4] Setting up EventBridge schedule..."

# Create or update the rule
RULE_ARN=$(aws events put-rule \
    --name "$SCHEDULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPR" \
    --state ENABLED \
    --description "Daily character sheet computation at 9:35 AM PT" \
    --region "$REGION" \
    --output text --query 'RuleArn')
echo "  Rule: $RULE_ARN"

# Get Lambda ARN
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --output text --query 'Configuration.FunctionArn')

# Add permission for EventBridge to invoke Lambda (idempotent with StatementId)
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "eventbridge-character-sheet-compute" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" 2>/dev/null || true

# Set Lambda as target
aws events put-targets \
    --rule "$SCHEDULE_NAME" \
    --targets "Id=character-sheet-compute-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --output text
echo "  ✅ EventBridge schedule configured"

# ── Verify ──
echo ""
echo "[4/4] Verification..."
INVOKE_RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/character-sheet-invoke.json 2>&1)
echo "  Invoke result: $INVOKE_RESULT"
echo "  Response:"
cat /tmp/character-sheet-invoke.json | python3 -m json.tool 2>/dev/null || cat /tmp/character-sheet-invoke.json
echo ""

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Character Sheet Compute Lambda deployed"
echo "   Next scheduled run: 9:35 AM PT tomorrow"
echo "   Manual test: aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "   Force recompute: aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"force\":true}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "   Specific date: aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"date\":\"2026-03-01\",\"force\":true}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "═══════════════════════════════════════════════════════"
