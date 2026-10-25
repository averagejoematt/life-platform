#!/bin/bash
# rollback_fleet.sh — CI auto-rollback of the whole Lambda fleet (moved out of ci-cd.yml, #5316).
#
# #4255: every code deploy is a fleet deploy (deploy/deploy_fleet.sh), which redeploys and
# re-seeds deploys/<fn>/previous.zip for EVERY mapped function plus both MCP functions. So
# the rollback set is always that same list, rebuilt from ci/lambda_map.json — the source
# deploy_fleet.sh iterates (#1859 gap 2 was the per-function deploy_matrix reading "[]" on
# a fleet push; there is no other path now).
#
# ROLLBACK_EXPECT_SHA (#5316) is passed through to rollback_lambda.sh: a function whose
# live build is not that sha is owned by a newer deploy and is SKIPPED_NEWER, never
# reverted. Tally (#1848 + #5316): reverted / no-artifact / skipped-newer / failed.
# Exit 1 only when a revert was attempted and broke.
#
# Usage: ROLLBACK_EXPECT_SHA="<sha> [<sha>]" bash deploy/rollback_fleet.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAMBDA_MAP="${LAMBDA_MAP:-$ROOT/ci/lambda_map.json}"

echo "⚠️  Smoke test failed after successful deploy — initiating auto-rollback"
if [ -n "${ROLLBACK_EXPECT_SHA:-}" ]; then
  echo "   reverting only functions still live on: ${ROLLBACK_EXPECT_SHA} (#5316)"
else
  echo "::warning::ROLLBACK_EXPECT_SHA is unset — reverting every function unconditionally (pre-#5316 behaviour)"
fi
echo ""

MATRIX=$(jq -c '[.lambdas | to_entries[] | select((.value.not_deployed // false) | not) | {function: .value.function}]
                       + [{function:"life-platform-mcp"}, {function:"life-platform-mcp-warmer"}]
                       | unique_by(.function)' "$LAMBDA_MAP")
COUNT=$(echo "$MATRIX" | jq 'length')
echo "   $COUNT function(s) to roll back"

ROLLED_BACK=0
MISSING=0
SKIPPED_NEWER=0
FAILED=0
declare -a SKIPPED_FNS=()

# rollback_lambda.sh exit codes (#1848, #5316): 0 = reverted, 2 = no previous.zip
# (function LEFT ON CURRENT CODE — report, don't fail), 3 = SKIPPED_NEWER (a newer
# deploy owns it — report, don't fail), else = attempted and broke (manual intervention).
for FUNC in $(echo "$MATRIX" | jq -r '.[].function'); do
  echo "→ Rolling back $FUNC..."
  RC=0
  bash "$ROOT/deploy/rollback_lambda.sh" "$FUNC" || RC=$?
  case "$RC" in
    0) ROLLED_BACK=$((ROLLED_BACK + 1)) ;;
    2) MISSING=$((MISSING + 1)) ;;
    3) SKIPPED_NEWER=$((SKIPPED_NEWER + 1)); SKIPPED_FNS+=("$FUNC") ;;
    *) echo "  ❌ Rollback failed for $FUNC — manual intervention required"
       FAILED=$((FAILED + 1)) ;;
  esac
done

echo ""
echo "═══ Rollback complete: $ROLLED_BACK reverted, $MISSING no-artifact (left on current code), $SKIPPED_NEWER skipped-newer (left on current code), $FAILED failed ═══"

if [ "$SKIPPED_NEWER" -gt 0 ]; then
  echo "::warning::$SKIPPED_NEWER function(s) SKIPPED_NEWER — their live build is not this run's deploy (a newer deploy owns them, or the sha was unreadable): ${SKIPPED_FNS[*]}"
fi
if [ "$MISSING" -gt 0 ]; then
  echo "::warning::$MISSING function(s) had no previous.zip and stayed on the just-deployed code — the fleet is MIXED-VERSION if any reverted. Verify before trusting either state."
fi
if [ "$FAILED" -gt 0 ]; then
  echo "::error::$FAILED Lambda(s) could not be rolled back — manual redeploy required"
  exit 1
fi

echo "✅ Rollback pass finished. Investigate smoke test failure before re-deploying."
