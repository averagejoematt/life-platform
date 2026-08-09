#!/usr/bin/env bash
# verify_bundle_ancestry.sh — read the LIVE bundle's commit fingerprint and
# classify the deploy we are about to make (or just made). #2377
#
# WHY: `verify_deployed_symbol.sh` answers "is this symbol live?" — you have to
# already know which symbol to look for. This answers the structural question:
# WHICH COMMIT is live, and is the tree we are shipping a descendant of it?
# 2026-08-08 an older CI run deployed after a newer merge; nothing refused it.
#
# Usage:
#   bash deploy/verify_bundle_ancestry.sh <function-name> [preflight|postflight] [shipping-sha]
#
#   preflight  (default) — run BEFORE update-function-code. Exit 2 = REFUSE:
#              the shipping tree is an ancestor of, or diverged from, what is live.
#   postflight           — run AFTER. Exit 2 = what landed is not what you shipped.
#
# shipping-sha defaults to $BUNDLE_GIT_SHA, then $GITHUB_SHA, then git HEAD —
# the same resolution order build_bundle.py stamps into the bundle.
#
# Escape hatches:
#   ALLOW_NON_FAST_FORWARD=1  deliberate rollback: refusal → loud warning.
#   SKIP_ANCESTRY_CHECK=1     skip entirely (exit 0) — break-glass only.
#
# Fail-soft by design: if AWS/curl/unzip can't produce a fingerprint we print an
# UNKNOWN line and exit 0. An unverifiable deploy must be visible, not blocked.
set -uo pipefail

FN="${1:?usage: verify_bundle_ancestry.sh <function-name> [preflight|postflight] [shipping-sha]}"
MODE="${2:-preflight}"
REGION="${AWS_REGION:-us-west-2}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${SKIP_ANCESTRY_CHECK:-}" = "1" ]; then
  echo "[ancestry] ⏭️  SKIP_ANCESTRY_CHECK=1 — ${MODE} skipped for ${FN}"
  exit 0
fi

SHIPPING="${3:-}"
if [ -z "${SHIPPING}" ]; then
  SHIPPING="${BUNDLE_GIT_SHA:-${GITHUB_SHA:-$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || echo "")}}"
fi
if [ -z "${SHIPPING}" ]; then
  echo "[ancestry] ⚠️  ${MODE} for ${FN}: no shipping sha resolvable (not a git checkout?) — unverified, allowing"
  exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

URL="$(aws lambda get-function --function-name "${FN}" --region "${REGION}" \
        --query 'Code.Location' --output text --no-cli-pager 2>/dev/null)"
if [ -z "${URL}" ] || [ "${URL}" = "None" ]; then
  echo "[ancestry] ⚠️  ${MODE} for ${FN}: could not read the deployed code location — unverified, allowing"
  exit 0
fi

DEPLOYED="-"
if curl -sf -o "${WORK}/fn.zip" "${URL}" 2>/dev/null; then
  # Extract ONLY build_info.json — a 2.5 MB bundle, one small member.
  if unzip -o -q -j "${WORK}/fn.zip" build_info.json -d "${WORK}" 2>/dev/null && [ -f "${WORK}/build_info.json" ]; then
    DEPLOYED="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("git_sha") or "-")' "${WORK}/build_info.json" 2>/dev/null || echo "-")"
  else
    echo "[ancestry] ℹ️  ${FN}'s live bundle carries no build_info.json (deployed before #2377, or by a path that predates it)"
  fi
else
  echo "[ancestry] ⚠️  ${MODE} for ${FN}: bundle download failed — unverified, allowing"
  exit 0
fi

python3 "${ROOT}/deploy/bundle_ancestry.py" \
  --deployed "${DEPLOYED}" --shipping "${SHIPPING}" --mode "${MODE}" --function "${FN}"
exit $?
