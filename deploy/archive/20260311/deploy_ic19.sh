#!/bin/bash
# deploy_ic19.sh — Deploy all IC-19 modified files
#
# Modified files:
#   1. lambdas/anomaly_detector_lambda.py      — v2.3.0 (sustained streak detection)
#   2. lambdas/daily_insight_compute_lambda.py — IC-2 v1.2.0 (slow drift + IC-19 context)
#   3. lambdas/hypothesis_engine_lambda.py     — v1.2.0 (D3B: Conti framing, experiment XRef)
#   4. mcp/tools_lifestyle.py                  — Cohen's d, Okafor/Norton/Chen board
#
# Note: tools_lifestyle.py is part of the MCP server (mcp_server.py / mcp_bridge.py).
#       It deploys as part of the MCP Lambda, not as a standalone Lambda.
#       Update MCP Lambda with: deploy_lambda.sh life-platform-mcp mcp/mcp_server.py --extra-files ...
#
# Usage: bash deploy/deploy_ic19.sh

set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== IC-19 Deploy ==="
echo ""

echo "1/3 Deploying anomaly-detector (v2.3.0)..."
bash deploy/deploy_lambda.sh anomaly-detector lambdas/anomaly_detector_lambda.py
echo "   ✓ anomaly-detector deployed"
sleep 10

echo "2/3 Deploying daily-insight-compute (IC-2 v1.2.0)..."
bash deploy/deploy_lambda.sh daily-insight-compute lambdas/daily_insight_compute_lambda.py
echo "   ✓ daily-insight-compute deployed"
sleep 10

echo "3/3 Deploying hypothesis-engine (v1.2.0)..."
bash deploy/deploy_lambda.sh hypothesis-engine lambdas/hypothesis_engine_lambda.py
echo "   ✓ hypothesis-engine deployed"

echo ""
echo "=== Lambda deploys complete ==="
echo ""
echo "NOTE: tools_lifestyle.py (MCP changes) requires a separate MCP Lambda deploy."
echo "Run: bash deploy/deploy_lambda.sh <mcp-function-name> mcp/mcp_server.py --extra-files mcp/tools_lifestyle.py ..."
echo "Check your MCP Lambda name with: aws lambda list-functions --query 'Functions[?contains(FunctionName, \`mcp\`)].FunctionName'"
