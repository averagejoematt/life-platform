#!/usr/bin/env bash
# setup_remediation_role.sh — create/update the OIDC role for the self-healing
# remediation agent (.github/workflows/remediation-agent.yml). Idempotent.
#
# This is a HIGH-SEVERITY IAM change (new principal + OIDC trust + Bedrock/KMS/SES),
# so it's intentionally operator-run, not agent-run. Run once:
#   bash deploy/setup_remediation_role.sh
#
# Reuses the existing GitHub OIDC provider (created by setup_github_oidc.sh).
set -euo pipefail

ACCOUNT="205930651321"
REGION="us-west-2"
ROLE="github-actions-remediation-role"
REPO="averagejoematt/life-platform"

TRUST=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Federated":"arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{"StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"},
    "StringLike":{"token.actions.githubusercontent.com:sub":"repo:${REPO}:*"}}}]}
JSON
)

# Read-only diagnosis + Bedrock + scoped audit-log write + SES report. NO deploy,
# NO lambda update, NO IAM write — the agent proposes fixes via PR; humans/CI deploy.
PERM=$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Sid":"Bedrock","Effect":"Allow",
   "Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],
   "Resource":[
   "arn:aws:bedrock:*:${ACCOUNT}:inference-profile/us.anthropic.claude-*",
   "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"]},
 {"Sid":"Diagnose","Effect":"Allow","Action":["logs:FilterLogEvents","logs:GetLogEvents",
   "logs:DescribeLogGroups","logs:DescribeLogStreams","cloudwatch:DescribeAlarms",
   "cloudwatch:DescribeAlarmHistory","cloudwatch:GetMetricData","cloudwatch:GetMetricStatistics",
   "cloudwatch:ListMetrics","lambda:GetFunctionConfiguration","lambda:ListFunctions"],"Resource":"*"},
 {"Sid":"DDB","Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:Query"],
   "Resource":"arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/life-platform"},
 {"Sid":"KMS","Effect":"Allow","Action":"kms:Decrypt",
   "Resource":"arn:aws:kms:${REGION}:${ACCOUNT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"},
 {"Sid":"S3Read","Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::matthew-life-platform/*"},
 {"Sid":"S3Log","Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::matthew-life-platform/remediation-log/*"},
 {"Sid":"SQS","Effect":"Allow","Action":["sqs:ReceiveMessage","sqs:GetQueueAttributes"],
   "Resource":"arn:aws:sqs:${REGION}:${ACCOUNT}:life-platform-ingestion-dlq"},
 {"Sid":"SSM","Effect":"Allow","Action":"ssm:GetParameter",
   "Resource":"arn:aws:ssm:${REGION}:${ACCOUNT}:parameter/life-platform/*"},
 {"Sid":"SES","Effect":"Allow","Action":["ses:SendEmail","sesv2:SendEmail"],"Resource":"*"}
]}
JSON
)

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "Updating trust policy on $ROLE..."
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  echo "Creating $ROLE..."
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
    --description "Self-healing remediation agent (GH Actions OIDC; Bedrock + read-only diagnosis)" >/dev/null
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name remediation-permissions --policy-document "$PERM"
echo "✅ $ROLE ready: arn:aws:iam::${ACCOUNT}:role/${ROLE}"
echo "   The workflow (.github/workflows/remediation-agent.yml) assumes this role via OIDC."
