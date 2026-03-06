#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Buddy Page Fixes v2.56.0
#
# Fix 1: "For Tom" → "Thank you for looking out for me!" + PST time
# Fix 2: Exercise "12 sessions this week" → deduped + "in the last 7 days"
# Fix 3: Activity dedup (WHOOP+Garmin → Strava duplicates)
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
BUCKET="matthew-life-platform"

echo "═══════════════════════════════════════════════════"
echo "  Buddy Page Fixes v2.56.0"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Upload fixed buddy HTML ──────────────────────────────────────────────
echo "[1/3] Uploading fixed buddy HTML..."
aws s3 cp lambdas/buddy/index.html s3://$BUCKET/buddy/index.html \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --region "$REGION" > /dev/null
echo "  ✓ HTML updated (subtitle + timestamp)"

# ── 2. Deploy Daily Brief Lambda (dedup + text fixes) ──────────────────────
echo ""
echo "[2/3] Packaging Daily Brief Lambda..."
cd lambdas
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✓ Package ready"

echo "Deploying..."
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb://daily_brief_lambda.zip \
    --region "$REGION" > /dev/null
echo "  ✓ Lambda updated: daily-brief"

# ── 3. Wait + regenerate buddy JSON ─────────────────────────────────────────
echo ""
echo "[3/3] Waiting 10s then regenerating buddy JSON..."
sleep 10

aws lambda invoke \
    --function-name daily-brief \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/buddy_fixes_result.json > /dev/null

echo "  ✓ Daily Brief ran"

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "Verifying buddy/data.json..."
aws s3 cp s3://$BUCKET/buddy/data.json /tmp/buddy_verify.json --region "$REGION" 2>/dev/null
python3 -c "
import json
with open('/tmp/buddy_verify.json') as f:
    data = json.load(f)
for s in data.get('status_lines', []):
    emoji = {'green':'🟢','yellow':'🟡','red':'🔴'}.get(s['status'],'⚪')
    print(f'  {emoji} {s[\"area\"]}: {s[\"text\"]}')
print()
print(f'  Beacon: {data.get(\"beacon\")} — {data.get(\"beacon_label\")}')
print(f'  Updated: {data.get(\"last_updated_friendly\", \"?\")}')
highlights = data.get('activity_highlights', [])
if highlights:
    print(f'  Activities: {len(highlights)} shown')
    for a in highlights:
        print(f'    • {a[\"name\"]} ({a[\"detail\"]}) — {a[\"date\"]}')
"

# ── 4. Invalidate CloudFront cache ───────────────────────────────────────────
echo ""
echo "[4/4] Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
    --distribution-id ETTJ44FT0Z4GO \
    --paths "/buddy/*" \
    --region us-east-1 > /dev/null
echo "  ✓ Cache invalidated (takes ~30s to propagate)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ All fixes deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Changes:"
echo "    1. Subtitle: 'Thank you for looking out for me!' + PST time"
echo "    2. Exercise: Mon–Sun weekly count + dedup"
echo "    3. Dedup: WHOOP+Garmin overlaps removed (Garmin preferred)"
echo "    4. CloudFront cache invalidated"
echo ""
echo "  Refresh buddy.averagejoematt.com in ~30s"
echo ""
