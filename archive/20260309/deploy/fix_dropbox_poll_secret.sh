#!/bin/bash
# Fix dropbox-poll: update secret key references to match api-keys bundle
set -euo pipefail

REGION="us-west-2"
LAMBDAS_DIR="$(dirname "$0")/../lambdas"

WORK_DIR=$(mktemp -d)
cp "$LAMBDAS_DIR/dropbox_poll_lambda.py" "$WORK_DIR/dropbox_poll_lambda.py"
(cd "$WORK_DIR" && zip -q deploy.zip dropbox_poll_lambda.py)

aws lambda update-function-code \
    --function-name dropbox-poll \
    --zip-file "fileb://$WORK_DIR/deploy.zip" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

echo "✅ dropbox-poll code deployed"

# Quick smoke test
sleep 5
aws lambda invoke \
    --function-name dropbox-poll \
    --region "$REGION" \
    --no-cli-pager \
    "$WORK_DIR/out.json" > /dev/null

cat "$WORK_DIR/out.json"
rm -rf "$WORK_DIR"
