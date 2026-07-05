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
# #544: methods_registry.py has exactly one Lambda consumer (site-api's /api/methods) —
# not shared-layer-worthy (the layer is for multi-Lambda-shared modules, ADR/convention
# matching vacation_fund.py's "shared by MCP, site-api, daily-brief" bar). Stage it as a
# top-level sibling instead; its own `import calibration_core`/`import stats_core` still
# resolve fine at runtime because those ARE layer modules already attached to site-api.
cp "$ROOT"/lambdas/methods_registry.py /tmp/siteapi/methods_registry.py
( cd /tmp/siteapi && zip -rq /tmp/siteapi.zip web/ reading/ methods_registry.py -x '*__pycache__*' '*.pyc' )

echo "→ Deploying $FN …"
aws lambda update-function-code --function-name "$FN" \
  --zip-file fileb:///tmp/siteapi.zip --region "$REGION" \
  --output text --query 'CodeSha256'

echo "→ Waiting for the code update to settle …"
aws lambda wait function-updated --function-name "$FN" --region "$REGION"

# site-api is NOT CDK-managed — nothing else attaches the shared layer to it, so a
# SHARED_LAYER_VERSION bump would silently leave it on the old layer (this broke #535's
# /api/journey CI and #538's /api/calibration import). Pin it to the current layer here,
# reading the ONE source of truth (cdk/stacks/constants.py). See
# reference_site_api_layer_manual_attach.
CONSTANTS="$ROOT/cdk/stacks/constants.py"
LAYER_VER="$(grep -E '^SHARED_LAYER_VERSION *= *[0-9]+' "$CONSTANTS" | grep -oE '[0-9]+' | head -1)"
ACCT="$(grep -E '^ACCT *= *' "$CONSTANTS" | grep -oE '[0-9]{6,}' | head -1)"
if [ -n "$LAYER_VER" ] && [ -n "$ACCT" ]; then
  LAYER_ARN="arn:aws:lambda:${REGION}:${ACCT}:layer:life-platform-shared-utils:${LAYER_VER}"
  CUR_ARN="$(aws lambda get-function-configuration --function-name "$FN" --region "$REGION" \
    --query 'Layers[0].Arn' --output text 2>/dev/null || echo '')"
  if [ "$CUR_ARN" != "$LAYER_ARN" ]; then
    echo "→ Attaching shared layer v${LAYER_VER} (was: ${CUR_ARN##*:}) …"
    aws lambda update-function-configuration --function-name "$FN" --region "$REGION" \
      --layers "$LAYER_ARN" --output text --query 'LastModified' >/dev/null
    aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  else
    echo "→ Shared layer already v${LAYER_VER} — no change."
  fi
else
  echo "⚠️  Could not parse SHARED_LAYER_VERSION/ACCT from $CONSTANTS — layer NOT synced. Attach manually."
fi

echo "→ Verifying handler import via $VERIFY_PATH …"
aws lambda invoke --function-name "$FN" --region "$REGION" --cli-binary-format raw-in-base64-out \
  --payload "{\"rawPath\":\"$VERIFY_PATH\",\"requestContext\":{\"http\":{\"method\":\"GET\",\"path\":\"$VERIFY_PATH\"}}}" \
  /tmp/siteapi_verify.json >/dev/null
python3 -c "import json,sys; d=json.load(open('/tmp/siteapi_verify.json')); \
assert 'errorType' not in d, ('HANDLER FAILED: '+json.dumps(d)[:300]); \
print('✅ site-api OK — status', d.get('statusCode'), 'on $VERIFY_PATH')"
