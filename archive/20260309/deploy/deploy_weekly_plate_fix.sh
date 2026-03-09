#!/bin/bash
# Deploy Weekly Plate hallucination fix — tighter Greatest Hits prompt
# Fixes: AI was fabricating meal pairings (e.g., adding quinoa + spinach to ground beef)
set -euo pipefail

echo "=== Deploying Weekly Plate prompt fix ==="

LAMBDA_NAME="weekly-plate"
ZIP_FILE="/tmp/weekly_plate.zip"
SRC="$HOME/Documents/Claude/life-platform/lambdas/weekly_plate_lambda.py"

# 1. Package Lambda
echo "[1/2] Packaging Lambda..."
cd "$(dirname "$SRC")"
cp weekly_plate_lambda.py lambda_function.py
zip -j "$ZIP_FILE" lambda_function.py board_loader.py 2>/dev/null || zip -j "$ZIP_FILE" lambda_function.py
rm lambda_function.py

# 2. Deploy
echo "[2/2] Deploying Lambda..."
aws lambda update-function-code \
  --function-name "$LAMBDA_NAME" \
  --zip-file "fileb://$ZIP_FILE" \
  --query 'LastModified' --output text

echo ""
echo "=== Done! Weekly Plate prompt fix deployed ==="
echo "Changes:"
echo "  - Greatest Hits: AI must use ONLY exact food names from log data"
echo "  - No fabricating meal pairings or side dishes"
echo "  - CRITICAL section renamed to HALLUCINATION PREVENTION"
echo "  - Try This section explicitly marked as the creative zone"
echo ""
echo "Next Friday's email should no longer invent quinoa + spinach combos."
