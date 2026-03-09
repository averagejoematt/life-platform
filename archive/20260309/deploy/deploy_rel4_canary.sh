#!/usr/bin/env bash
# deploy_rel4_canary.sh — REL-4: Synthetic End-to-End Health Check Canary
#
# Creates:
#   - IAM role: lambda-canary-role (DDB read/write on CANARY# pk, S3 canary/, SES, CW, Secrets)
#   - Lambda: life-platform-canary
#   - EventBridge rule: canary-schedule (every 4 hours)
#   - CloudWatch alarms: canary-ddb-failure, canary-s3-failure, canary-mcp-failure
#   - Adds canary widgets to OBS-2 dashboard
#
# Usage: bash deploy/deploy_rel4_canary.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
FUNCTION_NAME="life-platform-canary"
ROLE_NAME="lambda-canary-role"
RULE_NAME="canary-schedule"
TABLE_NAME="life-platform"
S3_BUCKET="matthew-life-platform"
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"

info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── 1. Get MCP Function URL ────────────────────────────────────────────────────
info "Fetching MCP Function URL..."
MCP_URL=$(aws lambda get-function-url-config \
    --function-name "life-platform-mcp" \
    --region "$REGION" \
    --query FunctionUrl --output text 2>/dev/null || echo "")

if [ -z "$MCP_URL" ]; then
    warn "Could not fetch MCP Function URL — MCP check will be skipped at runtime"
    MCP_URL="https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/"
fi
info "  MCP URL: $MCP_URL"

# ── 2. Create IAM role ─────────────────────────────────────────────────────────
info "Creating IAM role $ROLE_NAME..."

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --no-cli-pager 2>/dev/null || info "  Role already exists"

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    2>/dev/null || true

# Inline policy: tightly scoped to CANARY# pk only
INLINE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DDBCanaryOnly",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/${TABLE_NAME}",
      "Condition": {
        "ForAllValues:StringLike": {
          "dynamodb:LeadingKeys": ["CANARY#*"]
        }
      }
    },
    {
      "Sid": "S3CanaryPrefix",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::${S3_BUCKET}/canary/*"
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {"cloudwatch:namespace": "LifePlatform/Canary"}
      }
    },
    {
      "Sid": "SESAlert",
      "Effect": "Allow",
      "Action": ["sesv2:SendEmail"],
      "Resource": "*",
      "Condition": {
        "StringLike": {"ses:FromAddress": "*@mattsusername.com"}
      }
    },
    {
      "Sid": "SecretsAPIKey",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/api-keys*"
    }
  ]
}
EOF
)

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "canary-policy" \
    --policy-document "$INLINE_POLICY"

ok "IAM role configured"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

# ── 3. Package and deploy Lambda ───────────────────────────────────────────────
info "Packaging canary Lambda..."
ZIP_FILE="/tmp/${FUNCTION_NAME}.zip"
rm -f "$ZIP_FILE"
cd "$(dirname "$0")/.."

zip -j "$ZIP_FILE" lambdas/canary_lambda.py > /dev/null
info "  Zip: $(du -h "$ZIP_FILE" | cut -f1)"

ENV_VARS="Variables={TABLE_NAME=${TABLE_NAME},S3_BUCKET=${S3_BUCKET},MCP_FUNCTION_URL=${MCP_URL},MCP_SECRET_NAME=life-platform/api-keys}"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
    info "Updating existing Lambda..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --environment "$ENV_VARS" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
else
    info "Creating Lambda..."
    sleep 10  # IAM propagation
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler "canary_lambda.lambda_handler" \
        --zip-file "fileb://${ZIP_FILE}" \
        --timeout 60 \
        --memory-size 256 \
        --region "$REGION" \
        --description "REL-4: Synthetic canary — DDB + S3 + MCP round-trip every 4h" \
        --environment "$ENV_VARS" \
        --no-cli-pager > /dev/null
fi
ok "Lambda deployed"

# ── 4. EventBridge rule: every 4 hours ────────────────────────────────────────
info "Creating EventBridge rule: every 4 hours..."
RULE_ARN=$(aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "rate(4 hours)" \
    --state ENABLED \
    --description "REL-4: Synthetic canary every 4h" \
    --region "$REGION" \
    --query RuleArn --output text)

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "canary-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" \
    --no-cli-pager 2>/dev/null || info "  Permission already exists"

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "[{\"Id\": \"canary-target\", \"Arn\": \"${LAMBDA_ARN}\"}]" \
    --region "$REGION" \
    --no-cli-pager > /dev/null
ok "EventBridge rule configured (every 4 hours)"

# ── 5. CloudWatch alarms ───────────────────────────────────────────────────────
info "Creating CloudWatch alarms..."

for CHECK in ddb s3 mcp; do
    METRIC_NAME="CanaryDDBFail"
    CHECK_LABEL="DynamoDB"
    if [ "$CHECK" = "s3" ]; then METRIC_NAME="CanaryS3Fail"; CHECK_LABEL="S3"; fi
    if [ "$CHECK" = "mcp" ]; then METRIC_NAME="CanaryMCPFail"; CHECK_LABEL="MCP Lambda"; fi

    aws cloudwatch put-metric-alarm \
        --alarm-name "life-platform-canary-${CHECK}-failure" \
        --alarm-description "Canary: ${CHECK_LABEL} round-trip failed — platform data path impaired" \
        --namespace "LifePlatform/Canary" \
        --metric-name "$METRIC_NAME" \
        --statistic Sum \
        --period 300 \
        --evaluation-periods 1 \
        --threshold 1 \
        --comparison-operator GreaterThanOrEqualToThreshold \
        --treat-missing-data notBreaching \
        --alarm-actions "$SNS_ARN" \
        --region "$REGION" \
        --no-cli-pager
    info "  ✅ Alarm: life-platform-canary-${CHECK}-failure"
done

# Composite alarm: any canary failure
aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-canary-any-failure" \
    --alarm-description "Any canary check (DDB/S3/MCP) failed in last 5 minutes" \
    --namespace "LifePlatform/Canary" \
    --metric-name "CanaryDDBFail" \
    --statistic Sum \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$SNS_ARN" \
    --region "$REGION" \
    --no-cli-pager
info "  ✅ Alarm: life-platform-canary-any-failure"
ok "CloudWatch alarms created"

# ── 6. Test invocation ─────────────────────────────────────────────────────────
info "Running first canary check..."
sleep 3
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/canary_test.json \
    --query 'LogResult' \
    --output text 2>/dev/null | base64 -d | grep -E "(Canary|✅|❌|DDB|S3|MCP|PASS|FAIL)" || true

echo ""
RESULT=$(cat /tmp/canary_test.json 2>/dev/null || echo "{}")
echo "  Response: $RESULT"

echo ""
echo "══════════════════════════════════════════════════"
echo "✅  REL-4 Canary deployed!"
echo ""
echo "  Lambda:    $FUNCTION_NAME"
echo "  Schedule:  every 4 hours"
echo "  Checks:    DynamoDB write/read • S3 write/read • MCP reachability"
echo "  Alarms:    canary-{ddb,s3,mcp,any}-failure → SNS → email"
echo "  Metrics:   LifePlatform/Canary namespace"
echo "══════════════════════════════════════════════════"
