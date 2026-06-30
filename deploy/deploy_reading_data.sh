#!/usr/bin/env bash
#
# deploy_reading_data.sh — Phase A (reading data layer) deploy orchestrator
# (ADR-097, Mind pillar). RUN THIS YOURSELF; Claude does not execute deploys.
#
# Order matters: the GSIs must exist before the cover-pipeline Lambda (or anything
# else) queries them. Steps:
#   1. Add the two reading GSIs to the live table  (deploy_reading_gsis.sh)
#   2. cdk diff LifePlatformOperational            (REVIEW before applying)
#   3. cdk deploy LifePlatformOperational          (adds the reading-cover-pipeline Lambda)
#
# No layer rebuild (the reading modules bundle with the lambdas/ asset, not the
# shared layer) and no other stack changes. The cover Lambda is on-demand only
# (no EventBridge rule). Re-running is safe (GSIs idempotent; cdk is declarative).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${AWS_REGION:-us-west-2}"

echo "═══════════════════════════════════════════════════════════════"
echo " Phase A — reading data layer (ADR-097)"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. GSIs (additive, online backfill) ───────────────────────────────────────
echo "▶ Step 1/3 — reading GSIs (GSI1 sparse recall-due, GSI2 state/time)"
bash "$ROOT/deploy/deploy_reading_gsis.sh"

# ── 2. cdk diff (review gate) ─────────────────────────────────────────────────
echo "▶ Step 2/3 — cdk diff LifePlatformOperational (review the plan)"
echo "  Expect ONLY: + ReadingCoverPipeline Lambda + its dedicated role/policy/alarm/log group,"
echo "  and a benign re-hash of the shared lambdas/ Code.from_asset (same asset, new content hash)."
echo "  There must be NO destroys, NO IAM changes to existing roles, NO table changes."
( cd "$ROOT/cdk" && npx cdk diff LifePlatformOperational )

read -r -p $'\n  Proceed with cdk deploy LifePlatformOperational? [y/N] ' ans
if [ "${ans:-N}" != "y" ] && [ "${ans:-N}" != "Y" ]; then
  echo "✋ Aborted before deploy. GSIs (step 1) are already applied and are safe to keep."
  exit 0
fi

# ── 3. cdk deploy ─────────────────────────────────────────────────────────────
echo "▶ Step 3/3 — cdk deploy LifePlatformOperational"
( cd "$ROOT/cdk" && npx cdk deploy LifePlatformOperational --require-approval never )

# ── verify ────────────────────────────────────────────────────────────────────
echo "▶ verify the Lambda is live"
aws lambda get-function --function-name reading-cover-pipeline --region "$REGION" \
  --query 'Configuration.{Name:FunctionName,Runtime:Runtime,Handler:Handler,CodeSize:CodeSize,State:State}' --output table

echo "✅ Phase A deployed. Optional smoke test (writes a real cover to generated/covers/):"
cat <<'SMOKE'
   aws lambda invoke --function-name reading-cover-pipeline --region us-west-2 \
     --cli-binary-format raw-in-base64-out \
     --payload '{"title":"Project Hail Mary","author":"Andy Weir","isbn13":"9780593135204"}' \
     /tmp/reading_cover_out.json && cat /tmp/reading_cover_out.json
SMOKE
