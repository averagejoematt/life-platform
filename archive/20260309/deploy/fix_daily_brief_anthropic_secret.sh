#!/bin/bash
# Fix stale ANTHROPIC_SECRET env var on daily-brief Lambda
set -e

FUNCTION_NAME="daily-brief"
REGION="us-west-2"
TMPFILE=$(mktemp /tmp/lambda-env-XXXX.json)

echo "=== Current env vars for $FUNCTION_NAME ==="
aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query 'Environment.Variables' \
  --output json

echo ""
echo "=== Building updated env vars (removing ANTHROPIC_SECRET) ==="
aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query 'Environment.Variables' \
  --output json | python3 -c "
import json, sys
vars = json.load(sys.stdin)
removed = vars.pop('ANTHROPIC_SECRET', None)
if removed:
    print(f'[INFO] Removing ANTHROPIC_SECRET={removed}', file=sys.stderr)
else:
    print('[INFO] ANTHROPIC_SECRET not set — nothing to remove', file=sys.stderr)
print(json.dumps({'Variables': vars}))
" > "$TMPFILE"

cat "$TMPFILE"

echo ""
echo "=== Applying update ==="
aws lambda update-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --environment "file://$TMPFILE" \
  --query '[LastModified, State]' \
  --output text

rm -f "$TMPFILE"

echo ""
echo "=== Verifying ==="
aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query 'Environment.Variables' \
  --output json

echo ""
echo "Done. ANTHROPIC_SECRET removed — code will use default 'life-platform/api-keys'."
echo "To confirm no more WARN logs, check after 10 AM tomorrow or trigger a test invoke."
