#!/bin/bash
# deploy.command — Deploy mcp_server.py to AWS Lambda
# Double-click in Finder to run, or: bash scripts/deploy.command

set -euo pipefail
cd "$(dirname "$0")/.."   # always run from project root

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="/tmp/mcp_deploy.zip"

echo "════════════════════════════════════════════"
echo "  Life Platform — Deploy"
echo "════════════════════════════════════════════"

# Read version from source
VERSION=$(python3 -c "
import re
src = open('mcp_server.py').read()
m = re.search(r'\"version\": \"([\d.]+)\"', src)
print(m.group(1) if m else 'unknown')
")
echo "  Version detected : $VERSION"
echo ""

# Package
echo "▶ Packaging..."
rm -f "$ZIP_FILE"
zip -j "$ZIP_FILE" mcp_server.py > /dev/null
echo "  ✅ Packaged"

# Deploy
echo "▶ Uploading to Lambda..."
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://$ZIP_FILE" \
  --region "$REGION" > /dev/null

echo "▶ Waiting for update to complete..."
aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION"

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Deployed v$VERSION successfully"
echo "════════════════════════════════════════════"
echo ""
echo "Run scripts/verify.command to confirm."
echo ""
read -p "Press Enter to close..."
