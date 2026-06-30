#!/usr/bin/env bash
#
# deploy_reading_mcp.sh — Phase B (reading engine + MCP tools) deploy
# (ADR-097, Mind pillar). RUN THIS YOURSELF; Claude does not execute deploys.
#
# Phase B adds 8 MCP tools (mcp/tools_reading.py) + the rules-based recommender
# and onboarding (in the reading/ package). The MCP bundle now stages
# lambdas/reading/ as a top-level package (mcp_stack.py) so `from reading import …`
# resolves at runtime — numeric/retry_utils that reading depends on already come
# from the shared layer, so there is **NO shared-layer bump and NO fleet redeploy**.
# Just the MCP stack (the lambda + its warmer).
#
#   cdk diff LifePlatformMcp   — REVIEW (expect only the MCP code-asset re-hash;
#                                no IAM change — mcp_server() already grants table
#                                + index/* CRUD; no layer version change)
#   cdk deploy LifePlatformMcp — ships tools_reading + the staged reading/ package
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${AWS_REGION:-us-west-2}"

echo "═══════════════════════════════════════════════════════════════"
echo " Phase B — reading engine + MCP tools (ADR-097)"
echo "═══════════════════════════════════════════════════════════════"
echo "▶ cdk diff LifePlatformMcp (review the plan)"
echo "  Expect: the MCP Lambda + warmer code asset re-hash only (new bundle now"
echo "  includes mcp/tools_reading.py + the staged reading/ package). NO IAM change"
echo "  (mcp_server role already has table + index/* CRUD), NO layer version change."
( cd "$ROOT/cdk" && npx cdk diff LifePlatformMcp )

read -r -p $'\n  Proceed with cdk deploy LifePlatformMcp? [y/N] ' ans
if [ "${ans:-N}" != "y" ] && [ "${ans:-N}" != "Y" ]; then
  echo "✋ Aborted before deploy."
  exit 0
fi

echo "▶ cdk deploy LifePlatformMcp"
( cd "$ROOT/cdk" && npx cdk deploy LifePlatformMcp --require-approval never )

echo "▶ verify the MCP function is live"
aws lambda get-function --function-name life-platform-mcp --region "$REGION" \
  --query 'Configuration.{Name:FunctionName,State:State,CodeSize:CodeSize,LastUpdateStatus:LastUpdateStatus}' --output table

echo "✅ Phase B deployed. The 8 reading tools (get_reading_shelf, get_reading_recommendation,"
echo "   get_reading_profile, get_reading_history, get_due_recalls, get_reading_track_record,"
echo "   get_constellation, manage_reading) are now live on the MCP server."
