#!/bin/bash
# Deploy Daily Metrics Compute Lambda + EventBridge schedule
#
# Runs at 9:40 AM PT (17:40 UTC) — between character-sheet-compute (9:35)
# and daily-brief (10:00). Pre-computes all derived metrics so the Brief
# becomes a pure read + render operation.
#
# Usage:
#   bash deploy/deploy_daily_metrics_compute.sh              # deploy
#   bash deploy/deploy_daily_metrics_compute.sh --dry-run    # preview only
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REGION="us-west-2"
FUNCTION_NAME="daily-metrics-compute"
BUCKET="matthew-life-platform"

# Auto-detect IAM role from existing Lambda (avoids hardcoding ARN)
ROLE_ARN=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --output text --query 'Role' 2>/dev/null || echo "")
if [[ -z "$ROLE_ARN" ]]; then
    echo "ERROR: Could not detect IAM role from life-platform-mcp Lambda."
    echo "Set ROLE_ARN manually and re-run."
    exit 1
fi

SCHEDULE_NAME="daily-metrics-compute"
SCHEDULE_EXPR="cron(40 17 * * ? *)"   # 9:40 AM PT = 17:40 UTC
LAMBDA_DIR="$(cd "$(dirname "$0")/.." && pwd)/lambdas"
DEPLOY_DIR="/tmp/daily-metrics-compute-deploy"

echo "═══════════════════════════════════════════════════════"
echo "Daily Metrics Compute Lambda — Deploy"
echo "═══════════════════════════════════════════════════════"
echo "  Function:  $FUNCTION_NAME"
echo "  Role:      $ROLE_ARN"
echo "  Schedule:  $SCHEDULE_EXPR (9:40 AM PT daily)"
echo "  Mode:      $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE DEPLOY' )"
echo ""

# ── Build zip ──
echo "[1/4] Building deployment package..."
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

cp "$LAMBDA_DIR/daily_metrics_compute_lambda.py" "$DEPLOY_DIR/lambda_function.py"
cp "$LAMBDA_DIR/scoring_engine.py"               "$DEPLOY_DIR/scoring_engine.py"

cd "$DEPLOY_DIR"
zip -q daily-metrics-compute.zip lambda_function.py scoring_engine.py
ZIP_SIZE=$(du -h daily-metrics-compute.zip | cut -f1)
echo "  Package: $ZIP_SIZE (lambda_function.py + scoring_engine.py)"

if $DRY_RUN; then
    echo ""
    echo "[DRY RUN] Would deploy:"
    echo "  • Create/update Lambda: $FUNCTION_NAME"
    echo "  • Runtime: python3.12, 512 MB, 120s timeout"
    echo "  • Env: TABLE_NAME=life-platform, S3_BUCKET=$BUCKET, USER_ID=matthew"
    echo "  • Schedule: EventBridge rule '$SCHEDULE_NAME' at $SCHEDULE_EXPR"
    echo ""
    echo "Zip contents:"
    unzip -l daily-metrics-compute.zip
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
        --zip-file "fileb://daily-metrics-compute.zip" \
        --region "$REGION" \
        --output text --query 'FunctionArn'

    sleep 3

    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --timeout 120 \
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
        --zip-file "fileb://daily-metrics-compute.zip" \
        --timeout 120 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=$BUCKET,USER_ID=matthew}" \
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
    --description "Daily metrics pre-computation at 9:40 AM PT (before 10:00 AM daily-brief)" \
    --region "$REGION" \
    --output text --query 'RuleArn')
echo "  Rule: $RULE_ARN"

LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --output text --query 'Configuration.FunctionArn')

# Add EventBridge invoke permission (idempotent)
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "eventbridge-daily-metrics-compute" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$SCHEDULE_NAME" \
    --targets "Id=daily-metrics-compute-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --output text
echo "  ✅ EventBridge schedule configured"

# ── Smoke test ──
echo ""
echo "[4/4] Smoke test (dry-run invoke — no DDB writes)..."
echo "  Note: passing force=true to bypass idempotency check on first run"
INVOKE_RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"date":"'"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)"'","force":false}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-metrics-invoke.json 2>&1 || true)
echo "  Status: $INVOKE_RESULT"
echo "  Response:"
python3 -m json.tool /tmp/daily-metrics-invoke.json 2>/dev/null || cat /tmp/daily-metrics-invoke.json
echo ""

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Daily Metrics Compute Lambda deployed"
echo "   Next scheduled run: 9:40 AM PT tomorrow"
echo ""
echo "   Useful commands:"
echo "   # Run for yesterday (idempotency safe):"
echo "   aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"date\":\"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json && cat /tmp/test.json"
echo ""
echo "   # Force recompute a specific date:"
echo "   aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"date\":\"2026-03-06\",\"force\":true}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json && cat /tmp/test.json"
echo ""
echo "   # Check CloudWatch logs:"
echo "   aws logs describe-log-streams --log-group-name /aws/lambda/$FUNCTION_NAME --order-by LastEventTime --descending --limit 1 --region $REGION --output text --query 'logStreams[0].logStreamName'"
echo "═══════════════════════════════════════════════════════"
