#!/bin/bash
# Deploy weekly_digest_lambda.py v3.2.0
set -e

FUNCTION_NAME="weekly-digest"
FILE="weekly_digest_lambda.py"
ZIP="weekly_digest_lambda.zip"

echo "==> Zipping $FILE..."
zip -j "$ZIP" "$FILE"

echo "==> Uploading to Lambda..."
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://$ZIP" \
  --region us-west-2

echo "==> Waiting for update to complete..."
aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" \
  --region us-west-2

echo "==> Done. Verifying deployed version..."
aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region us-west-2 \
  --query "LastModified"

echo ""
echo "✅ weekly-digest v3.2.0 deployed."
echo ""
echo "Smoke test — invoke now:"
echo "  aws lambda invoke --function-name weekly-digest --region us-west-2 /tmp/digest_out.json && cat /tmp/digest_out.json"
