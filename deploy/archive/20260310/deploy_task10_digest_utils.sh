#!/usr/bin/env bash
# deploy_task10_digest_utils.sh
# Task 10: Deploy digest_utils consolidation to weekly-digest and monthly-digest.
#
# digest_utils.py is a shared pure-Python module bundled into both zips.
#
# Changes deployed:
#   weekly_digest_lambda.py  — imports from digest_utils (removed local defs)
#   monthly_digest_lambda.py — imports from digest_utils + 5 bug fixes:
#       1. ex_macrofactor: wrong field names (calories/protein_g -> total_calories_kcal/total_protein_g)
#       2. ex_macrofactor: hardcoded targets -> profile-driven
#       3. Profile SK: PROFILE -> PROFILE#v1
#       4. dedup_activities now applied in ex_strava
#       5. compute_banister: uses shared compute_banister_from_list (includes dedup)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LAMBDAS_DIR="$REPO_ROOT/lambdas"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy_lambda.sh"

if [[ ! -f "$DEPLOY_SCRIPT" ]]; then
  echo "ERROR: deploy_lambda.sh not found at $DEPLOY_SCRIPT"
  exit 1
fi

echo "=== Task 10: Deploy digest_utils consolidation ==="
echo ""

echo "--- Deploying weekly-digest ---"
# Handler: digest_handler.lambda_handler → deploy_lambda.sh renames source to digest_handler.py
bash "$DEPLOY_SCRIPT" weekly-digest \
  "$LAMBDAS_DIR/weekly_digest_lambda.py" \
  --extra-files "$LAMBDAS_DIR/digest_utils.py"

echo "Waiting 10s before next deploy..."
sleep 10

echo "--- Deploying monthly-digest ---"
# Handler: monthly_digest_lambda.lambda_handler → filename matches source
bash "$DEPLOY_SCRIPT" monthly-digest \
  "$LAMBDAS_DIR/monthly_digest_lambda.py" \
  --extra-files "$LAMBDAS_DIR/digest_utils.py"

echo ""
echo "=== Done. ==="
echo ""
echo "Verify via CloudWatch logs:"
echo "  weekly-digest:  aws logs tail /aws/lambda/weekly-digest --since 5m --region us-west-2"
echo "  monthly-digest: aws logs tail /aws/lambda/monthly-digest --since 5m --region us-west-2"
