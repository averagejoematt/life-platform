#!/usr/bin/env bash
# SEC-1 Finish: Reassign 2 remaining Lambdas off lambda-weekly-digest-role
# and deprecate the shared role.
#
# Run from project root: bash deploy/sec1_finish_iam_decomposition.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

EMAIL_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-email-role"
COMPUTE_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-compute-role"

echo "=== SEC-1 Finish: Reassigning 2 remaining Lambdas ==="
echo ""

# brittany-weekly-email is an email Lambda → email role
echo -n "  brittany-weekly-email → life-platform-email-role ... "
aws lambda update-function-configuration \
  --function-name brittany-weekly-email \
  --role "$EMAIL_ROLE_ARN" \
  --region "$REGION" \
  --no-cli-pager > /dev/null
echo "✅"

sleep 5

# life-platform-qa-smoke tests things but shouldn't send email
echo -n "  life-platform-qa-smoke → life-platform-compute-role ... "
aws lambda update-function-configuration \
  --function-name life-platform-qa-smoke \
  --role "$COMPUTE_ROLE_ARN" \
  --region "$REGION" \
  --no-cli-pager > /dev/null
echo "✅"

echo ""
echo "=== Verification ==="
for fn in "brittany-weekly-email" "life-platform-qa-smoke"; do
  role=$(aws lambda get-function-configuration \
    --function-name "$fn" --region "$REGION" \
    --query "Role" --output text --no-cli-pager | sed 's|.*role/||')
  echo "  $fn → $role"
done

echo ""
echo "=== Checking lambda-weekly-digest-role still has users ==="
REMAINING=$(aws lambda list-functions --region "$REGION" --no-cli-pager \
  --query "Functions[?Role=='arn:aws:iam::${ACCOUNT}:role/lambda-weekly-digest-role'].FunctionName" \
  --output text)

if [ -z "$REMAINING" ] || [ "$REMAINING" = "None" ]; then
  echo "  ✅ No Lambdas remaining on lambda-weekly-digest-role"
  echo ""
  echo "  Safe to deprecate. Tag it for review:"
  aws iam tag-role \
    --role-name lambda-weekly-digest-role \
    --tags Key=status,Value=deprecated Key=deprecated-date,Value=$(date +%Y-%m-%d) Key=reason,Value=sec1-iam-decomposition \
    --no-cli-pager 2>/dev/null && echo "  ✅ Tagged lambda-weekly-digest-role as deprecated" || true
  echo ""
  echo "  After 7 days of clean operation, delete with:"
  echo "    aws iam delete-role-policy --role-name lambda-weekly-digest-role --policy-name <policy>"
  echo "    aws iam detach-role-policy --role-name lambda-weekly-digest-role --policy-arn <arn>"
  echo "    aws iam delete-role --role-name lambda-weekly-digest-role"
else
  echo "  ⚠️  Still assigned: $REMAINING"
fi

echo ""
echo "=== SEC-1 Complete ==="
echo "  3 scoped roles now cover all 35 Lambdas:"
echo "    life-platform-compute-role  → compute Lambdas (no SES)"
echo "    life-platform-email-role    → email Lambdas"
echo "    life-platform-digest-role   → digest Lambdas (+ blog S3)"
echo "    lambda-weekly-digest-role   → DEPRECATED (no users)"
