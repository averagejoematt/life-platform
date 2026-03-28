#!/usr/bin/env bash
# DB-22: Download Barlow Condensed 600 woff2 and upload to S3
# Usage: bash deploy/download_barlow_condensed.sh

set -euo pipefail
cd "$(dirname "$0")/.."

FONT_DIR="site/assets/fonts"
FONT_FILE="barlow-condensed-600.woff2"
S3_BUCKET="matthew-life-platform"

echo "📥 Downloading Barlow Condensed 600 woff2..."

# Google Fonts serves woff2 when User-Agent indicates modern browser
curl -sL -o "$FONT_DIR/$FONT_FILE" \
  "https://fonts.gstatic.com/s/barlowcondensed/v12/HTxxL3I-JCGChYJ8VI-L6OO_au7B46r2z3bWuYMBYgo.woff2"

if [ ! -s "$FONT_DIR/$FONT_FILE" ]; then
  echo "❌ Download failed or file is empty. Trying alternate URL..."
  # Alternate: extract from Google Fonts CSS
  CSS_URL="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600&display=swap"
  WOFF2_URL=$(curl -sL -H "User-Agent: Mozilla/5.0 (Macintosh)" "$CSS_URL" | grep -oP 'url\(\K[^)]+\.woff2' | head -1)
  if [ -n "$WOFF2_URL" ]; then
    curl -sL -o "$FONT_DIR/$FONT_FILE" "$WOFF2_URL"
  fi
fi

if [ -s "$FONT_DIR/$FONT_FILE" ]; then
  SIZE=$(wc -c < "$FONT_DIR/$FONT_FILE" | tr -d ' ')
  echo "✅ Downloaded $FONT_FILE ($SIZE bytes)"
else
  echo "❌ Failed to download font. Download manually from:"
  echo "   https://fonts.google.com/specimen/Barlow+Condensed"
  echo "   Select weight 600, download woff2, save as $FONT_DIR/$FONT_FILE"
  exit 1
fi

echo ""
echo "📤 Uploading to S3..."
aws s3 cp "$FONT_DIR/$FONT_FILE" "s3://$S3_BUCKET/assets/fonts/$FONT_FILE" \
  --content-type "font/woff2" \
  --cache-control "max-age=31536000,immutable"

echo "✅ Font uploaded to S3"
echo ""
echo "📤 Syncing updated CSS..."
aws s3 cp site/assets/css/tokens.css "s3://$S3_BUCKET/assets/css/tokens.css" --content-type "text/css"
aws s3 cp site/assets/css/base.css "s3://$S3_BUCKET/assets/css/base.css" --content-type "text/css"

echo ""
echo "🔄 Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/assets/css/*" "/assets/fonts/*"

echo ""
echo "✅ DB-22 complete — Barlow Condensed 600 live"
echo "   Hard refresh the site to see the change."
