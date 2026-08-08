#!/usr/bin/env bash
# Verify a symbol is present in a Lambda's ACTUALLY DEPLOYED code.
#
# WHY: a LastModified timestamp only tells you *a* deploy happened, not *which
# commit* it carried. With several CI/CD runs queued behind each other — the
# normal state during a merge queue — an earlier run can land after a later
# merge, so a fresh timestamp routinely accompanies stale code. The only honest
# check is to pull the deployed bundle and read it.
#
# Usage: bash deploy/verify_deployed_symbol.sh <function-name> <path-in-bundle> <symbol>
#   e.g. bash deploy/verify_deployed_symbol.sh daily-brief emails/daily_brief_lambda.py nutrition_delivery_public
#
# Exit 0 if present, 1 if absent — so it can gate a wait loop.
set -uo pipefail

FN="${1:?usage: verify_deployed_symbol.sh <function-name> <path-in-bundle> <symbol>}"
REL="${2:?missing path-in-bundle}"
SYM="${3:?missing symbol}"
REGION="${AWS_REGION:-us-west-2}"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

URL="$(aws lambda get-function --function-name "${FN}" --region "${REGION}" \
        --query 'Code.Location' --output text 2>/dev/null)" || {
  echo "[verify] could not read ${FN}'s code location"; exit 1; }

curl -s -o "${WORK}/fn.zip" "${URL}" || { echo "[verify] download failed"; exit 1; }
unzip -o -q "${WORK}/fn.zip" -d "${WORK}/code" 2>/dev/null || {
  echo "[verify] unzip failed"; exit 1; }

TARGET="${WORK}/code/${REL}"
if [ ! -f "${TARGET}" ]; then
  echo "[verify] ${REL} is NOT in ${FN}'s bundle at all"
  exit 1
fi

COUNT="$(grep -c "${SYM}" "${TARGET}" || true)"
STAMP="$(aws lambda get-function-configuration --function-name "${FN}" \
          --region "${REGION}" --query 'LastModified' --output text 2>/dev/null)"

if [ "${COUNT:-0}" -gt 0 ]; then
  echo "[verify] ✅ ${FN} (${STAMP}) — '${SYM}' present ${COUNT}x in ${REL}"
  exit 0
fi
echo "[verify] ❌ ${FN} (${STAMP}) — '${SYM}' ABSENT from ${REL}; the timestamp is not the commit you want"
exit 1
