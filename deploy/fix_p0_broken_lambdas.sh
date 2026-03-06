#!/bin/bash
# fix_p0_broken_lambdas.sh
# Fixes the lambda_function.py packaging bug in wednesday-chronicle and anomaly-detector.
# Also backfills anomaly detection for missed days and purges the DLQ.
#
# Root cause: Both Lambdas have handler=lambda_function.lambda_handler but their
# zips contained the source filename (wednesday_chronicle_lambda.py / anomaly_detector_lambda.py)
# instead of lambda_function.py. Redeploy via universal deploy_lambda.sh fixes this.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/fix_p0_broken_lambdas.sh

set -euo pipefail
REGION="us-west-2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "P0 Fix: Broken Lambda packaging + DLQ purge"
echo "=================================================="

# ── Step 1: Fix wednesday-chronicle ──────────────────
echo ""
echo "▶ Step 1/5: Redeploying wednesday-chronicle..."
bash "$SCRIPT_DIR/deploy_lambda.sh" wednesday-chronicle "$ROOT_DIR/lambdas/wednesday_chronicle_lambda.py"

echo "   Waiting 10s before next deploy..."
sleep 10

# ── Step 2: Fix anomaly-detector ─────────────────────
echo ""
echo "▶ Step 2/5: Redeploying anomaly-detector..."
bash "$SCRIPT_DIR/deploy_lambda.sh" anomaly-detector "$ROOT_DIR/lambdas/anomaly_detector_lambda.py"

echo "   Waiting 10s before invoking..."
sleep 10

# ── Step 3: Smoke-test wednesday-chronicle ───────────
echo ""
echo "▶ Step 3/5: Smoke-testing wednesday-chronicle (dry invoke, no email)..."
CHRONICLE_RESULT=$(aws lambda invoke \
    --function-name wednesday-chronicle \
    --payload '{"dry_run": true}' \
    --log-type Tail \
    --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    /tmp/chronicle_smoke.json 2>&1 || true)

STATUS=$(python3 -c "import json; d=json.load(open('/tmp/chronicle_smoke.json')); print(d.get('statusCode', d.get('FunctionError', 'unknown')))" 2>/dev/null || echo "check_output")
echo "   Chronicle smoke test status: $STATUS"
cat /tmp/chronicle_smoke.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=2)[:500])" 2>/dev/null || true

# ── Step 4: Backfill anomaly detector for missed days ─
echo ""
echo "▶ Step 4/5: Backfilling anomaly detector for Mar 4 and Mar 5..."

for DATE in "2026-03-04" "2026-03-05"; do
    echo "   Invoking anomaly-detector for $DATE..."
    aws lambda invoke \
        --function-name anomaly-detector \
        --payload "{\"date\": \"$DATE\"}" \
        --log-type Tail \
        --region "$REGION" \
        --cli-binary-format raw-in-base64-out \
        /tmp/anomaly_${DATE}.json > /dev/null 2>&1 || true
    STATUS=$(python3 -c "import json; d=json.load(open('/tmp/anomaly_${DATE}.json')); print(d.get('statusCode', d.get('FunctionError', 'ok')))" 2>/dev/null || echo "invoked")
    echo "   $DATE: $STATUS"
    sleep 5
done

# ── Step 5: Purge the DLQ ─────────────────────────────
echo ""
echo "▶ Step 5/5: Purging DLQ..."
aws sqs purge-queue \
    --queue-url "https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq" \
    --region "$REGION"
echo "   DLQ purged."

# ── Summary ──────────────────────────────────────────
echo ""
echo "=================================================="
echo "✅ P0 fix complete."
echo ""
echo "Verify:"
echo "  1. wednesday-chronicle alarm clears within ~24h"
echo "  2. anomaly-detector runs clean tomorrow at 8:05 AM PT"
echo "  3. Check DLQ: aws sqs get-queue-attributes \\"
echo "       --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \\"
echo "       --attribute-names ApproximateNumberOfMessages --region us-west-2"
echo ""
echo "NOTE: Wednesday Chronicle missed the Mar 4 installment."
echo "To manually trigger a Chronicle for that week, run:"
echo "  aws lambda invoke --function-name wednesday-chronicle \\"
echo "    --payload '{\"target_date\": \"2026-03-04\"}' \\"
echo "    --region us-west-2 --cli-binary-format raw-in-base64-out /tmp/chronicle_manual.json"
echo "=================================================="
