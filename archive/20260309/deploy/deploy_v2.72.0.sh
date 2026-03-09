#!/bin/bash
# Deploy v2.72.0 — 6 Features:
#   #41 Defense Mechanism Detector (journal enrichment + MCP tool)
#   #19 Data Export & Portability (new Lambda + EventBridge)
#   #33 Biological Age Estimation (MCP tool)
#   #38 Continuous Metabolic Health Score (MCP tool)
#   #29 Meal-Level Glycemic Response Database (MCP tool)
#
# New: tools_longevity.py module (4 tools: get_biological_age,
#      get_metabolic_health_score, get_food_response_database, get_defense_patterns)
# Updated: journal_enrichment_lambda.py (defense mechanism second pass)
# New Lambda: data-export (28th Lambda)
#
# Tool count: 116 → 120

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_HELPER="$SCRIPT_DIR/deploy_lambda.sh"

echo "═══════════════════════════════════════════════════════"
echo "  Deploying v2.72.0 — 6 Features"
echo "═══════════════════════════════════════════════════════"

# ── 1. Deploy MCP Server (new tools_longevity.py module) ─────────────────
echo ""
echo "▶ [1/4] Deploying MCP Server (4 new tools)..."
cd "$PROJECT_ROOT/mcp"

# Create deployment package
rm -f /tmp/mcp-deploy.zip
zip -r /tmp/mcp-deploy.zip . \
  -x "__pycache__/*" "*.pyc" ".DS_Store" \
  --quiet

aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb:///tmp/mcp-deploy.zip \
  --region us-west-2 \
  --no-cli-pager \
  --query 'LastModified' \
  --output text

echo "  ✓ MCP server deployed (120 tools)"
sleep 10

# ── 2. Deploy Journal Enrichment Lambda (defense mechanism detection) ────
echo ""
echo "▶ [2/4] Deploying Journal Enrichment Lambda (defense patterns)..."
bash "$DEPLOY_HELPER" journal-enrichment "$PROJECT_ROOT/lambdas/journal_enrichment_lambda.py"
echo "  ✓ Journal enrichment deployed with defense mechanism detection"
sleep 10

# ── 3. Create/Update Data Export Lambda ──────────────────────────────────
echo ""
echo "▶ [3/4] Deploying Data Export Lambda..."

# Check if Lambda exists
if aws lambda get-function --function-name life-platform-data-export --region us-west-2 --no-cli-pager 2>/dev/null; then
  echo "  Lambda exists — updating code..."
  bash "$DEPLOY_HELPER" life-platform-data-export "$PROJECT_ROOT/lambdas/data_export_lambda.py"
else
  echo "  Creating new Lambda function..."

  # Get the IAM role ARN from an existing Lambda
  ROLE_ARN=$(aws lambda get-function \
    --function-name life-platform-mcp \
    --region us-west-2 \
    --no-cli-pager \
    --query 'Configuration.Role' \
    --output text)

  cd /tmp
  rm -f data-export.zip

  # Read handler config — for new Lambdas, we set it ourselves
  cp "$PROJECT_ROOT/lambdas/data_export_lambda.py" data_export_lambda.py
  zip data-export.zip data_export_lambda.py
  rm data_export_lambda.py

  aws lambda create-function \
    --function-name life-platform-data-export \
    --runtime python3.12 \
    --handler data_export_lambda.lambda_handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/data-export.zip \
    --timeout 300 \
    --memory-size 512 \
    --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,USER_ID=matthew}" \
    --region us-west-2 \
    --no-cli-pager \
    --query 'FunctionArn' \
    --output text

  echo "  ✓ Data export Lambda created"
fi
sleep 5

# ── 4. Create EventBridge rule for monthly export ────────────────────────
echo ""
echo "▶ [4/4] Setting up monthly export EventBridge rule..."

# 1st of each month at 3 AM PT (11 AM UTC)
aws events put-rule \
  --name "life-platform-monthly-export" \
  --schedule-expression "cron(0 11 1 * ? *)" \
  --state ENABLED \
  --description "Monthly full data export to S3" \
  --region us-west-2 \
  --no-cli-pager \
  --query 'RuleArn' \
  --output text 2>/dev/null || echo "  (Rule may already exist)"

# Get Lambda ARN
EXPORT_ARN=$(aws lambda get-function \
  --function-name life-platform-data-export \
  --region us-west-2 \
  --no-cli-pager \
  --query 'Configuration.FunctionArn' \
  --output text)

aws events put-targets \
  --rule "life-platform-monthly-export" \
  --targets "Id=data-export,Arn=$EXPORT_ARN,Input={\"export_type\":\"full\"}" \
  --region us-west-2 \
  --no-cli-pager 2>/dev/null || echo "  (Target may already exist)"

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
  --function-name life-platform-data-export \
  --statement-id monthly-export-eventbridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:us-west-2:205930651321:rule/life-platform-monthly-export" \
  --region us-west-2 \
  --no-cli-pager 2>/dev/null || echo "  (Permission may already exist)"

echo "  ✓ Monthly export scheduled (1st of month, 3 AM PT)"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  v2.72.0 Deploy Complete"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  MCP Server:  120 tools (4 new)"
echo "  Lambdas:     28 (1 new: data-export)"
echo "  New module:  mcp/tools_longevity.py"
echo ""
echo "  New tools:"
echo "    • get_biological_age       (#33)"
echo "    • get_metabolic_health_score (#38)"
echo "    • get_food_response_database (#29)"
echo "    • get_defense_patterns     (#41)"
echo ""
echo "  Updated:"
echo "    • journal_enrichment — defense mechanism detection (2nd Haiku call)"
echo "    • data_export — monthly S3 dump (#19)"
echo ""
echo "  Post-deploy:"
echo "    1. Run journal enrichment with force=true to backfill defense patterns:"
echo "       aws lambda invoke --function-name journal-enrichment \\"
echo "         --payload '{\"force\": true}' --cli-binary-format raw-in-base64-out \\"
echo "         --region us-west-2 /tmp/je-out.json && cat /tmp/je-out.json"
echo ""
echo "    2. Test data export:"
echo "       aws lambda invoke --function-name life-platform-data-export \\"
echo "         --payload '{\"export_type\": \"full\"}' --cli-binary-format raw-in-base64-out \\"
echo "         --region us-west-2 /tmp/export-out.json && cat /tmp/export-out.json"
