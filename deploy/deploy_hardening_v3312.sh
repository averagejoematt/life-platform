#!/usr/bin/env bash
# deploy_hardening_v3312.sh
# Deploys two Lambdas changed in the v3.3.12 hardening session:
#   1. life-platform-mcp  — auth-failure EMF metric added to handler.py
#   2. daily-insight-compute — TTL added to platform_memory writes
#
# Usage:
#   bash deploy/deploy_hardening_v3312.sh
#
# Prerequisites: deploy_lambda.sh must be in the same directory and executable.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$SCRIPT_DIR/deploy_lambda.sh"

echo "=== v3.3.12 hardening deploy ==="
echo ""

echo "1/2  life-platform-mcp (auth-failure EMF metric)"
bash "$DEPLOY" life-platform-mcp
echo "    Waiting 10s before next deploy..."
sleep 10

echo "2/2  daily-insight-compute (platform_memory TTL)"
bash "$DEPLOY" daily-insight-compute
echo ""

echo "=== Done. Verify in CloudWatch: ==="
echo "  life-platform-mcp:        aws logs tail /aws/lambda/life-platform-mcp --since 5m"
echo "  daily-insight-compute:    aws logs tail /aws/lambda/daily-insight-compute --since 5m"
echo ""
echo "  Auth failure metric appears in LifePlatform/MCP namespace (EventType=AuthFailure)"
echo "  after any 401 rejection — trigger a test with a bad Bearer token if you want"
echo "  to verify immediately."
