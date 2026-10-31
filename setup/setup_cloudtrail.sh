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

# ── Step 1: Apply the bucket policy FROM THE REPO'S SOURCE OF TRUTH ─────────────
# #5512 (2026-10-31): this step used to write its own inline policy — a hand-maintained
# TWIN of deploy/bucket_policy.json holding only the two CloudTrail statements, while the
# repo file held only the public-read + delete-protection statements. `put-bucket-policy`
# REPLACES the whole document, so whichever document was applied last silently dropped the
# other's statements: the repo file was applied on 2026-07-08 and CloudTrail delivered
# nothing (AccessDenied, retried every few minutes) for 115 days. Both statement sets now
# live in deploy/bucket_policy.json and this script applies THAT file verbatim
# (tests/test_cloudtrail_delivery_deadman_5512.py pins both halves and bans an inline
# policy literal here — the INCIDENT_LOG 2026-08-30 twin-document class).
echo "[1/4] Applying S3 bucket policy from deploy/bucket_policy.json (public-read + delete-protection + CloudTrail)..."

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POLICY_FILE="$REPO_ROOT/deploy/bucket_policy.json"

if ! grep -q '"AWSCloudTrailWrite"' "$POLICY_FILE"; then
  echo "  ✗ $POLICY_FILE carries no AWSCloudTrailWrite statement — refusing to apply a policy that would keep CloudTrail dark" >&2
  exit 1
fi

aws s3api put-bucket-policy \
  --bucket "$BUCKET" \
  --policy "file://$POLICY_FILE" \
  --region "$REGION"

echo "  ✓ Bucket policy applied"

# ── Step 2: Create trail ──────────────────────────────────────────────────────
echo "[2/4] Creating trail..."

aws cloudtrail create-trail \
  --name "$TRAIL_NAME" \
  --s3-bucket-name "$BUCKET" \
  --s3-key-prefix "$PREFIX" \
  --include-global-service-events \
  --is-multi-region-trail \
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
