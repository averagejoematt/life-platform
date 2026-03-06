#!/bin/bash
# Deploy Daily Brief v2.77.0 — Monolith extraction (html_builder, ai_calls, output_writers)
# Packages: lambda_function.py + scoring_engine.py + board_loader.py +
#           html_builder.py + ai_calls.py + output_writers.py
set -e

LAMBDA_NAME="daily-brief"
REGION="us-west-2"
LAMBDAS_DIR="$HOME/Documents/Claude/life-platform/lambdas"
DEPLOY_DIR="$HOME/Documents/Claude/life-platform/deploy"
ZIP_PATH="$DEPLOY_DIR/daily_brief_v2.77.0.zip"

echo "=== Daily Brief v2.77.0 Deploy ==="
echo "Packaging 6 files into zip..."

cd "$LAMBDAS_DIR"

# Build zip — lambda_function.py is the entry point
zip -j "$ZIP_PATH" \
    daily_brief_lambda.py \
    scoring_engine.py \
    board_loader.py \
    html_builder.py \
    ai_calls.py \
    output_writers.py

# Rename entry point inside zip to what Lambda expects
cd "$DEPLOY_DIR"
python3 - <<'PYEOF'
import zipfile, os, shutil

src = "daily_brief_v2.77.0.zip"
tmp = "daily_brief_v2.77.0_tmp.zip"

with zipfile.ZipFile(src, "r") as zin:
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "daily_brief_lambda.py":
                item.filename = "lambda_function.py"
            zout.writestr(item, data)

os.replace(tmp, src)
print("Entry point renamed: daily_brief_lambda.py -> lambda_function.py")
PYEOF

echo "Zip contents:"
unzip -l "$ZIP_PATH"

echo ""
echo "Deploying to Lambda: $LAMBDA_NAME..."
aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$ZIP_PATH" \
    --region "$REGION"

echo ""
echo "Waiting 10s for update to propagate..."
sleep 10

echo ""
echo "Running smoke test (dry_run=true)..."
aws lambda invoke \
    --function-name "$LAMBDA_NAME" \
    --region "$REGION" \
    --log-type Tail \
    --payload '{"dry_run": true}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/daily_brief_response.json \
    --query 'LogResult' \
    --output text | base64 --decode | tail -30

echo ""
echo "Response:"
cat /tmp/daily_brief_response.json

echo ""
echo "=== Deploy complete: daily-brief v2.77.0 ==="
