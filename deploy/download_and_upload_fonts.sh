#!/bin/bash
# deploy/download_and_upload_fonts.sh
# WR-21: Self-host Google Fonts — download woff2 files and upload to S3.
# Sends a modern browser User-Agent so Google returns actual woff2 files.
#
# Run once from the project root. Requires curl + awscli.
# Usage: bash deploy/download_and_upload_fonts.sh

set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
FONT_DIR="site/assets/fonts"
S3_PREFIX="site/assets/fonts"

# Modern Chrome UA — required to get woff2 from Google Fonts (not HTML error pages)
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

mkdir -p "$FONT_DIR"

echo "=== Step 1: Fetch Google Fonts CSS to get live woff2 URLs ==="

# Fetch the CSS file that contains the actual woff2 URLs for each variant
CSS=$(curl -sL \
  -H "User-Agent: $UA" \
  "https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Mono:ital,wght@0,400;0,700;1,400;1,700&family=Lora:ital,wght@0,400;0,600;1,400;1,600&display=swap")

echo "   CSS fetched ($(echo "$CSS" | wc -c) bytes)"

# Extract all woff2 URLs
URLS=$(echo "$CSS" | grep -o 'https://fonts.gstatic.com[^)]*\.woff2')
echo "   Found $(echo "$URLS" | wc -l | tr -d ' ') woff2 URLs"

echo ""
echo "=== Step 2: Download font files ==="

# Download each unique URL, name by font+weight detected from CSS context
while IFS= read -r url; do
  # Get the filename from the URL's last path component (hash-named)
  hash=$(echo "$url" | sed 's|.*/||')
  # Download with browser UA
  curl -sL -H "User-Agent: $UA" "$url" -o "$FONT_DIR/$hash"
  size=$(wc -c < "$FONT_DIR/$hash")
  echo "   $hash — ${size} bytes"
done <<< "$URLS"

echo ""
echo "=== Step 3: Rename to human-readable names ==="
# Map hash filenames to readable names using CSS context
# Parse each @font-face block and extract family+style+weight+url

python3 - "$FONT_DIR" "$CSS" << 'PYEOF'
import sys, re, os, shutil

font_dir = sys.argv[1]
css = sys.argv[2]

# Parse @font-face blocks
blocks = re.split(r'@font-face\s*\{', css)[1:]

renamed = {}
for block in blocks:
    family_m = re.search(r"font-family:\s*'([^']+)'", block)
    weight_m = re.search(r'font-weight:\s*(\d+)', block)
    style_m  = re.search(r'font-style:\s*(normal|italic)', block)
    url_m    = re.search(r'url\((https://fonts\.gstatic\.com[^)]+\.woff2)\)', block)

    if not (family_m and weight_m and url_m):
        continue

    family = family_m.group(1).lower().replace(' ', '-')
    weight = weight_m.group(1)
    style  = style_m.group(1) if style_m else 'normal'
    url    = url_m.group(1)
    hash_  = url.split('/')[-1]

    suffix = weight
    if style == 'italic':
        suffix += 'italic'

    readable = f"{family}-{suffix}.woff2"
    src = os.path.join(font_dir, hash_)
    dst = os.path.join(font_dir, readable)

    if os.path.exists(src) and readable not in renamed:
        shutil.copy2(src, dst)
        renamed[readable] = hash_
        print(f"   {hash_} -> {readable}")

print(f"\n   Renamed {len(renamed)} font files")

# Clean up hash-named files
for f in os.listdir(font_dir):
    if f not in renamed.values() and not any(f == k for k in renamed):
        path = os.path.join(font_dir, f)
        if os.path.isfile(path) and not f.endswith('.woff2') or (f.endswith('.woff2') and re.match(r'^[A-Za-z0-9_-]{20,}\.woff2$', f)):
            os.remove(path)
PYEOF

echo ""
echo "=== Step 4: Verify =="
ls -lh "$FONT_DIR/"*.woff2 2>/dev/null | awk '{print "   " $5 "\t" $9}'

echo ""
echo "=== Step 5: Upload to S3 ==="
aws s3 sync "$FONT_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --region "$REGION" \
  --content-type "font/woff2" \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*" \
  --include "*.woff2" \
  --no-cli-pager

echo ""
echo "✅ Fonts uploaded to s3://$BUCKET/$S3_PREFIX/"
echo "   Run 'bash deploy/deploy_site_all.sh' to deploy the updated base.css."
