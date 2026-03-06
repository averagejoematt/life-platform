#!/bin/bash
# deploy_character_sheet_phase3.sh — Character Sheet Phase 3: Visual Layer
# v2.64.0
#
# Deploys:
#   1. Wednesday Chronicle Lambda — character_sheet data + Elena narrative hooks
#   2. Daily Brief Lambda — avatar data contract in dashboard + buddy JSON
#   3. Dashboard — avatar UI (programmatic SVG placeholder + badge constellation)
#   4. Buddy Page — compact avatar in character sheet tile
#
# Run from: ~/Documents/Claude/life-platform/

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="us-west-2"
BUCKET="matthew-life-platform"

echo "=== Character Sheet Phase 3: Visual Layer (v2.64.0) ==="
echo ""
echo "Changes:"
echo "  1. Chronicle: character_sheet fetch + data packet section + Elena prompt guidance"
echo "  2. Daily Brief: _build_avatar_data() + avatar in dashboard/buddy JSON"
echo "  3. Dashboard: programmatic SVG avatar with tier aura, body frame, badge constellation"
echo "  4. Buddy Page: compact SVG avatar between header and pillar bars"
echo ""

# ═══════════════════════════════════════════════════════════════════
# [1/6] Deploy Wednesday Chronicle Lambda
# ═══════════════════════════════════════════════════════════════════
echo "[1/6] Packaging Wednesday Chronicle Lambda..."
cd "$ROOT/lambdas"
rm -f wednesday_chronicle.zip
zip wednesday_chronicle.zip wednesday_chronicle_lambda.py board_loader.py
echo "  ✓ Zip: $(du -h wednesday_chronicle.zip | cut -f1)"

echo "  Deploying..."
aws lambda update-function-code \
  --function-name "wednesday-chronicle" \
  --zip-file "fileb://wednesday_chronicle.zip" \
  --region "$REGION" \
  --no-cli-pager > /dev/null
echo "  ✓ wednesday-chronicle Lambda updated"

# Wait for propagation
sleep 10

# ═══════════════════════════════════════════════════════════════════
# [2/6] Deploy Daily Brief Lambda
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "[2/6] Packaging Daily Brief Lambda..."
TMP_DIR=$(mktemp -d)
cp "$ROOT/lambdas/daily_brief_lambda.py" "$TMP_DIR/lambda_function.py"
if [ -f "$ROOT/lambdas/board_loader.py" ]; then
  cp "$ROOT/lambdas/board_loader.py" "$TMP_DIR/"
fi
(cd "$TMP_DIR" && zip -j "$ROOT/lambdas/daily_brief_lambda.zip" ./*)
rm -rf "$TMP_DIR"
echo "  ✓ Zip: $(du -h "$ROOT/lambdas/daily_brief_lambda.zip" | cut -f1)"

echo "  Deploying..."
aws lambda update-function-code \
  --function-name "daily-brief" \
  --zip-file "fileb://$ROOT/lambdas/daily_brief_lambda.zip" \
  --region "$REGION" \
  --no-cli-pager > /dev/null
echo "  ✓ daily-brief Lambda updated"

# Wait for propagation
sleep 10

# ═══════════════════════════════════════════════════════════════════
# [3/6] Deploy Dashboard
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "[3/6] Uploading dashboard..."
aws s3 cp "$ROOT/lambdas/dashboard/index.html" "s3://$BUCKET/dashboard/index.html" \
  --content-type "text/html" \
  --cache-control "max-age=300"
echo "  ✓ Dashboard uploaded"

# ═══════════════════════════════════════════════════════════════════
# [4/6] Deploy Buddy Page
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "[4/6] Uploading buddy page..."
aws s3 cp "$ROOT/lambdas/buddy/index.html" "s3://$BUCKET/buddy/index.html" \
  --content-type "text/html" \
  --cache-control "max-age=300"
echo "  ✓ Buddy page uploaded"

# ═══════════════════════════════════════════════════════════════════
# [5/6] Invalidate CloudFront caches
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "[5/6] Invalidating CloudFront caches..."

DASH_DIST=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Aliases.Items, 'dash.averagejoematt.com')].Id" --output text 2>/dev/null || echo "")
if [ -n "$DASH_DIST" ] && [ "$DASH_DIST" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$DASH_DIST" --paths "/index.html" > /dev/null
  echo "  ✓ Dashboard CloudFront invalidated"
fi

BUDDY_DIST=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Aliases.Items, 'buddy.averagejoematt.com')].Id" --output text 2>/dev/null || echo "")
if [ -n "$BUDDY_DIST" ] && [ "$BUDDY_DIST" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$BUDDY_DIST" --paths "/index.html" > /dev/null
  echo "  ✓ Buddy CloudFront invalidated"
fi

# ═══════════════════════════════════════════════════════════════════
# [6/6] Verify
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "[6/6] Verifying deployments..."
sleep 3

echo "  Chronicle:"
aws lambda get-function-configuration \
  --function-name "wednesday-chronicle" \
  --region "$REGION" \
  --query '{LastModified: LastModified, CodeSize: CodeSize}' \
  --no-cli-pager

echo "  Daily Brief:"
aws lambda get-function-configuration \
  --function-name "daily-brief" \
  --region "$REGION" \
  --query '{LastModified: LastModified, CodeSize: CodeSize}' \
  --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Character Sheet Phase 3 deployed (v2.64.0)"
echo ""
echo "What was deployed:"
echo "  🔄 Chronicle Lambda — character_sheet in data packet + Elena guidance"
echo "  🔄 Daily Brief Lambda — avatar data contract in dashboard/buddy JSON"
echo "  🎮 Dashboard — SVG avatar with tier aura, body frame, badges"
echo "  🎮 Buddy Page — compact SVG avatar in character sheet tile"
echo ""
echo "Verification:"
echo "  1. Dashboard: https://dash.averagejoematt.com"
echo "     → After tomorrow's 10 AM brief, avatar should render in Character Sheet tile"
echo "  2. Buddy:    https://buddy.averagejoematt.com"
echo "     → Avatar will appear above pillar bars"
echo "  3. Chronicle: Next Wednesday's email will include Character Sheet section"
echo ""
echo "Note: Avatar is a programmatic SVG placeholder. Real pixel art sprites"
echo "      will replace it once generated and uploaded to S3."
echo "═══════════════════════════════════════════════════════════════"
