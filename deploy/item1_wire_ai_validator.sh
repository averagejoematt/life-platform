#!/bin/bash
# item1_wire_ai_validator.sh — AI-3: Wire ai_output_validator into daily-brief
#
# Steps:
#   1. Rebuild shared-utils Layer (adds ai_output_validator.py)
#   2. Run layer attach script with new ARN
#   3. Deploy daily-brief Lambda
#   4. Verify via CloudWatch logs

set -euo pipefail
REGION="us-west-2"

echo "═══ Item 1: Wire AI Output Validator ═══"
echo ""
echo "Step 1/3: Rebuilding shared-utils Layer (adding ai_output_validator.py)..."
echo "  This will print a Layer ARN at the end — copy it for Step 2."
echo ""
bash deploy/p3_build_shared_utils_layer.sh

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Step 2/3: Attach new Layer to daily-brief."
echo "  Copy the Layer ARN from above and run:"
echo ""
echo "  bash deploy/p3_attach_shared_utils_layer.sh <LAYER_ARN>"
echo ""
echo "  (Once done, press Enter here to continue to the deploy step)"
read -r

echo "Step 3/3: Deploying daily-brief Lambda..."
bash deploy/deploy_unified.sh daily-brief

echo ""
echo "═══ Verification ═══"
echo "Check CloudWatch for [AI-3] entries after next Daily Brief fires (10 AM PT):"
echo ""
echo "  STREAM=\$(aws logs describe-log-streams \\"
echo "    --log-group-name /aws/lambda/daily-brief \\"
echo "    --order-by LastEventTime --descending --limit 1 \\"
echo "    --query 'logStreams[0].logStreamName' --output text --region $REGION)"
echo ""
echo "  aws logs get-log-events \\"
echo "    --log-group-name /aws/lambda/daily-brief \\"
echo "    --log-stream-name \"\$STREAM\" --region $REGION \\"
echo "    | grep -i 'AI-3\\|validator\\|WARN.*ai_output'"
echo ""
echo "✅ Item 1 complete."
