#!/bin/bash
# item3_wire_platform_logger.sh — OBS-1: Wire platform_logger into daily-brief
#
# platform_logger.py is now in the Layer (items 1+2 already added to Layer).
# This just deploys daily-brief to pick up the new import + set_date call.
#
# Verification: CloudWatch logs will emit JSON lines with correlation_id field.

set -euo pipefail

echo "═══ Item 3: Wire Platform Logger into daily-brief ═══"
echo ""
echo "Deploying daily-brief Lambda..."
bash deploy/deploy_unified.sh daily-brief
echo "  ✅ daily-brief deployed"

echo ""
echo "═══ Verification ═══"
echo "After next Daily Brief fires (or invoke manually), check for JSON log lines:"
echo ""
echo "  STREAM=\$(aws logs describe-log-streams \\"
echo "    --log-group-name /aws/lambda/daily-brief \\"
echo "    --order-by LastEventTime --descending --limit 1 \\"
echo "    --query 'logStreams[0].logStreamName' --output text --region us-west-2)"
echo ""
echo "  aws logs get-log-events \\"
echo "    --log-group-name /aws/lambda/daily-brief \\"
echo "    --log-stream-name \"\$STREAM\" --region us-west-2 \\"
echo "    | grep 'correlation_id'"
echo ""
echo "  # CWL Insights query to verify (replace date):"
echo "  # filter correlation_id like '2026-03-08' | sort @timestamp asc"
echo ""
echo "NOTE: Existing print() statements still work. platform_logger is additive."
echo "      Incremental migration of print() -> logger.info() can happen over time."
echo ""
echo "✅ Item 3 complete."
