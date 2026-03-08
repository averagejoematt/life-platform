#!/bin/bash
# item2_wire_ingestion_validator.sh — DATA-2: Wire ingestion_validator into whoop, strava, macrofactor
#
# ingestion_validator.py is already in the Layer (added via item1 or manually).
# This script deploys the 3 Lambdas that now import it.

set -euo pipefail

echo "═══ Item 2: Wire Ingestion Validator ═══"
echo "  Lambdas: whoop, strava, macrofactor"
echo ""

echo "Deploying whoop Lambda..."
bash deploy/deploy_unified.sh whoop
echo "  ✅ whoop deployed"

sleep 10

echo "Deploying strava Lambda..."
bash deploy/deploy_unified.sh strava
echo "  ✅ strava deployed"

sleep 10

echo "Deploying macrofactor Lambda..."
bash deploy/deploy_unified.sh macrofactor
echo "  ✅ macrofactor deployed"

echo ""
echo "═══ Verification ═══"
echo "After next scheduled ingestion run (6 AM PT), check for [DATA-2] entries:"
echo ""
echo "  for FUNC in whoop strava macrofactor; do"
echo "    echo \"--- \$FUNC ---\""
echo "    STREAM=\$(aws logs describe-log-streams \\"
echo "      --log-group-name /aws/lambda/\$FUNC-data-ingestion \\"
echo "      --order-by LastEventTime --descending --limit 1 \\"
echo "      --query 'logStreams[0].logStreamName' --output text --region us-west-2)"
echo "    aws logs get-log-events --log-group-name /aws/lambda/\$FUNC-data-ingestion \\"
echo "      --log-stream-name \"\$STREAM\" --region us-west-2 | grep -i 'DATA-2\\|validator' || echo 'no DATA-2 entries yet'"
echo "  done"
echo ""
echo "⚠️  IMPORTANT: First run will validate real data."
echo "   If valid data is unexpectedly rejected, loosen the schema rule in"
echo "   lambdas/ingestion_validator.py and redeploy — don't remove the validator."
echo ""
echo "✅ Item 2 complete."
