#!/bin/bash
# ============================================================
#  CloudTrail setup — management events only (free tier)
#  Logs to existing S3 bucket: matthew-life-platform/cloudtrail/
# ============================================================

set -e

TRAIL_NAME="life-platform-trail"
BUCKET="matthew-life-platform"
PREFIX="cloudtrail"
REGION="us-west-2"
ACCOUNT_ID="205930651321"

echo ""
echo "=== Setting up CloudTrail ==="
echo "Trail:  $TRAIL_NAME"
echo "Bucket: s3://$BUCKET/$PREFIX/"
echo ""

# ── Step 1: Add CloudTrail bucket policy ──────────────────────────────────────
echo "[1/4] Applying S3 bucket policy for CloudTrail..."

# Fetch existing policy (if any) and merge — for now we set fresh
POLICY=$(cat << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudtrail.amazonaws.com"
      },
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::$BUCKET",
      "Condition": {
        "StringEquals": {
          "aws:SourceArn": "arn:aws:cloudtrail:$REGION:$ACCOUNT_ID:trail/$TRAIL_NAME"
        }
      }
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudtrail.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$BUCKET/$PREFIX/AWSLogs/$ACCOUNT_ID/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control",
          "aws:SourceArn": "arn:aws:cloudtrail:$REGION:$ACCOUNT_ID:trail/$TRAIL_NAME"
        }
      }
    }
  ]
}
EOF
)

aws s3api put-bucket-policy \
  --bucket "$BUCKET" \
  --policy "$POLICY" \
  --region "$REGION"

echo "  ✓ Bucket policy applied"

# ── Step 2: Create trail ──────────────────────────────────────────────────────
echo "[2/4] Creating trail..."

aws cloudtrail create-trail \
  --name "$TRAIL_NAME" \
  --s3-bucket-name "$BUCKET" \
  --s3-key-prefix "$PREFIX" \
  --no-include-global-service-events \
  --no-is-multi-region-trail \
  --enable-log-file-validation \
  --region "$REGION" > /dev/null

echo "  ✓ Trail created: $TRAIL_NAME"

# ── Step 3: Start logging ─────────────────────────────────────────────────────
echo "[3/4] Starting logging..."

aws cloudtrail start-logging \
  --name "$TRAIL_NAME" \
  --region "$REGION"

echo "  ✓ Logging started"

# ── Step 4: Verify ───────────────────────────────────────────────────────────
echo "[4/4] Verifying..."

aws cloudtrail get-trail-status \
  --name "$TRAIL_NAME" \
  --region "$REGION" \
  --query "{IsLogging:IsLogging,LatestDeliveryError:LatestDeliveryError}" \
  --output table

echo ""
echo "=== Done ==="
echo ""
echo "Logs will appear in:"
echo "  s3://$BUCKET/$PREFIX/AWSLogs/$ACCOUNT_ID/CloudTrail/$REGION/YYYY/MM/DD/"
echo ""
echo "To search logs later:"
echo "  aws cloudtrail lookup-events --region $REGION --lookup-attributes AttributeKey=EventSource,AttributeValue=lambda.amazonaws.com"
