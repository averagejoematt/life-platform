#!/usr/bin/env bash
# deploy/deploy_site_api.sh — deploy life-platform-site-api with the full bundle.
#
# #781: site-api ships the SAME staged full-tree bundle as every other function
# (deploy/build_bundle.py) — web/, reading/, methods_registry.py, and all shared
# modules are inside the bundle, so there is no shared layer to attach and no
# partial zip that can break imports (ADR-046 / #535 / #538 incident classes).
# Then verifies the handler imported by invoking a real route — not just a
# CloudFront 200 (which can cache a prior response).
#
# Usage:  bash deploy/deploy_site_api.sh [verify_path]
#   verify_path defaults to /api/status. Pass e.g. /api/coach_team to check a route.
set -euo pipefail

REGION="us-west-2"
FN="life-platform-site-api"
VERIFY_PATH="${1:-/api/status}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Staging the full bundle (deploy/build_bundle.py) …"
python3 "$ROOT/deploy/build_bundle.py" --out /tmp/siteapi_stage --zip /tmp/siteapi.zip

echo "→ Deploying $FN …"
aws lambda update-function-code --function-name "$FN" \
  --zip-file fileb:///tmp/siteapi.zip --region "$REGION" \
  --output text --query 'CodeSha256'

echo "→ Waiting for the code update to settle …"
aws lambda wait function-updated --function-name "$FN" --region "$REGION"

echo "→ Verifying handler import via $VERIFY_PATH …"
aws lambda invoke --function-name "$FN" --region "$REGION" --cli-binary-format raw-in-base64-out \
  --payload "{\"rawPath\":\"$VERIFY_PATH\",\"requestContext\":{\"http\":{\"method\":\"GET\",\"path\":\"$VERIFY_PATH\"}}}" \
  /tmp/siteapi_verify.json >/dev/null
python3 -c "import json,sys; d=json.load(open('/tmp/siteapi_verify.json')); \
assert 'errorType' not in d, ('HANDLER FAILED: '+json.dumps(d)[:300]); \
print('✅ site-api OK — status', d.get('statusCode'), 'on $VERIFY_PATH')"
