#!/usr/bin/env bash
# deploy_lifecycle_gaps.sh — Fix all 3 lifecycle gaps
# 1. MCP server (overdue detection + catalog_id)
# 2. Site API Lambda (achievements + challenge catalog endpoint)
# 3. Site HTML (achievements page + challenges page)
set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
DIST_ID="E3S424OXQZ8NBE"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Lifecycle Gap Fixes ==="

echo "[1/5] Deploying MCP server (overdue detection + catalog_id)..."
bash "$PROJECT_ROOT/deploy/deploy_lambda.sh" life-platform-mcp-server "$PROJECT_ROOT/mcp_server.py"
echo "  Done"
sleep 10

echo "[2/5] Deploying site-api Lambda (achievements + challenge catalog)..."
bash "$PROJECT_ROOT/deploy/deploy_lambda.sh" life-platform-site-api "$PROJECT_ROOT/lambdas/site_api_lambda.py"
echo "  Done"
sleep 10

echo "[3/5] Syncing site to S3..."
aws s3 sync "$PROJECT_ROOT/site/" "s3://$BUCKET/site/" \
  --region "$REGION" --no-cli-pager \
  --exclude ".DS_Store" --exclude "*.swp"
echo "  Done"

echo "[4/5] Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/achievements/*" "/api/achievements" "/challenges/*" "/api/challenge_catalog" \
  --region us-east-1 --no-cli-pager
echo "  Done"

echo "[5/5] Verifying site-api..."
aws lambda invoke \
  --function-name life-platform-site-api \
  --payload '{"requestContext":{"http":{"method":"GET","path":"/api/achievements"}},"rawPath":"/api/achievements","headers":{}}' \
  --region "$REGION" --no-cli-pager /tmp/ach_test.json
echo "  Achievements endpoint returned $(wc -c < /tmp/ach_test.json) bytes"

echo ""
echo "=== All 3 gaps fixed ==="
echo "Gap 1: list_challenges now flags overdue active challenges"
echo "Gap 2: create_challenge accepts catalog_id for catalog→DDB linkage"
echo "Gap 3: /api/achievements now counts completed challenges + 5 new badges"
echo ""
echo "Verify:"
echo "  https://averagejoematt.com/achievements/"
echo "  https://averagejoematt.com/challenges/"
