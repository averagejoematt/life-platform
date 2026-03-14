#!/bin/bash
# apply_s3_lifecycle.sh — Apply S3 lifecycle rule to expire deploy artifacts
#
# Expires objects under deploys/ prefix after 30 days.
# Safe: latest.zip and previous.zip age resets on every deploy.
# Any Lambda not deployed in 30+ days loses its rollback artifact (acceptable).
#
# Run once. Re-run is idempotent (overwrites the rule).
#
# Usage:
#   bash deploy/apply_s3_lifecycle.sh

set -euo pipefail

BUCKET="matthew-life-platform"
RULE_ID="expire-lambda-deploy-artifacts"

echo "Applying S3 lifecycle rule to s3://${BUCKET}/deploys/ ..."

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "'"${RULE_ID}"'",
        "Status": "Enabled",
        "Filter": {
          "Prefix": "deploys/"
        },
        "Expiration": {
          "Days": 30
        }
      }
    ]
  }'

echo ""
echo "Done. Verifying..."
aws s3api get-bucket-lifecycle-configuration --bucket "${BUCKET}" \
  | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
for r in cfg.get('Rules', []):
    print(f\"  Rule: {r['ID']} | Status: {r['Status']} | Prefix: {r.get('Filter',{}).get('Prefix','?')} | Expire: {r.get('Expiration',{}).get('Days','?')} days\")
"
echo ""
echo "Lifecycle rule applied. Objects under deploys/ will expire after 30 days."
