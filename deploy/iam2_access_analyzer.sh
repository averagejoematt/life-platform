#!/usr/bin/env bash
# IAM-2: Enable IAM Access Analyzer for the life-platform AWS account
# Free service — identifies unused permissions, external access, and over-broad policies.
# Run once; idempotent (will error harmlessly if analyzer already exists).

set -euo pipefail

REGION="us-west-2"
ANALYZER_NAME="life-platform-analyzer"

echo "=== IAM-2: Creating IAM Access Analyzer ==="

aws accessanalyzer create-analyzer \
  --analyzer-name "$ANALYZER_NAME" \
  --type ACCOUNT \
  --region "$REGION" && echo "✅ Analyzer created: $ANALYZER_NAME" \
  || echo "ℹ️  Analyzer may already exist (check below)"

echo ""
echo "View findings in the AWS Console:"
echo "  https://us-west-2.console.aws.amazon.com/access-analyzer/home?region=us-west-2"
echo ""
echo "Or via CLI:"
echo "  aws accessanalyzer list-findings --analyzer-name $ANALYZER_NAME --region $REGION"
