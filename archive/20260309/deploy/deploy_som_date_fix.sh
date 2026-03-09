#!/bin/bash
# deploy_som_date_fix.sh
# Fix: State of Mind entries silently dropped because HAE sends timestamp
# as "start" field, but process_state_of_mind() only checked "date",
# "startDate", "start_date", "timestamp". Added "start" and "end" fallbacks.
#
# After deploying, re-trigger a manual HAE sync of State of Mind (past 7 days)
# to reprocess the entry from March 4th.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_DIR/lambdas"
FUNCTION_NAME="health-auto-export-webhook"
REGION="us-west-2"

echo "=== Deploy: State of Mind date field fix ==="
echo ""

# ── Package Lambda ──
echo "📦 Packaging health_auto_export_lambda.py..."
cd "$LAMBDA_DIR"
cp health_auto_export_lambda.py lambda_function.py
zip -q health_auto_export_lambda.zip lambda_function.py
rm lambda_function.py
echo "   Created health_auto_export_lambda.zip"

# ── Deploy Lambda ──
echo "🚀 Deploying Lambda: $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$LAMBDA_DIR/health_auto_export_lambda.zip" \
    --region "$REGION" \
    --no-cli-pager

echo ""
echo "✅ Deployed!"
echo ""
echo "=== Next Steps ==="
echo "1. Open Health Auto Export on your iPhone"
echo "2. Trigger a manual sync of State of Mind (past 7 days)"
echo "3. Check: aws s3 ls s3://matthew-life-platform/raw/state_of_mind/ --recursive"
echo "4. Verify: the MCP tool get_state_of_mind_trend should now return data"
