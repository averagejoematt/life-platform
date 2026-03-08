#!/usr/bin/env bash
# deploy_rel2_dlq_consumer.sh — REL-2: DLQ Consumer Lambda
#
# Creates:
#   - IAM role + policy: lambda-dlq-consumer-role
#   - Lambda: life-platform-dlq-consumer
#   - EventBridge rule: dlq-consumer-schedule (every 6 hours)
#
# Usage: bash deploy/deploy_rel2_dlq_consumer.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
FUNCTION_NAME="life-platform-dlq-consumer"
ROLE_NAME="lambda-dlq-consumer-role"
RULE_NAME="dlq-consumer-schedule"
DLQ_NAME="life-platform-ingestion-dlq"
S3_BUCKET="matthew-life-platform"
TABLE_NAME="life-platform"

info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── 1. Get DLQ URL ─────────────────────────────────────────────────────────────
info "Fetching DLQ URL..."
DLQ_URL=$(aws sqs get-queue-url \
    --queue-name "$DLQ_NAME" \
    --region "$REGION" \
    --query QueueUrl --output text)
info "  DLQ URL: $DLQ_URL"

DLQ_ARN=$(aws sqs get-queue-attributes \
    --queue-url "$DLQ_URL" \
    --attribute-names QueueArn \
    --region "$REGION" \
    --query Attributes.QueueArn --output text)
info "  DLQ ARN: $DLQ_ARN"

# ── 2. Create IAM role ──────────────────────────────────────────────────────────
info "Creating IAM role $ROLE_NAME..."

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

# Create role (ignore error if already exists)
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --no-cli-pager 2>/dev/null || info "  Role already exists — updating policy"

# Attach basic Lambda execution managed policy
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    2>/dev/null || true

# Inline policy: SQS read/delete + Lambda invoke + S3 archive write + SES send
INLINE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DLQAccess",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "$DLQ_ARN"
    },
    {
      "Sid": "LambdaRetryInvoke",
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT}:function:*-data-ingestion"
    },
    {
      "Sid": "S3Archive",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::${S3_BUCKET}/dead-letter-archive/*"
    },
    {
      "Sid": "SESAlert",
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "sesv2:SendEmail"],
      "Resource": "*",
      "Condition": {
        "StringLike": {"ses:FromAddress": "*@mattsusername.com"}
      }
    }
  ]
}
EOF
)

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "dlq-consumer-policy" \
    --policy-document "$INLINE_POLICY"

ok "IAM role configured"

ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

# ── 3. Package and deploy Lambda ────────────────────────────────────────────────
info "Packaging Lambda..."
ZIP_FILE="/tmp/${FUNCTION_NAME}.zip"
rm -f "$ZIP_FILE"
cd "$(dirname "$0")/.."  # project root

zip -j "$ZIP_FILE" \
    lambdas/dlq_consumer_lambda.py \
    > /dev/null

info "  Zip: $(du -h "$ZIP_FILE" | cut -f1)"

# Create or update
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
    info "Updating existing Lambda $FUNCTION_NAME..."

    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "$REGION" \
        --no-cli-pager > /dev/null

    # Wait for update to complete before updating config
    aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"

    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --environment "Variables={TABLE_NAME=${TABLE_NAME},S3_BUCKET=${S3_BUCKET},DLQ_URL=${DLQ_URL},AWS_REGION_OVERRIDE=${REGION}}" \
        --region "$REGION" \
        --no-cli-pager > /dev/null

else
    info "Creating Lambda $FUNCTION_NAME..."

    # Brief wait for IAM role propagation
    sleep 10

    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler "dlq_consumer_lambda.lambda_handler" \
        --zip-file "fileb://${ZIP_FILE}" \
        --timeout 120 \
        --memory-size 256 \
        --region "$REGION" \
        --description "REL-2: DLQ consumer — classifies, retries, archives, alerts on failed messages" \
        --environment "Variables={TABLE_NAME=${TABLE_NAME},S3_BUCKET=${S3_BUCKET},DLQ_URL=${DLQ_URL}}" \
        --no-cli-pager > /dev/null
fi

ok "Lambda deployed"

# ── 4. EventBridge rule: every 6 hours ──────────────────────────────────────────
info "Creating EventBridge rule: $RULE_NAME (every 6 hours)..."

RULE_ARN=$(aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "rate(6 hours)" \
    --state ENABLED \
    --description "REL-2: DLQ consumer — polls life-platform-ingestion-dlq every 6h" \
    --region "$REGION" \
    --query RuleArn --output text)

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

# Add EventBridge permission to invoke Lambda
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "dlq-consumer-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" \
    --no-cli-pager 2>/dev/null || info "  Permission already exists"

# Wire target
aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "[{\"Id\": \"dlq-consumer-target\", \"Arn\": \"${LAMBDA_ARN}\"}]" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

ok "EventBridge rule configured (every 6 hours)"

# ── 5. CloudWatch alarm: DLQ depth ──────────────────────────────────────────────
info "Creating CloudWatch alarm: dlq-depth-warning..."

aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-dlq-depth-warning" \
    --alarm-description "DLQ has 1+ messages — REL-2 consumer will process on next run" \
    --namespace "AWS/SQS" \
    --metric-name "ApproximateNumberOfMessagesVisible" \
    --dimensions "Name=QueueName,Value=${DLQ_NAME}" \
    --statistic Maximum \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts" \
    --region "$REGION" \
    --no-cli-pager

ok "DLQ depth alarm created"

# ── 6. Test invocation ───────────────────────────────────────────────────────────
info "Testing invocation (DLQ should be empty — expect 0 messages)..."
sleep 3

aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/dlq_consumer_test.json \
    --query 'LogResult' \
    --output text 2>/dev/null | base64 -d | grep -E "(INFO|ERROR|DLQ|messages)" || true

echo ""
RESULT=$(cat /tmp/dlq_consumer_test.json 2>/dev/null || echo "{}")
echo "  Response: $RESULT"

echo ""
echo "══════════════════════════════════════════════════"
echo "✅  REL-2 DLQ Consumer deployed!"
echo ""
echo "  Lambda:     $FUNCTION_NAME"
echo "  Schedule:   every 6 hours"
echo "  DLQ:        $DLQ_NAME"
echo "  Archive:    s3://${S3_BUCKET}/dead-letter-archive/"
echo ""
echo "  Behaviour:"
echo "    Transient (timeout/throttle/503): retry once via Lambda invoke"
echo "    Permanent (auth/404/receive≥3):   archive to S3 + SES alert"
echo "══════════════════════════════════════════════════"
