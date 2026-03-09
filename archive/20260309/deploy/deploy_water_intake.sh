#!/bin/bash
set -euo pipefail

# Deploy health-auto-export-webhook Lambda v1.3.0 (water intake tracking)

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="health-auto-export-webhook"

echo "Deploying $FUNCTION v1.3.0 (water intake)..."

rm -f health_auto_export_lambda.zip
zip -q health_auto_export_lambda.zip health_auto_export_lambda.py

aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file "fileb://health_auto_export_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"

echo "✅ $FUNCTION updated to v1.3.0"
echo ""
echo "Water intake (water_intake_ml) will now flow on the next Health Auto Export sync."
echo "Field: water_intake_ml (sum of all readings per day, in mL)"
echo ""
echo "To verify after next sync:"
echo "  aws dynamodb get-item --table-name life-platform \\"
echo "    --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#apple_health\"},\"sk\":{\"S\":\"DATE#2026-02-24\"}}' \\"
echo "    --projection-expression water_intake_ml --region us-west-2"
