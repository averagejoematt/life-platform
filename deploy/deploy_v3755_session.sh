#!/bin/bash
# deploy_v3755_session.sh — v3.7.55 Session Deploy
# Deploys: acwr-compute (new), email-subscriber (new), daily-brief (BS-02 stats),
#          wednesday-chronicle (subscribe CTA), mcp-server (new tools),
#          CDK LifePlatformCompute (ACWRCompute Lambda + EventBridge),
#          site/index.html + site/subscribe.html to S3
#
# Run order: CDK first (creates IAM roles), then individual Lambda deploys, then S3.
# Post-deploy: run post_cdk_reconcile_smoke.sh
#
# REQUIRES: aws CLI, CDK venv activated
# Usage: bash deploy/deploy_v3755_session.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== v3.7.55 Session Deploy ==="
echo ""

# ── 1. CDK deploy (LifePlatformCompute) — creates acwr-compute Lambda + EventBridge rule
echo "[1/7] CDK deploy LifePlatformCompute (acwr-compute Lambda)..."
source cdk/.venv/bin/activate
cd cdk
npx cdk deploy LifePlatformCompute --require-approval never
cd "$ROOT"
echo "      ✓ CDK LifePlatformCompute deployed"
echo ""

# ── 2. Deploy acwr-compute Lambda
echo "[2/7] Deploying acwr-compute..."
bash deploy/deploy_lambda.sh acwr-compute lambdas/acwr_compute_lambda.py
sleep 10
echo "      ✓ acwr-compute deployed"
echo ""

# ── 3. Deploy email-subscriber Lambda (new function — CDK LifePlatformOperational)
# NOTE: email-subscriber is NOT yet in CDK operational_stack.py.
# Manual creation required first time — see below.
# After first deploy, subsequent updates use deploy_lambda.sh normally.
#
# First-time manual creation:
#   aws lambda create-function \
#     --function-name email-subscriber \
#     --runtime python3.12 \
#     --handler email_subscriber_lambda.lambda_handler \
#     --role arn:aws:iam::205930651321:role/lambda-email-subscriber-role \
#     --environment Variables="{USER_ID=matthew,TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,EMAIL_SENDER=lifeplatform@mattsusername.com,SITE_URL=https://averagejoematt.com}" \
#     --timeout 15 --memory-size 256 \
#     --zip-file fileb:///tmp/email_subscriber.zip
#
# IAM role creation (one-time):
#   aws iam create-role --role-name lambda-email-subscriber-role \
#     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
#   # Then attach the policies from role_policies.operational_email_subscriber()
#
# For subsequent deploys (after first-time setup):
echo "[3/7] Deploying email-subscriber..."
echo "      NOTE: If this is first deploy, create the function manually — see script comments."
bash deploy/deploy_lambda.sh email-subscriber lambdas/email_subscriber_lambda.py
sleep 10
echo "      ✓ email-subscriber deployed"
echo ""

# ── 4. Deploy daily-brief (write_public_stats_json wired)
echo "[4/7] Deploying daily-brief (BS-02 public_stats_json)..."
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py
sleep 10
echo "      ✓ daily-brief deployed"
echo ""

# ── 5. Deploy wednesday-chronicle (subscribe CTA footer)
echo "[5/7] Deploying wednesday-chronicle (subscribe CTA)..."
bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py
sleep 10
echo "      ✓ wednesday-chronicle deployed"
echo ""

# ── 6. Deploy MCP server (get_essential_seven + get_acwr_status registered)
echo "[6/7] Deploying life-platform-mcp (new tools)..."
cd "$ROOT"
rm -f /tmp/mcp_deploy.zip
zip -j /tmp/mcp_deploy.zip mcp_server.py mcp_bridge.py
zip -r /tmp/mcp_deploy.zip mcp/
zip -j /tmp/mcp_deploy.zip lambdas/digest_utils.py  # compute_confidence now in digest_utils
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb:///tmp/mcp_deploy.zip \
  --cli-binary-format raw-in-base64-out \
  > /dev/null
echo "      ✓ life-platform-mcp deployed"
echo ""

# ── 7. Sync site/ to S3
echo "[7/7] Syncing site/ to S3..."
aws s3 cp site/index.html    s3://matthew-life-platform/site/index.html    --content-type "text/html" --cache-control "max-age=300"
aws s3 cp site/subscribe.html s3://matthew-life-platform/site/subscribe.html --content-type "text/html" --cache-control "max-age=300"
echo "      ✓ site/index.html + site/subscribe.html synced"
echo ""

# ── Post-deploy smoke test
echo "=== Running post-CDK smoke test ==="
bash deploy/post_cdk_reconcile_smoke.sh

echo ""
echo "=== v3.7.55 deploy complete ==="
echo ""
echo "Next steps:"
echo "  1. Trigger acwr-compute manually to backfill yesterday:"
echo "     aws lambda invoke --function-name acwr-compute --payload '{\"date\":\"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' --cli-binary-format raw-in-base64-out /tmp/acwr_out.json && cat /tmp/acwr_out.json"
echo "  2. Verify subscribe page: https://averagejoematt.com/subscribe"
echo "  3. Test subscribe flow: POST https://averagejoematt.com/api/subscribe"
echo "  4. Verify homepage hero loads public_stats.json on next Daily Brief run"
echo "  5. CloudFront invalidation (if needed): aws cloudfront create-invalidation --distribution-id <AMJ_DIST_ID> --paths '/*'"
echo ""
echo "IMPORTANT: email-subscriber Lambda needs API Gateway route /api/subscribe wired."
echo "  See docs/ARCHITECTURE.md — add to web_stack.py API Gateway config."
