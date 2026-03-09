#!/bin/bash
# logs.command — Tail recent CloudWatch logs for the MCP Lambda
# Double-click in Finder to run, or: bash scripts/logs.command

set -euo pipefail
cd "$(dirname "$0")/.."

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"
LINES=75

echo "════════════════════════════════════════════"
echo "  Life Platform — Recent Logs"
echo "  Function : $FUNCTION_NAME"
echo "════════════════════════════════════════════"
echo ""

# Get the most recent log stream
echo "▶ Finding latest log stream..."
STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP" \
  --region "$REGION" \
  --order-by LastEventTime \
  --descending \
  --max-items 1 \
  --query "logStreams[0].logStreamName" \
  --output text)

echo "  Stream: $STREAM"
echo ""
echo "▶ Last $LINES log events:"
echo "────────────────────────────────────────────"

aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$STREAM" \
  --region "$REGION" \
  --limit "$LINES" \
  --query "events[*].message" \
  --output text | tr '\t' '\n'

echo ""
echo "────────────────────────────────────────────"
echo ""
echo "Tip: Run again to refresh. For live tailing:"
echo "  aws logs tail $LOG_GROUP --follow --region $REGION"
echo ""
read -p "Press Enter to close..."
