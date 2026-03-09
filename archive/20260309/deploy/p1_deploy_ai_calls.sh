#!/bin/bash
# p1_deploy_ai_calls.sh — Deploy P1.8/P1.9: backoff + token metrics across all AI Lambdas
#
# Changes deployed:
#   - retry_utils.py: new shared module (4-attempt exponential backoff + CloudWatch metrics)
#   - ai_calls.py: updated call_anthropic() delegates to retry_utils
#   - All 7 email/digest Lambdas: local call_anthropic[_with_retry] delegates to retry_utils
#   - All hardcoded model strings replaced with os.environ.get("AI_MODEL", ...)
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_deploy_ai_calls.sh

set -euo pipefail
REGION="us-west-2"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P1.8/P1.9: Backoff + token metrics — all AI Lambdas       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Add CloudWatch permission to IAM roles
echo "── Step 1: Adding CloudWatch PutMetricData to IAM roles ──"
bash deploy/p1_add_cloudwatch_metrics_permission.sh
echo ""

# Step 2: Deploy each Lambda with retry_utils.py bundled
echo "── Step 2: Deploying Lambdas ──"
echo ""

# daily-brief — uses ai_calls.py (which now uses retry_utils internally)
echo "[ daily-brief ]"
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py \
                  lambdas/board_loader.py lambdas/retry_utils.py
sleep 10

# weekly-digest
echo "[ weekly-digest ]"
bash deploy/deploy_lambda.sh weekly-digest lambdas/weekly_digest_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py \
                  lambdas/board_loader.py lambdas/insight_writer.py lambdas/retry_utils.py
sleep 10

# monthly-digest
echo "[ monthly-digest ]"
bash deploy/deploy_lambda.sh monthly-digest lambdas/monthly_digest_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py lambdas/retry_utils.py
sleep 10

# nutrition-review
echo "[ nutrition-review ]"
bash deploy/deploy_lambda.sh nutrition-review lambdas/nutrition_review_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/retry_utils.py
sleep 10

# wednesday-chronicle
echo "[ wednesday-chronicle ]"
bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py lambdas/retry_utils.py
sleep 10

# weekly-plate
echo "[ weekly-plate ]"
bash deploy/deploy_lambda.sh weekly-plate lambdas/weekly_plate_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/retry_utils.py
sleep 10

# monday-compass
echo "[ monday-compass ]"
bash deploy/deploy_lambda.sh monday-compass lambdas/monday_compass_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/retry_utils.py

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P1.8/P1.9 Deploy Complete                               ║"
echo "║                                                              ║"
echo "║  All AI Lambdas now have:                                   ║"
echo "║  - 4-attempt exponential backoff (5s / 15s / 45s)           ║"
echo "║  - Token usage → CloudWatch LifePlatform/AI namespace        ║"
echo "║  - Failure metric on final retry exhaustion                  ║"
echo "║  - No hardcoded model strings                                ║"
echo "║                                                              ║"
echo "║  Verify after next Daily Brief (11 AM):                     ║"
echo "║    CloudWatch > Metrics > LifePlatform/AI > LambdaFunction  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
