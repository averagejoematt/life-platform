#!/usr/bin/env bash
# deploy_fleet.sh — push the ONE full-tree code bundle to every function (#781).
#
# The shared layer is retired: shared modules ship inside each function's code
# bundle. A change to a shared module (ai_calls.py, stats_core.py, …) therefore
# reaches the fleet by re-uploading the bundle to every function — this script
# does that with ONE zip built + ONE S3 upload + N fast update-function-code
# calls. Deterministic, list-free: no curated "consumers" list to drift.
#
# Safety: before updating a function, its LIVE handler is resolved against the
# staged bundle — if the handler's module file isn't in the bundle at the
# expected path (e.g. the us-east-1 email-subscriber's flat handler), the
# function is SKIPPED with a warning instead of being bricked.
#
# MCP (life-platform-mcp + -warmer) gets the mcp-shaped bundle (tree + mcp/).
# Layer config is never touched — garth/pillow dependency layers stay attached.
#
# Usage:  bash deploy/deploy_fleet.sh [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEFAULT_REGION="us-west-2"
BUCKET="matthew-life-platform"
LAMBDA_MAP="${LAMBDA_MAP:-ci/lambda_map.json}"
DRY_RUN="${1:-}"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
# #2377: the ancestry check speaks in FULL shas, matching what build_bundle.py
# stamps into build_info.json (CI's GITHUB_SHA first — a merge-ref checkout can
# leave HEAD pointing somewhere other than the sha the run was dispatched for).
SHA_FULL="${BUNDLE_GIT_SHA:-${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo "")}}"

STAGE=/tmp/fleet_stage
STAGE_MCP=/tmp/fleet_stage_mcp
ZIP_TREE=/tmp/fleet_tree.zip
ZIP_MCP=/tmp/fleet_mcp.zip

echo "── 1. Build bundles (deploy/build_bundle.py) ──"
python3 deploy/build_bundle.py --out "$STAGE" --zip "$ZIP_TREE"
python3 deploy/build_bundle.py --mcp --out "$STAGE_MCP" --zip "$ZIP_MCP"

KEY_TREE="deploys/_fleet/tree-${SHA}.zip"
KEY_MCP="deploys/_fleet/mcp-${SHA}.zip"

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "DRY RUN — would upload $ZIP_TREE → s3://$BUCKET/$KEY_TREE and update:"
else
  echo "── 2. Upload bundles to S3 ──"
  aws s3 cp "$ZIP_TREE" "s3://$BUCKET/$KEY_TREE" --region "$DEFAULT_REGION" --no-cli-pager >/dev/null
  aws s3 cp "$ZIP_MCP" "s3://$BUCKET/$KEY_MCP" --region "$DEFAULT_REGION" --no-cli-pager >/dev/null
fi

echo "── 3. Fleet update ──"
UPDATED=0; SKIPPED=0; FAILED=0
declare -a UPDATED_FNS=()

# #2377 ancestry gate. The fleet ships ONE identical bundle to every function, so
# one probe answers for all of them — downloading 100+ live zips to ask the same
# question would be the "slows deploys materially" failure mode. The probe is the
# first function we would actually update (no hardcoded name to drift), and the
# check runs BEFORE that first update, so a refusal leaves the fleet untouched.
ANCESTRY_PROBE=""
ANCESTRY_PROBE_REGION="$DEFAULT_REGION"

# #1848: keep the per-function rollback artifact store honest on FLEET deploys too.
# rollback_lambda.sh (and the CI auto-rollback job) redeploy deploys/<fn>/previous.zip;
# before this, only deploy_lambda.sh single-function deploys rotated those artifacts,
# so after a fleet deploy the store pointed at arbitrarily stale zips — the 2026-07-26
# auto-rollback reverted 50 functions to pre-wave code because of exactly that.
# Server-side S3 copies only; called AFTER a successful update so latest.zip == live.
seed_artifacts() {
  local FN="$1" SRC_KEY="$2"
  local LATEST="deploys/${FN}/latest.zip"
  if aws s3 ls "s3://$BUCKET/$LATEST" --region "$DEFAULT_REGION" >/dev/null 2>&1; then
    aws s3 cp "s3://$BUCKET/$LATEST" "s3://$BUCKET/deploys/${FN}/previous.zip" \
      --region "$DEFAULT_REGION" --no-cli-pager >/dev/null
  fi
  aws s3 cp "s3://$BUCKET/$SRC_KEY" "s3://$BUCKET/$LATEST" \
    --region "$DEFAULT_REGION" --no-cli-pager >/dev/null
}

# Unique (function, region) pairs from the map; region defaults to us-west-2.
while IFS=$'\t' read -r FUNC REGION NOT_DEPLOYED; do
  [ -n "$FUNC" ] || continue
  if [ "$NOT_DEPLOYED" = "true" ]; then
    echo "  ⏭️  $FUNC — not_deployed flag"; SKIPPED=$((SKIPPED+1)); continue
  fi
  # Resolve the live handler → expected file path in the bundle.
  HANDLER=$(aws lambda get-function-configuration --function-name "$FUNC" --region "$REGION" \
      --query Handler --output text --no-cli-pager 2>/dev/null) || {
    echo "  ⏭️  $FUNC — not found in $REGION"; SKIPPED=$((SKIPPED+1)); continue; }
  MODULE_PATH="${HANDLER%.*}"; EXPECTED="${MODULE_PATH//.//}.py"
  if [ ! -f "$STAGE/$EXPECTED" ]; then
    echo "  ⏭️  $FUNC — handler $HANDLER not in bundle ($EXPECTED missing); left as-is"
    SKIPPED=$((SKIPPED+1)); continue
  fi
  if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "  ✓ would update $FUNC ($REGION, handler $HANDLER)"; UPDATED=$((UPDATED+1)); continue
  fi
  if [ -z "$ANCESTRY_PROBE" ]; then
    ANCESTRY_PROBE="$FUNC"; ANCESTRY_PROBE_REGION="$REGION"
    if ! AWS_REGION="$REGION" bash "$ROOT/deploy/verify_bundle_ancestry.sh" "$FUNC" preflight "$SHA_FULL"; then
      echo "❌ Aborting the FLEET deploy — see the [ancestry] line above. Nothing was updated."
      exit 1
    fi
  fi
  # us-east-1 functions can't read a us-west-2 S3 object via S3Key — direct upload.
  if [ "$REGION" = "$DEFAULT_REGION" ]; then
    aws lambda update-function-code --function-name "$FUNC" --region "$REGION" \
      --s3-bucket "$BUCKET" --s3-key "$KEY_TREE" --no-cli-pager >/dev/null \
      && { echo "  ✅ $FUNC"; UPDATED=$((UPDATED+1)); UPDATED_FNS+=("$FUNC:$REGION"); seed_artifacts "$FUNC" "$KEY_TREE"; } \
      || { echo "  ❌ $FUNC"; FAILED=$((FAILED+1)); }
  else
    aws lambda update-function-code --function-name "$FUNC" --region "$REGION" \
      --zip-file "fileb://$ZIP_TREE" --no-cli-pager >/dev/null \
      && { echo "  ✅ $FUNC ($REGION)"; UPDATED=$((UPDATED+1)); UPDATED_FNS+=("$FUNC:$REGION"); seed_artifacts "$FUNC" "$KEY_TREE"; } \
      || { echo "  ❌ $FUNC ($REGION)"; FAILED=$((FAILED+1)); }
  fi
done < <(jq -r '.lambdas | to_entries[] | [.value.function, (.value.region // "us-west-2"), ((.value.not_deployed // false)|tostring)] | @tsv' "$LAMBDA_MAP" | sort -u)

echo "── 4. MCP bundle (life-platform-mcp + warmer) ──"
for FN in life-platform-mcp life-platform-mcp-warmer; do
  if [ "$DRY_RUN" = "--dry-run" ]; then echo "  ✓ would update $FN (mcp bundle)"; continue; fi
  aws lambda update-function-code --function-name "$FN" --region "$DEFAULT_REGION" \
    --s3-bucket "$BUCKET" --s3-key "$KEY_MCP" --no-cli-pager >/dev/null \
    && { echo "  ✅ $FN"; UPDATED=$((UPDATED+1)); UPDATED_FNS+=("$FN:$DEFAULT_REGION"); seed_artifacts "$FN" "$KEY_MCP"; } \
    || { echo "  ❌ $FN"; FAILED=$((FAILED+1)); }
done

if [ "$DRY_RUN" != "--dry-run" ] && [ ${#UPDATED_FNS[@]} -gt 0 ]; then
  echo "── 5. Wait for updates to settle ──"
  for entry in "${UPDATED_FNS[@]}"; do
    aws lambda wait function-updated --function-name "${entry%%:*}" --region "${entry##*:}" || true
  done
fi

POSTFLIGHT_RC=0
if [ "$DRY_RUN" != "--dry-run" ] && [ -n "$ANCESTRY_PROBE" ]; then
  echo "── 6. Ancestry postflight (#2377) ──"
  AWS_REGION="$ANCESTRY_PROBE_REGION" bash "$ROOT/deploy/verify_bundle_ancestry.sh" \
    "$ANCESTRY_PROBE" postflight "$SHA_FULL" || POSTFLIGHT_RC=$?
fi

echo ""
echo "═══ Fleet deploy: $UPDATED updated, $SKIPPED skipped, $FAILED failed ═══"
if [ "$POSTFLIGHT_RC" -ne 0 ]; then
  echo "❌ POSTFLIGHT MISMATCH on $ANCESTRY_PROBE — the live bundle is not the one this run shipped."
  exit 1
fi
[ "$FAILED" -eq 0 ] || exit 1
