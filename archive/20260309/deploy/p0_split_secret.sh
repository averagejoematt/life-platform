#!/bin/bash
# p0_split_secret.sh — P0: Split life-platform/api-keys into dedicated ai-keys secret
#
# WHAT: Creates life-platform/ai-keys containing ONLY the Anthropic API key.
#       Updates ANTHROPIC_SECRET env var on all AI-calling Lambdas to point
#       to the new scoped secret. Expands the shared IAM policy to include the
#       new secret ARN (stays in effect until role decomposition runs).
#
# WHY: The bundle secret (api-keys) contains 9 credentials. Any Lambda that
#      needs the Anthropic key currently gets access to all 9. Isolating the
#      Anthropic key limits blast radius to just that credential.
#
# SAFE TO RE-RUN: Uses put-secret-value if secret already exists.
#
# Usage: cd ~/Documents/Claude/life-platform && ./deploy/p0_split_secret.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P0: Split Anthropic API key into dedicated secret           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Read the current Anthropic key from the bundle secret ──────────────
echo "── Step 1: Reading current Anthropic key from life-platform/api-keys ──"
CURRENT_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "life-platform/api-keys" \
    --region "$REGION" \
    --query "SecretString" --output text --no-cli-pager | \
    python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('anthropic_api_key','NOT_FOUND'))")

if [ "$CURRENT_KEY" = "NOT_FOUND" ] || [ -z "$CURRENT_KEY" ]; then
    echo "❌ Could not read anthropic_api_key from life-platform/api-keys"
    echo "   Check the secret exists and your AWS credentials are valid."
    exit 1
fi
echo "  ✅ Anthropic key retrieved (length: ${#CURRENT_KEY} chars)"
echo ""

# ── Step 2: Create (or update) life-platform/ai-keys ──────────────────────────
echo "── Step 2: Creating life-platform/ai-keys secret ──"
SECRET_VALUE="{\"anthropic_api_key\": \"$CURRENT_KEY\"}"

EXISTING=$(aws secretsmanager describe-secret \
    --secret-id "life-platform/ai-keys" \
    --region "$REGION" --no-cli-pager 2>&1 || true)

if echo "$EXISTING" | grep -q "ResourceNotFoundException"; then
    aws secretsmanager create-secret \
        --name "life-platform/ai-keys" \
        --description "Anthropic API key — split from api-keys on $(date +%Y-%m-%d) (P0 security fix)" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "  ✅ Created new secret: life-platform/ai-keys"
else
    aws secretsmanager put-secret-value \
        --secret-id "life-platform/ai-keys" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "  ✅ Updated existing secret: life-platform/ai-keys"
fi

AI_KEYS_ARN=$(aws secretsmanager describe-secret \
    --secret-id "life-platform/ai-keys" \
    --region "$REGION" \
    --query "ARN" --output text --no-cli-pager)
echo "  ARN: $AI_KEYS_ARN"
echo ""

# ── Step 3: Update ANTHROPIC_SECRET env var on all AI-calling Lambdas ──────────
echo "── Step 3: Updating ANTHROPIC_SECRET env var on all AI-calling Lambdas ──"

# Every Lambda that calls the Anthropic API (verified from source)
AI_LAMBDAS=(
    "daily-brief"
    "weekly-digest"
    "monthly-digest"
    "nutrition-review"
    "wednesday-chronicle"
    "weekly-plate"
    "monday-compass"
    "anomaly-detector"
    "daily-insight-compute"
    "hypothesis-engine"
)

TMPFILE=$(mktemp /tmp/lambda-env-XXXXXX.json)
trap 'rm -f "$TMPFILE"' EXIT

for fn in "${AI_LAMBDAS[@]}"; do
    echo -n "  Updating $fn ... "

    CURRENT_ENV=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Environment.Variables" \
        --output json --no-cli-pager 2>/dev/null || echo "{}")

    # Write to temp file — avoids shell quoting issues with --environment flag
    python3 -c "
import sys, json
env = json.loads(sys.argv[1])
env['ANTHROPIC_SECRET'] = 'life-platform/ai-keys'
payload = {'FunctionName': sys.argv[2], 'Environment': {'Variables': env}}
print(json.dumps(payload))
" "$CURRENT_ENV" "$fn" > "$TMPFILE"

    aws lambda update-function-configuration \
        --cli-input-json "file://$TMPFILE" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "✅"
    sleep 3  # avoid ResourceConflictException on rapid sequential updates
done
echo ""

# ── Step 4: Update the shared IAM policy to allow the new secret ARN ──────────
echo "── Step 4: Updating IAM policy to permit life-platform/ai-keys ──"

# This updates lambda-weekly-digest-role (currently shared by all AI-calling Lambdas).
# After p0_iam_role_decomposition.sh runs, per-role policies will replace this.
ROLE_NAME="lambda-weekly-digest-role"
POLICY_NAME="weekly-digest-access"

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"DynamoDB\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"dynamodb:GetItem\",
        \"dynamodb:Query\",
        \"dynamodb:PutItem\",
        \"dynamodb:UpdateItem\",
        \"dynamodb:BatchGetItem\"
      ],
      \"Resource\": \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\"
    },
    {
      \"Sid\": \"SecretsAI\",
      \"Effect\": \"Allow\",
      \"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": [
        \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\",
        \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/api-keys*\"
      ]
    },
    {
      \"Sid\": \"Email\",
      \"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\", \"sesv2:SendEmail\"],
      \"Resource\": \"*\"
    },
    {
      \"Sid\": \"S3Read\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:GetObject\",
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/config/*\",
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\"
      ]
    },
    {
      \"Sid\": \"S3Write\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:PutObject\",
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\"
      ]
    }
  ]
}" --no-cli-pager

echo "  ✅ Policy updated: both ai-keys and api-keys now permitted"
echo ""

# ── Step 5: Verification ────────────────────────────────────────────────────────
echo "── Step 5: Verification ──"
echo ""
echo "  Secret existence:"
aws secretsmanager describe-secret \
    --secret-id "life-platform/ai-keys" \
    --region "$REGION" \
    --query "{Name:Name,ARN:ARN}" \
    --output table --no-cli-pager

echo ""
echo "  Spot-check (daily-brief ANTHROPIC_SECRET):"
aws lambda get-function-configuration \
    --function-name "daily-brief" \
    --region "$REGION" \
    --query "Environment.Variables.ANTHROPIC_SECRET" \
    --output text --no-cli-pager

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P0 Secret Split Complete                                 ║"
echo "║                                                              ║"
echo "║  NEXT: After 24h of stable Lambda runs, remove the          ║"
echo "║  anthropic_api_key field from life-platform/api-keys to     ║"
echo "║  fully isolate the credential.                               ║"
echo "║                                                              ║"
echo "║  Then run: ./deploy/p0_iam_role_decomposition.sh            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
