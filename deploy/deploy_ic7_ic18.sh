#!/bin/bash
# deploy/deploy_ic7_ic18.sh
# Deploys IC-7 (Cross-Pillar Trade-off Reasoning) + IC-18 (Hypothesis Engine)
# P1 (Weekly Plate memory/anti-repeat) was already live — verified and marked complete.
# Version: v2.89.0
set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
LAMBDA_ROLE="arn:aws:iam::${ACCOUNT}:role/lambda-life-platform-role"
TABLE="life-platform"
S3_BUCKET="matthew-life-platform"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDA_DIR="${PROJECT_ROOT}/lambdas"

echo "=== Life Platform v2.89.0 Deploy: IC-7 + IC-18 + P1 ==="
echo "Project root: ${PROJECT_ROOT}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: daily-brief Lambda (IC-7 in ai_calls.py)
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [1/4] Deploying daily-brief (IC-7 cross-pillar trade-offs)..."
bash "${PROJECT_ROOT}/deploy/deploy_lambda.sh" daily-brief
echo "    Waiting 10s..."
sleep 10

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: life-platform-mcp (IC-18 tools: 142 → 144)
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [2/4] Deploying life-platform-mcp (IC-18: +tools_hypotheses, 142 → 144 tools)..."
bash "${PROJECT_ROOT}/deploy/deploy_mcp_split.sh"
echo "    Waiting 10s..."
sleep 10

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: hypothesis-engine Lambda (new, IC-18)
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [3/4] Deploying hypothesis-engine Lambda..."

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
echo "    hypothesis-engine deployed. Waiting 10s..."
sleep 10

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: EventBridge rule — Sunday 11 AM PT (19:00 UTC)
# ─────────────────────────────────────────────────────────────────────────────
echo ">>> [4/4] Setting up EventBridge schedule (Sunday 11 AM PT)..."

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

# Grant EventBridge permission (idempotent — ignore if already exists)
aws lambda add-permission \
    --function-name hypothesis-engine \
    --statement-id "allow-eventbridge-hypothesis-engine" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "${REGION}" \
    --output text --query 'Statement' > /dev/null 2>&1 || \
    echo "    (EventBridge permission already exists)"

echo "    EventBridge rule created: ${RULE_NAME}"

# ─────────────────────────────────────────────────────────────────────────────
# VERIFY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== VERIFICATION ==="

echo ""
echo "--- MCP tool count (expect 144) ---"
aws lambda invoke \
    --function-name life-platform-mcp \
    --cli-binary-format raw-in-base64-out \
    --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"}' \
    /tmp/mcp_out.json \
    --region "${REGION}" > /dev/null
python3 -c "
import json
with open('/tmp/mcp_out.json') as f:
    d = json.load(f)
b = json.loads(d.get('body','{}'))
tools = b.get('result',{}).get('tools',[])
print(f'  Total MCP tools: {len(tools)}')
hypo = [t['name'] for t in tools if 'hypothesis' in t['name'].lower() or 'hypothes' in t['name'].lower()]
print(f'  Hypothesis tools: {hypo}')
"

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
echo "=== DEPLOY COMPLETE: v2.89.0 ==="
echo ""
echo "Changes deployed:"
echo "  IC-7 : _build_cross_pillar_tradeoffs() in ai_calls.py"
echo "         Injected into call_board_of_directors + call_tldr_and_guidance"
echo "         Detects: sleep vs movement, nutrition deficit vs TSB, stress vs recovery,"
echo "         metabolic lag, consistency trailing pillar strength"
echo ""
echo "  IC-18: hypothesis-engine Lambda (34th Lambda) + EventBridge (Sunday 11 AM PT)"
echo "         2 new MCP tools: get_hypotheses + update_hypothesis_outcome (144 total)"
echo "         DDB: pk=USER#matthew#SOURCE#hypotheses, sk=HYPOTHESIS#<ISO-timestamp>"
echo "         Weekly scientific method loop: generate -> check -> confirm/refute -> coaching"
echo ""
echo "  P1   : Verified live in weekly_plate_lambda.py (load_plate_history + store_plate_summary)"
echo ""
echo "To test hypothesis engine on-demand:"
echo "  aws lambda invoke --function-name hypothesis-engine \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --payload '{\"force_run\":true}' /tmp/hypo_out.json --region ${REGION} && cat /tmp/hypo_out.json"
echo ""
echo "To check DDB for hypotheses:"
echo "  aws dynamodb query --table-name life-platform \\"
echo "    --key-condition-expression 'pk = :pk AND begins_with(sk, :prefix)' \\"
echo "    --expression-attribute-values '{\":pk\":{\"S\":\"USER#matthew#SOURCE#hypotheses\"},\":prefix\":{\"S\":\"HYPOTHESIS#\"}}' \\"
echo "    --region ${REGION} --output json | python3 -c \"import sys,json; d=json.load(sys.stdin); print(len(d['Items']), 'hypotheses')\""
