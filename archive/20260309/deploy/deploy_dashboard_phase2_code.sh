#!/bin/bash
# Dashboard Phase 2 — Code Deploy
# Uploads updated HTML files + deploys weekly digest Lambda with write_clinical_json
# v2.39.0
set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"
LAMBDA_NAME="weekly-digest"
DASHBOARD_DIR="$(dirname "$0")/../lambdas/dashboard"
LAMBDA_DIR="$(dirname "$0")/../lambdas"

echo "╔══════════════════════════════════════════════╗"
echo "║  Dashboard Phase 2 — Code Deploy (v2.39.0)  ║"
echo "╚══════════════════════════════════════════════╝"

# ── Step 1: Upload dashboard HTML files to S3 ──
echo ""
echo "═══ Step 1/3: Upload dashboard HTML to S3 ═══"

echo "  Uploading index.html..."
aws s3 cp "$DASHBOARD_DIR/index.html" "s3://$BUCKET/dashboard/index.html" \
  --content-type "text/html" \
  --cache-control "max-age=300" \
  --region "$REGION"

echo "  Uploading clinical.html..."
aws s3 cp "$DASHBOARD_DIR/clinical.html" "s3://$BUCKET/dashboard/clinical.html" \
  --content-type "text/html" \
  --cache-control "max-age=3600" \
  --region "$REGION"

echo "  ✅ HTML files uploaded"

# ── Step 2: Verify S3 objects ──
echo ""
echo "═══ Step 2/3: Verify S3 objects ═══"

for OBJ in "dashboard/index.html" "dashboard/clinical.html" "dashboard/data.json"; do
  SIZE=$(aws s3api head-object --bucket "$BUCKET" --key "$OBJ" --region "$REGION" \
    --query 'ContentLength' --output text 2>/dev/null || echo "MISSING")
  echo "  $OBJ: $SIZE bytes"
done

# ── Step 3: Deploy Weekly Digest Lambda ──
echo ""
echo "═══ Step 3/3: Deploy Weekly Digest Lambda ═══"

echo "  Creating deployment zip..."
cd "$LAMBDA_DIR"
rm -f weekly_digest_v2_lambda.zip
cp weekly_digest_v2_lambda.py digest_handler.py
zip weekly_digest_v2_lambda.zip digest_handler.py
rm digest_handler.py
echo "  Zip created: $(wc -c < weekly_digest_v2_lambda.zip) bytes"

echo "  Deploying to Lambda..."
aws lambda update-function-code \
  --function-name "$LAMBDA_NAME" \
  --zip-file "fileb://weekly_digest_v2_lambda.zip" \
  --region "$REGION" \
  --query 'LastModified' \
  --output text

echo "  ✅ Weekly Digest Lambda deployed"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅ Code deploy complete!                               ║"
echo "║                                                          ║"
echo "║  Dashboard: http://$BUCKET.s3-website-$REGION.amazonaws.com/dashboard/ ║"
echo "║  Clinical:  .../dashboard/clinical.html                  ║"
echo "║                                                          ║"
echo "║  Clinical JSON will be generated on next Sunday digest.  ║"
echo "║  To test now: aws lambda invoke --function-name          ║"
echo "║    weekly-digest /tmp/wd-out.json --region us-west-2     ║"
echo "║                                                          ║"
echo "║  Next: Run deploy_dashboard_phase2_infra.sh for          ║"
echo "║  CloudFront + custom domain setup.                       ║"
echo "╚══════════════════════════════════════════════════════════╝"
