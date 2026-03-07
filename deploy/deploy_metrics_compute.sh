#!/bin/bash
# Deploy daily-metrics-compute Lambda
# Usage: bash deploy/deploy_metrics_compute.sh

set -e
WORK_DIR=$(mktemp -d)
cp lambdas/daily_metrics_compute_lambda.py "$WORK_DIR/lambda_function.py"
cp lambdas/scoring_engine.py "$WORK_DIR/scoring_engine.py" 2>/dev/null || true
(cd "$WORK_DIR" && zip -q deploy.zip lambda_function.py scoring_engine.py 2>/dev/null || zip -q deploy.zip lambda_function.py)
aws lambda update-function-code \
  --function-name daily-metrics-compute \
  --zip-file "fileb://$WORK_DIR/deploy.zip" \
  --region us-west-2 \
  --no-cli-pager
rm -rf "$WORK_DIR"
echo "✅ daily-metrics-compute deployed"
