#!/usr/bin/env bash
# COST-1: Add S3 lifecycle rule — raw/ objects >90 days → Glacier Instant Retrieval
# Estimated savings: ~$0.50–$1.50/month once raw/ accumulates
# Run once; idempotent (replaces lifecycle config each time)

set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== COST-1: Setting S3 lifecycle rule on s3://$BUCKET/raw/ ==="

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" \
  --region "$REGION" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "raw-to-glacier-instant-90d",
        "Status": "Enabled",
        "Filter": {
          "Prefix": "raw/"
        },
        "Transitions": [
          {
            "Days": 90,
            "StorageClass": "GLACIER_IR"
          }
        ]
      }
    ]
  }'

echo "✅ Lifecycle rule applied."
echo ""
echo "Verify with:"
echo "  aws s3api get-bucket-lifecycle-configuration --bucket $BUCKET --region $REGION"
