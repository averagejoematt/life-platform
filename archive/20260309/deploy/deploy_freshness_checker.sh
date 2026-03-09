#!/bin/bash
set -e
cd "$(dirname "$0")/.."
echo "=== Deploy Freshness Checker (remove Hevy, add garmin+habitify) ==="
cd lambdas
cp freshness_checker_lambda.py lambda_function.py
zip -j freshness_checker.zip lambda_function.py
rm lambda_function.py
aws lambda update-function-code \
    --function-name life-platform-freshness-checker \
    --zip-file fileb://freshness_checker.zip \
    --region us-west-2 \
    --query "LastModified"
echo "=== Done ==="
