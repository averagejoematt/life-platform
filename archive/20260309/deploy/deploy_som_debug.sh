#!/bin/bash
# deploy_som_debug.sh — Add debug logging to trace SoM processing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_DIR/lambdas"
FUNCTION_NAME="health-auto-export-webhook"
REGION="us-west-2"

echo "=== Deploy: SoM debug logging ==="
cd "$LAMBDA_DIR"
cp health_auto_export_lambda.py lambda_function.py
zip -q health_auto_export_lambda.zip lambda_function.py
rm lambda_function.py
echo "📦 Packaged"

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$LAMBDA_DIR/health_auto_export_lambda.zip" \
    --region "$REGION" \
    --no-cli-pager

echo "✅ Deployed with debug logging"
echo ""
echo "Now: trigger HAE State of Mind sync, then check CloudWatch:"
echo "  aws logs filter-log-events --log-group-name /aws/lambda/health-auto-export-webhook --start-time \$(date -v-5M +%s000) --filter-pattern 'SoM DEBUG' --region us-west-2 --no-cli-pager"
