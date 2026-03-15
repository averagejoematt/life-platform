#!/usr/bin/env bash
# deploy/r8_p0_verify.sh — Architecture Review #8 P0 verification
#
# Checks the two highest-priority findings from R8:
#   1. Webhook auth status — is the endpoint actually authenticated?
#   2. Secret name reconciliation — do IAM policies match actual secrets?
#
# Run: bash deploy/r8_p0_verify.sh
# Requires: AWS CLI v2, configured for us-west-2

set -euo pipefail
REGION="us-west-2"

echo "═══════════════════════════════════════════════════════════════"
echo "Architecture Review #8 — P0 Verification"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ──────────────────────────────────────────────────────────────────
# CHECK 1: What secrets actually exist in AWS?
# ──────────────────────────────────────────────────────────────────
echo "── CHECK 1: Secrets Manager inventory ──"
echo "Listing all life-platform secrets..."
echo ""

SECRETS=$(aws secretsmanager list-secrets \
  --region "$REGION" \
  --filters Key=name,Values=life-platform \
  --query 'SecretList[*].{Name:Name,DeletedDate:DeletedDate}' \
  --output table 2>/dev/null || echo "ERROR: Could not list secrets")

echo "$SECRETS"
echo ""

# Check for ingestion-keys specifically
echo "Does 'life-platform/ingestion-keys' exist?"
if aws secretsmanager describe-secret --secret-id "life-platform/ingestion-keys" --region "$REGION" > /dev/null 2>&1; then
    echo "  ⚠️  YES — life-platform/ingestion-keys EXISTS in AWS"
    echo "     This secret is referenced in role_policies.py (COST-B) but NOT in ARCHITECTURE.md."
    echo "     ACTION: Either document it or migrate IAM to use dedicated secret names."
else
    echo "  ❌ NO — life-platform/ingestion-keys does NOT exist"
    echo "     But role_policies.py grants IAM access to it for 4 Lambdas (Notion, Habitify, Todoist, HAE)."
    echo "     ACTION: Fix role_policies.py to use actual secret names."
fi
echo ""

# ──────────────────────────────────────────────────────────────────
# CHECK 2: What SECRET_NAME env vars are set on affected Lambdas?
# ──────────────────────────────────────────────────────────────────
echo "── CHECK 2: Lambda SECRET_NAME env vars ──"
echo ""

for FUNC in notion-journal-ingestion habitify-data-ingestion todoist-data-ingestion health-auto-export-webhook; do
    SECRET_VAR=$(aws lambda get-function-configuration \
        --function-name "$FUNC" \
        --region "$REGION" \
        --query 'Environment.Variables.SECRET_NAME' \
        --output text 2>/dev/null || echo "ERROR")

    if [ "$SECRET_VAR" = "None" ] || [ -z "$SECRET_VAR" ]; then
        echo "  $FUNC: SECRET_NAME not set (will use code default)"
    elif [ "$SECRET_VAR" = "ERROR" ]; then
        echo "  $FUNC: ❌ Could not read config"
    else
        echo "  $FUNC: SECRET_NAME = $SECRET_VAR"
    fi
done
echo ""

# ──────────────────────────────────────────────────────────────────
# CHECK 3: Webhook auth — does it reject bad tokens?
# ──────────────────────────────────────────────────────────────────
echo "── CHECK 3: Webhook auth test ──"
echo "Testing health-auto-export webhook with invalid token..."
echo ""

# Get the API Gateway URL
API_URL="https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest"

HTTP_CODE=$(curl -s -o /tmp/r8_webhook_test.json -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer INVALID_TOKEN_R8_TEST" \
    -H "Content-Type: application/json" \
    -d '{"data":{"metrics":[]}}' \
    "$API_URL" 2>/dev/null || echo "000")

echo "  URL: $API_URL"
echo "  HTTP status: $HTTP_CODE"

if [ "$HTTP_CODE" = "401" ]; then
    echo "  ✅ Webhook correctly rejects invalid tokens"
elif [ "$HTTP_CODE" = "403" ]; then
    echo "  ✅ Webhook rejects request (403 — may be API Gateway level)"
elif [ "$HTTP_CODE" = "200" ]; then
    echo "  ⚠️  WARNING: Webhook returned 200 with invalid token!"
    echo "     This may mean auth is broken. Check response body:"
    cat /tmp/r8_webhook_test.json 2>/dev/null || true
    echo ""
elif [ "$HTTP_CODE" = "500" ]; then
    echo "  ⚠️  Webhook returned 500 — Lambda may be crashing on auth"
    echo "     Check CloudWatch logs: aws logs tail /aws/lambda/health-auto-export-webhook --since 5m"
    echo "     Response body:"
    cat /tmp/r8_webhook_test.json 2>/dev/null || true
    echo ""
elif [ "$HTTP_CODE" = "000" ]; then
    echo "  ❌ Could not reach webhook endpoint (network error or URL changed)"
else
    echo "  ℹ️  Unexpected status code: $HTTP_CODE"
    cat /tmp/r8_webhook_test.json 2>/dev/null || true
fi
echo ""

# ──────────────────────────────────────────────────────────────────
# CHECK 4: Verify reserved concurrency on MCP Lambda
# ──────────────────────────────────────────────────────────────────
echo "── CHECK 4: MCP Lambda reserved concurrency ──"

CONCURRENCY=$(aws lambda get-function-concurrency \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --query 'ReservedConcurrentExecutions' \
    --output text 2>/dev/null || echo "ERROR")

if [ "$CONCURRENCY" = "None" ] || [ -z "$CONCURRENCY" ]; then
    echo "  ⚠️  No reserved concurrency set on life-platform-mcp"
    echo "     ADR-010 documents reserved concurrency of 10. Consider setting it."
elif [ "$CONCURRENCY" = "10" ]; then
    echo "  ✅ Reserved concurrency: $CONCURRENCY (matches ADR-010)"
else
    echo "  ℹ️  Reserved concurrency: $CONCURRENCY (ADR-010 specifies 10)"
fi
echo ""

# ──────────────────────────────────────────────────────────────────
# CHECK 5: Run the new IAM/secrets consistency lint
# ──────────────────────────────────────────────────────────────────
echo "── CHECK 5: IAM/secrets consistency lint ──"
echo "Running tests/test_iam_secrets_consistency.py..."
echo ""

cd "$(dirname "$0")/.."
python3 -m pytest tests/test_iam_secrets_consistency.py -v --tb=short 2>&1 || true
echo ""

# ──────────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo "P0 verification complete. Review findings above."
echo "═══════════════════════════════════════════════════════════════"

rm -f /tmp/r8_webhook_test.json
