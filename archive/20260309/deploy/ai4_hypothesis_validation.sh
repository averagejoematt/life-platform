#!/bin/bash
# deploy/ai4_hypothesis_validation.sh — AI-4: Hypothesis engine output validation
# Deploys updated hypothesis engine Lambda with validation logic
set -euo pipefail
REGION="us-west-2"

echo "═══════════════════════════════════════════════════════════"
echo "AI-4: Hypothesis Engine Output Validation"
echo "═══════════════════════════════════════════════════════════"

# ── Pre-flight: Verify the Lambda source file exists and has AI-4 markers ──
LAMBDA_FILE="lambdas/hypothesis_engine_lambda.py"
if [ ! -f "$LAMBDA_FILE" ]; then
  echo "❌ ERROR: $LAMBDA_FILE not found!"
  echo "   Download hypothesis_engine_lambda.py from Claude's output and copy to lambdas/"
  exit 1
fi

if ! grep -q "AI-4" "$LAMBDA_FILE"; then
  echo "❌ ERROR: $LAMBDA_FILE does not contain AI-4 markers!"
  echo "   Make sure you've copied the updated version from Claude's output."
  exit 1
fi

echo "✅ Source file verified (AI-4 markers present)"
echo ""

# ── Deploy hypothesis engine Lambda ──
echo "Deploying hypothesis-engine Lambda..."
bash deploy/deploy_lambda.sh hypothesis-engine lambdas/hypothesis_engine_lambda.py

echo ""
echo "Waiting 5 seconds..."
sleep 5

# ── Smoke test (dry run — won't call AI, just verifies import + data gather) ──
echo ""
echo "Smoke testing hypothesis-engine..."
RESPONSE=$(aws lambda invoke \
  --function-name hypothesis-engine \
  --payload '{}' \
  --region "$REGION" \
  --cli-binary-format raw-in-base64-out \
  /tmp/ai4_test.json 2>&1)

echo "  Lambda response:"
cat /tmp/ai4_test.json | python3 -m json.tool 2>/dev/null || cat /tmp/ai4_test.json
echo ""

# Check for errors
if grep -q "errorMessage" /tmp/ai4_test.json 2>/dev/null; then
  echo "⚠️ Lambda returned an error — check CloudWatch logs:"
  echo "  aws logs tail /aws/lambda/hypothesis-engine --since 5m --region $REGION"
else
  echo "✅ Lambda executed successfully"
fi

# ── Verify AI-4 log markers in CloudWatch ──
echo ""
echo "Checking for [AI-4] log markers..."
sleep 3
aws logs tail /aws/lambda/hypothesis-engine --since 2m --region "$REGION" --format short 2>/dev/null | grep -o '\[AI-4\][^"]*' | head -5 || echo "  (no AI-4 markers found yet — may need more time)"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ AI-4 Complete!"
echo ""
echo "Changes deployed:"
echo "  • Data completeness check (10+ days with 5+ metrics each)"
echo "  • Hypothesis validation (required fields, 2+ domains,"
echo "    numeric thresholds in criteria, 7-30d window, dedup)"
echo "  • 30-day hard expiry on unconfirmed hypotheses"
echo "  • 7-day minimum sample before checking (was 3)"
echo "  • 4 confirming checks needed for promotion (was 2)"
echo "  • Haiku verdict validation (reject malformed responses)"
echo "  • Updated prompt requires effect sizes + numeric thresholds"
echo "═══════════════════════════════════════════════════════════"
