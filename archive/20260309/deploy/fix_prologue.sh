#!/bin/bash
# fix_prologue.sh — Fix age and living situation in prologue
set -euo pipefail

echo "=== Fixing prologue (age + Brittany) ==="

# Download current
aws s3 cp s3://matthew-life-platform/blog/week-00.html /tmp/week-00-fix.html

# Fix
sed -i '' 's/Matthew is thirty-five. He lives alone in Seattle./Matthew is thirty-seven. He lives with his girlfriend, Brittany, in Seattle./' /tmp/week-00-fix.html

# Verify
if grep -q "thirty-seven" /tmp/week-00-fix.html; then
  echo "✓ Text fixed"
else
  echo "✗ Fix failed — text not found"
  exit 1
fi

# Re-upload
aws s3 cp /tmp/week-00-fix.html s3://matthew-life-platform/blog/week-00.html \
  --content-type "text/html; charset=utf-8"
echo "✓ Uploaded to S3"

# Invalidate cache
aws cloudfront create-invalidation \
  --distribution-id E1JOC1V6E6DDYI \
  --paths "/week-00.html" \
  --output json | jq '.Invalidation.Id'
echo "✓ CloudFront cache invalidated"

echo ""
echo "Done. Give it 1-2 min for cache to clear, then check:"
echo "  https://d1aufb59hb2r1q.cloudfront.net/week-00.html"

rm -f /tmp/week-00-fix.html
