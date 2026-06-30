#!/usr/bin/env bash
# deploy/deploy_site_api.sh — deploy life-platform-site-api as the FULL web/ package.
#
# site_api_lambda imports many web/ siblings (site_api_common, _coach, _vitals, …),
# so a single-file deploy breaks it (Runtime.ImportModuleError, ADR-046). This
# always ships the whole web/ dir, then verifies the handler imported by invoking
# a real route — not just a CloudFront 200 (which can cache a prior response).
#
# Usage:  bash deploy/deploy_site_api.sh [verify_path]
#   verify_path defaults to /api/status. Pass e.g. /api/coach_team to check a route.
set -euo pipefail

REGION="us-west-2"
FN="life-platform-site-api"
VERIFY_PATH="${1:-/api/status}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Packaging full web/ from $ROOT/lambdas/web/ …"
rm -rf /tmp/siteapi /tmp/siteapi.zip
mkdir -p /tmp/siteapi/web
cp "$ROOT"/lambdas/web/*.py /tmp/siteapi/web/
# ADR-097 (Phase C): site_api_reading imports the reading data-layer package.
# Stage lambdas/reading/ as a top-level package so `from reading import …`
# resolves at runtime (numeric/retry_utils come from the shared layer).
cp -r "$ROOT"/lambdas/reading /tmp/siteapi/reading
rm -rf /tmp/siteapi/reading/__pycache__
( cd /tmp/siteapi && zip -rq /tmp/siteapi.zip web/ reading/ -x '*__pycache__*' '*.pyc' )

echo "→ Deploying $FN …"
aws lambda update-function-code --function-name "$FN" \
  --zip-file fileb:///tmp/siteapi.zip --region "$REGION" \
  --output text --query 'CodeSha256'

echo "→ Waiting for the update to settle …"
aws lambda wait function-updated --function-name "$FN" --region "$REGION"

echo "→ Verifying handler import via $VERIFY_PATH …"
aws lambda invoke --function-name "$FN" --region "$REGION" --cli-binary-format raw-in-base64-out \
  --payload "{\"rawPath\":\"$VERIFY_PATH\",\"requestContext\":{\"http\":{\"method\":\"GET\",\"path\":\"$VERIFY_PATH\"}}}" \
  /tmp/siteapi_verify.json >/dev/null
python3 -c "import json,sys; d=json.load(open('/tmp/siteapi_verify.json')); \
assert 'errorType' not in d, ('HANDLER FAILED: '+json.dumps(d)[:300]); \
print('✅ site-api OK — status', d.get('statusCode'), 'on $VERIFY_PATH')"
