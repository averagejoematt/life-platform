#!/bin/bash
# deploy_v2.41.0_state_of_mind.sh
# Deploy webhook Lambda v1.5.0 with State of Mind ingestion support
# 
# What this does:
#   1. Packages health_auto_export_lambda.py as Lambda zip
#   2. Updates the Lambda function code
#
# After deploying, you need to configure Health Auto Export on your iPhone:
#   1. Open Health Auto Export → Automated Exports → New Automation
#   2. Select "REST API" as Automation Type
#   3. Data Type: "State of Mind" (NOT Health Metrics)
#   4. URL: same Lambda Function URL as your existing health metrics automation
#   5. Headers: Authorization = Bearer <same token>
#   6. Export Format: JSON, Version 2
#   7. Date Range: "Since Last Sync"
#   8. Sync Cadence: every 1 hour (or your preference)
#   9. Run a Manual Export to test — check CloudWatch logs for "State of Mind detected"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_DIR/lambdas"
FUNCTION_NAME="health-auto-export-webhook"
REGION="us-west-2"

echo "=== Life Platform v2.41.0 — State of Mind Ingestion ==="
echo ""

# ── Step 1: Package Lambda ──
echo "📦 Packaging health_auto_export_lambda.py..."
cd "$LAMBDA_DIR"
cp health_auto_export_lambda.py lambda_function.py
zip -q health_auto_export_lambda.zip lambda_function.py
rm lambda_function.py
echo "   Created health_auto_export_lambda.zip"

# ── Step 2: Deploy Lambda ──
echo "🚀 Deploying Lambda: $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$LAMBDA_DIR/health_auto_export_lambda.zip" \
    --region "$REGION" \
    --no-cli-pager

echo ""
echo "✅ Lambda deployed successfully!"
echo ""
echo "=== Next Steps ==="
echo "1. Open Health Auto Export on your iPhone"
echo "2. Go to Automated Exports → New Automation → REST API"
echo "3. Set Data Type to 'State of Mind'"
echo "4. Use the same URL and Authorization header as your existing automation"
echo "5. Export Format: JSON, Version 2"
echo "6. Date Range: 'Since Last Sync'"
echo "7. Run a Manual Export to test"
echo "8. Check CloudWatch logs for 'State of Mind detected' message"
echo ""
echo "Data flow: How We Feel → HealthKit → Health Auto Export → Lambda → DynamoDB + S3"
echo "  S3: raw/state_of_mind/YYYY/MM/DD.json (individual check-ins)"
echo "  DynamoDB: som_avg_valence, som_check_in_count, som_top_labels, etc."
echo ""
echo "MCP tool available: get_state_of_mind_trend"
