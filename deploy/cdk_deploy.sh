#!/usr/bin/env bash
# cdk_deploy.sh — the guarded path for `cdk deploy` (#382).
#
# Wraps `npx cdk deploy` with deploy/check_deploy_drift.py, which blocks when:
#   (a) this checkout is missing lambdas/cdk/mcp commits already on
#       origin/main — deploying would ship STALE code over a directly-pushed
#       fix (CONVENTIONS.md §2/§3's "deploy from main" reflex, now enforced); or
#   (b) CloudFormation drift-detection shows a live Lambda's Code has diverged
#       from the stack(s) you're about to deploy — a deploy_lambda.sh push
#       happened since the last cdk deploy, and a blind deploy would clobber it.
#
# Usage:
#   bash deploy/cdk_deploy.sh <StackName> [<StackName> ...] [-- <extra cdk args>]
#
# Examples:
#   bash deploy/cdk_deploy.sh LifePlatformCore
#   bash deploy/cdk_deploy.sh LifePlatformIngestion LifePlatformCompute -- --require-approval never
#
# Overrides (rare, intentional — mirrors sync_site_to_s3.sh's ALLOW_STALE_SITE):
#   ALLOW_STALE_DEPLOY_CHECKOUT=1 bash deploy/cdk_deploy.sh <Stack>
#   ALLOW_LIVE_LAMBDA_DRIFT=1 bash deploy/cdk_deploy.sh <Stack>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -eq 0 ]; then
    echo "Usage: bash deploy/cdk_deploy.sh <StackName> [<StackName> ...] [-- <extra cdk args>]" >&2
    exit 1
fi

STACKS=()
EXTRA=()
_in_extra=0
for a in "$@"; do
    if [ "$a" = "--" ]; then
        _in_extra=1
        continue
    fi
    if [ "$_in_extra" -eq 1 ]; then
        EXTRA+=("$a")
    else
        STACKS+=("$a")
    fi
done

GUARD_ARGS=()
if [ "${ALLOW_STALE_DEPLOY_CHECKOUT:-0}" = "1" ]; then
    GUARD_ARGS+=("--allow-stale-checkout")
fi
if [ "${ALLOW_LIVE_LAMBDA_DRIFT:-0}" = "1" ]; then
    GUARD_ARGS+=("--allow-live-drift")
fi

echo "→ dual-deployment-plane guard (checkout freshness + live-code drift)…"
python3 "$ROOT/deploy/check_deploy_drift.py" "${STACKS[@]}" "${GUARD_ARGS[@]+"${GUARD_ARGS[@]}"}"

echo "→ guard passed. Deploying: ${STACKS[*]}"
(cd "$ROOT/cdk" && npx cdk deploy "${STACKS[@]}" "${EXTRA[@]+"${EXTRA[@]}"}")
