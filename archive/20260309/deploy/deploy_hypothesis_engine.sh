#!/bin/bash
# deploy_hypothesis_engine.sh — Deploy IC-18 hypothesis-engine Lambda + EventBridge
# Steps 3-4 from deploy_ic7_ic18.sh (steps 1-2 already deployed successfully)
set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
LAMBDA_ROLE="arn:aws:iam::${ACCOUNT}:role/lambda-weekly-digest-role"
TABLE="life-platform"
S3_BUCKET="matthew-life-platform"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDA_DIR="${PROJECT_ROOT}/lambdas"

echo "=== Deploying hypothesis-engine Lambda (IC-18) ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: hypothesis-engine Lambda
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [1/2] Deploying hypothesis-engine Lambda..."

HYPO_DIR=$(mktemp -d)
cp "${LAMBDA_DIR}/hypothesis_engine_lambda.py" "${HYPO_DIR}/hypothesis_engine_lambda.py"
cd "${HYPO_DIR}"
zip -q hypothesis_engine.zip hypothesis_engine_lambda.py
cd "${PROJECT_ROOT}"

if aws lambda get-function --function-name hypothesis-engine --region "${REGION}" &>/dev/null; then
    echo "    Updating existing hypothesis-engine Lambda..."
    aws lambda update-function-code \
        --function-name hypothesis-engine \
        --zip-file "fileb://${HYPO_DIR}/hypothesis_engine.zip" \
        --region "${REGION}" \
        --output text --query 'FunctionName' > /dev/null
    sleep 5
    aws lambda update-function-configuration \
        --function-name hypothesis-engine \
        --timeout 120 \
        --memory-size 256 \
        --environment "Variables={TABLE_NAME=${TABLE},S3_BUCKET=${S3_BUCKET},USER_ID=matthew,ANTHROPIC_SECRET=life-platform/api-keys}" \
        --region "${REGION}" \
        --output text --query 'FunctionName' > /dev/null
else
    echo "    Creating new hypothesis-engine Lambda..."
    aws lambda create-function \
        --function-name hypothesis-engine \
        --runtime python3.12 \
        --role "${LAMBDA_ROLE}" \
        --handler hypothesis_engine_lambda.lambda_handler \
        --zip-file "fileb://${HYPO_DIR}/hypothesis_engine.zip" \
        --timeout 120 \
        --memory-size 256 \
        --environment "Variables={TABLE_NAME=${TABLE},S3_BUCKET=${S3_BUCKET},USER_ID=matthew,ANTHROPIC_SECRET=life-platform/api-keys}" \
        --region "${REGION}" \
        --output text --query 'FunctionName' > /dev/null
fi

rm -rf "${HYPO_DIR}"
echo "    ✅ hypothesis-engine deployed. Waiting 10s..."
sleep 10

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: EventBridge rule — Sunday 11 AM PT (19:00 UTC)
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [2/2] Setting up EventBridge schedule (Sunday 11 AM PT)..."

RULE_NAME="hypothesis-engine-weekly"
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:hypothesis-engine"

aws events put-rule \
    --name "${RULE_NAME}" \
    --schedule-expression "cron(0 19 ? * SUN *)" \
    --state ENABLED \
    --description "IC-18 Hypothesis Engine — Sunday 11 AM PT / 19:00 UTC" \
    --region "${REGION}" \
    --output text --query 'RuleArn' > /dev/null

aws events put-targets \
    --rule "${RULE_NAME}" \
    --targets "Id=hypothesis-engine-target,Arn=${LAMBDA_ARN}" \
    --region "${REGION}" \
    --output text --query 'FailedEntryCount' > /dev/null

aws lambda add-permission \
    --function-name hypothesis-engine \
    --statement-id "allow-eventbridge-hypothesis-engine" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "${REGION}" \
    --output text --query 'Statement' > /dev/null 2>&1 || \
    echo "    (EventBridge permission already exists)"

echo "    ✅ EventBridge rule created: ${RULE_NAME} (Sunday 11 AM PT)"

# ─────────────────────────────────────────────────────────────────────────────
# VERIFY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== VERIFICATION ==="

echo ""
echo "--- hypothesis-engine Lambda state ---"
aws lambda get-function-configuration \
    --function-name hypothesis-engine \
    --region "${REGION}" \
    --query '[State, LastUpdateStatus, Timeout, MemorySize]' \
    --output json

echo ""
echo "--- EventBridge rule ---"
aws events describe-rule \
    --name "${RULE_NAME}" \
    --region "${REGION}" \
    --query '[Name, ScheduleExpression, State]' \
    --output json

echo ""
echo "=== DEPLOY COMPLETE ==="
echo ""
echo "To test on-demand:"
echo "  aws lambda invoke --function-name hypothesis-engine \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --payload '{\"force_run\":true}' /tmp/hypo_out.json --region ${REGION} && cat /tmp/hypo_out.json"
