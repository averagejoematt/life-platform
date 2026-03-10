#!/usr/bin/env bash
# deploy_hardening_v3312.sh
# Deploys two Lambdas changed in the v3.3.12 hardening session:
#   1. life-platform-mcp  — auth-failure EMF metric added to handler.py
#   2. daily-insight-compute — TTL added to platform_memory writes
#
# Usage:
#   bash deploy/deploy_hardening_v3312.sh

set -euo pipefail
REGION="us-west-2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== v3.3.12 hardening deploy ==="
echo ""

# ──────────────────────────────────────────────────────────────
# 1. life-platform-mcp — full package deploy (mcp/ subdir structure)
#    deploy_lambda.sh flattens files; MCP needs mcp/ preserved.
# ──────────────────────────────────────────────────────────────
echo "1/2  life-platform-mcp (auth-failure EMF metric)"

WORK_DIR=$(mktemp -d)
cp "$ROOT/mcp_server.py" "$WORK_DIR/mcp_server.py"
cp -r "$ROOT/mcp" "$WORK_DIR/mcp"

(cd "$WORK_DIR" && zip -qr deploy.zip mcp_server.py mcp/)
echo "📦 Packaged mcp_server.py + mcp/ directory"

aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file "fileb://$WORK_DIR/deploy.zip" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --query "LastModified" --output text --no-cli-pager)
echo "✅ Deployed life-platform-mcp (modified: $LAST_MODIFIED)"
rm -rf "$WORK_DIR"

echo "    Waiting 10s before next deploy..."
sleep 10

# ──────────────────────────────────────────────────────────────
# 2. daily-insight-compute — single-file, deploy_lambda.sh handles it
# ──────────────────────────────────────────────────────────────
echo "2/2  daily-insight-compute (platform_memory TTL)"
bash "$SCRIPT_DIR/deploy_lambda.sh" \
    daily-insight-compute \
    lambdas/daily_insight_compute_lambda.py
echo ""

echo "=== Done. Verify in CloudWatch: ==="
echo "  life-platform-mcp:       aws logs tail /aws/lambda/life-platform-mcp --since 5m"
echo "  daily-insight-compute:   aws logs tail /aws/lambda/daily-insight-compute --since 5m"
echo ""
echo "  Auth failure metric: LifePlatform/MCP namespace, EventType=AuthFailure"
