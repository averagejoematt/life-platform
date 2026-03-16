#!/usr/bin/env bash
# deploy_web_stack.sh — Deploy LifePlatformWeb CDK stack
#
# Creates:
#   - life-platform-site-api Lambda (read-only, reserved concurrency=20)
#   - Lambda Function URL
#   - averagejoematt.com CloudFront distribution (S3 + Lambda origins)
#
# Prerequisites:
#   1. CERT_ARN_AMJ in cdk/stacks/web_stack.py must be updated (not PLACEHOLDER)
#      Run: bash deploy/request_amj_cert.sh first
#   2. CDK venv must exist: cd cdk && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
#
# ⚠️  Cost warning: CloudFront distribution creation is free. Lambda reserved
#     concurrency=20 is the viral defence cap. WAF is NOT yet wired (see Step 4
#     in deploy notes) — add it after confirming the site is live.
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")/.."

# Guard: refuse to deploy if cert ARN is still the placeholder
if grep -q "PLACEHOLDER-request-cert-first" cdk/stacks/web_stack.py; then
  echo "❌ CERT_ARN_AMJ in cdk/stacks/web_stack.py is still a placeholder."
  echo "   Run: bash deploy/request_amj_cert.sh"
  echo "   Then update CERT_ARN_AMJ and re-run this script."
  exit 1
fi

echo "=== LifePlatformWeb CDK deploy ==="
echo ""

cd cdk
source .venv/bin/activate

echo "--- CDK diff (preview) ---"
npx cdk diff LifePlatformWeb 2>&1 | head -60
echo ""

read -p "Proceed with deploy? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

echo ""
echo "--- Deploying LifePlatformWeb ---"
npx cdk deploy LifePlatformWeb --require-approval never 2>&1

echo ""
echo "--- Running smoke tests ---"
cd ..
bash deploy/post_cdk_reconcile_smoke.sh

echo ""
echo "✅ LifePlatformWeb deployed."
echo ""
echo "Next steps:"
echo "  1. Find the CloudFront domain from CDK outputs (AmjDistributionDomain)"
echo "  2. Run: bash deploy/point_route53_to_cloudfront.sh"
echo "  3. Sync the site: bash deploy/sync_site_to_s3.sh"
echo "  4. Test live: curl -I https://averagejoematt.com"
