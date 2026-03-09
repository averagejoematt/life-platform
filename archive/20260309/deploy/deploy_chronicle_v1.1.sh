#!/bin/bash
# deploy_chronicle_v1.1.sh — Deploy updated Wednesday Chronicle Lambda + blog homepage
# Changes:
#   1. Elena's system prompt: synthesis over recounting, no day-by-day
#   2. Editorial guidance in user message
#   3. Age fix (37, lives with Brittany)
#   4. Redesigned blog homepage with hero/featured layout
#   5. Updated build_blog_index for future installments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$ROOT_DIR/lambdas"
FUNC_NAME="wednesday-chronicle"
REGION="us-west-2"

echo "=== Deploy Wednesday Chronicle v1.1 ==="
echo ""

# [1/4] Deploy updated Lambda
echo "[1/4] Packaging Lambda..."
cd "$LAMBDA_DIR"
rm -f wednesday_chronicle.zip
zip wednesday_chronicle.zip wednesday_chronicle_lambda.py
echo "  ✓ Zip: $(du -h wednesday_chronicle.zip | cut -f1)"

echo ""
echo "[2/4] Updating Lambda function..."
aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file "fileb://wednesday_chronicle.zip" \
  --region "$REGION" \
  --output json | jq '{FunctionName, CodeSize, LastModified}'
echo "  ✓ Lambda updated"

# [3/4] Upload new blog homepage
echo ""
echo "[3/4] Uploading redesigned blog homepage..."
aws s3 cp "$ROOT_DIR/blog/index.html" s3://matthew-life-platform/blog/index.html \
  --content-type "text/html; charset=utf-8"
echo "  ✓ Homepage uploaded"

# [4/4] Invalidate CloudFront cache
echo ""
echo "[4/4] Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
  --distribution-id E1JOC1V6E6DDYI \
  --paths "/index.html" "/week-00.html" \
  --output json | jq '.Invalidation.Id'
echo "  ✓ Cache invalidation started"

echo ""
echo "==========================================="
echo "  ✓ Wednesday Chronicle v1.1 deployed!"
echo "==========================================="
echo ""
echo "  Changes:"
echo "    • Elena's voice: synthesis over day-by-day recounting"
echo "    • Age/bio fix: 37, lives with Brittany"
echo "    • Blog homepage: hero layout, clear read CTA"
echo "    • build_blog_index: featured latest + archive list"
echo ""
echo "  Blog: https://blog.averagejoematt.com"
echo "  Next fire: Wednesday 7:00 AM PT"
