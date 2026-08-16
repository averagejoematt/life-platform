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

# ── Toolchain parity (#2468 postmortem, 2026-08-16) ───────────────────────────
# Synth output depends on WHICH aws-cdk-lib the spawned `python3 app.py` resolves,
# and that is environment roulette: the night this landed, three different libs
# lived on one machine (system 2.244.0, a stale cdk/.venv 2.241.0, the pin
# 2.263.0) and `cdk` did not even honor an activated venv's PATH. Deploys made
# from a stale lib can NEVER converge with CI's pinned synth — that is exactly
# how seven "cannot ship" config-drift warnings stood for a week while stack
# deploys kept "fixing" them. So this wrapper owns its toolchain: refresh
# cdk/.venv from the pin file and synth through its absolute interpreter path,
# byte-matching the venv CI's Plan job builds fresh on every run.
echo "→ toolchain parity: cdk/.venv ← cdk/requirements.txt…"
python3 -m venv "$ROOT/cdk/.venv"
"$ROOT/cdk/.venv/bin/pip" install -q -r "$ROOT/cdk/requirements.txt"
APP_OVERRIDE=(--app "$ROOT/cdk/.venv/bin/python3 app.py")

echo "→ guard passed. Deploying: ${STACKS[*]}"
(cd "$ROOT/cdk" && npx cdk deploy "${STACKS[@]}" "${APP_OVERRIDE[@]}" "${EXTRA[@]+"${EXTRA[@]}"}")
